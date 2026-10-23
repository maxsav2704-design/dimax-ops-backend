from __future__ import annotations

import smtplib
import ssl
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.integrations.email import smtp_sender


@pytest.fixture
def smtp(monkeypatch):
    config = SimpleNamespace(
        SMTP_HOST="smtp.dimax.example",
        SMTP_PORT=587,
        SMTP_TLS=True,
        SMTP_USER="test-mailer",
        SMTP_PASSWORD="synthetic-test-password",
        SMTP_FROM="notifications@dimax.example",
    )
    factory = MagicMock(spec=smtplib.SMTP)
    client = factory.return_value.__enter__.return_value
    monkeypatch.setattr(smtp_sender, "settings", config)
    monkeypatch.setattr(smtp_sender.smtplib, "SMTP", factory)
    return config, factory, client


def send(**kwargs):
    smtp_sender.SmtpEmailSender().send(
        to_email="factory@dimax.example",
        subject="Synthetic approval",
        body_text="Test only",
        **kwargs,
    )


def test_starttls_verifies_certificate_and_hostname_before_credentials(smtp):
    config, factory, client = smtp

    send()

    factory.assert_called_once_with(config.SMTP_HOST, 587, timeout=20)
    client.starttls.assert_called_once()
    context = client.starttls.call_args.kwargs["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.protocol == ssl.PROTOCOL_TLS_CLIENT
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.get_ca_certs(), "System trusted CA certificates must be loaded"
    client.login.assert_called_once_with(config.SMTP_USER, config.SMTP_PASSWORD)
    assert [call[0] for call in client.mock_calls] == ["starttls", "login", "send_message"]


@pytest.mark.parametrize(
    "error",
    [
        ssl.SSLCertVerificationError(1, "certificate has expired"),
        ssl.SSLCertVerificationError(1, "hostname mismatch"),
        ssl.SSLCertVerificationError(1, "self-signed certificate"),
        ssl.SSLError("TLS negotiation failed"),
        smtplib.SMTPNotSupportedError("STARTTLS is unavailable"),
    ],
    ids=["expired", "wrong-host", "untrusted", "handshake", "no-starttls"],
)
def test_tls_failure_never_authenticates_sends_or_falls_back(smtp, error):
    _, factory, client = smtp
    client.starttls.side_effect = error

    with pytest.raises(type(error)) as caught:
        send()

    assert caught.value is error
    factory.assert_called_once()
    client.starttls.assert_called_once()
    client.login.assert_not_called()
    client.send_message.assert_not_called()
    factory.return_value.__exit__.assert_called_once()


def test_context_failure_is_not_ignored(smtp, monkeypatch):
    _, _, client = smtp
    error = OSError("Cannot load trusted CA certificates")
    create_context = MagicMock(side_effect=error)
    monkeypatch.setattr(smtp_sender.ssl, "create_default_context", create_context)

    with pytest.raises(OSError) as caught:
        send()

    assert caught.value is error
    create_context.assert_called_once_with()
    client.starttls.assert_not_called()
    client.login.assert_not_called()
    client.send_message.assert_not_called()


def test_tls_can_send_without_smtp_authentication(smtp):
    config, _, client = smtp
    config.SMTP_USER = ""
    config.SMTP_PASSWORD = ""

    send()

    client.starttls.assert_called_once()
    client.login.assert_not_called()
    client.send_message.assert_called_once()


def test_local_mailpit_plaintext_mode_remains_explicit(smtp, monkeypatch):
    config, factory, client = smtp
    config.SMTP_HOST = "mailpit"
    config.SMTP_PORT = 1025
    config.SMTP_TLS = False
    config.SMTP_USER = ""
    config.SMTP_PASSWORD = ""
    create_context = MagicMock()
    monkeypatch.setattr(smtp_sender.ssl, "create_default_context", create_context)

    send()

    factory.assert_called_once_with("mailpit", 1025, timeout=20)
    create_context.assert_not_called()
    client.starttls.assert_not_called()
    client.login.assert_not_called()
    client.send_message.assert_called_once()


def test_tls_preserves_recipients_html_and_pdf_attachment(smtp, tmp_path):
    config, _, client = smtp
    pdf = tmp_path / "journal.pdf"
    payload = b"%PDF-1.4\nsynthetic-test-only\n%%EOF"
    pdf.write_bytes(payload)

    send(
        cc_emails=["admin@dimax.example"],
        body_html="<p>Test only</p>",
        attachment_path=str(pdf),
        attachment_name="DIMAX-journal.pdf",
    )

    client.send_message.assert_called_once()
    message = client.send_message.call_args.args[0]
    assert message["From"] == config.SMTP_FROM
    assert message["To"] == "factory@dimax.example"
    assert message["Cc"] == "admin@dimax.example"
    assert message["Subject"] == "Synthetic approval"
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "Test only"
    assert message.get_body(preferencelist=("html",)).get_content().strip() == "<p>Test only</p>"
    attachment, = message.iter_attachments()
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_filename() == "DIMAX-journal.pdf"
    assert attachment.get_payload(decode=True) == payload
