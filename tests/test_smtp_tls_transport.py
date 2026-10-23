"""Real STARTTLS on loopback only; no database, relay or external mail delivery."""
from __future__ import annotations

from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
import shutil
import socket
import socketserver
import ssl
import subprocess
import threading
from types import SimpleNamespace

import pytest

from app.integrations.email import smtp_sender


HOST = "smtp.dimax.example"


@pytest.fixture(scope="module")
def certificates(tmp_path_factory):
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.fail("OpenSSL CLI is required; run the isolated SMTP TLS acceptance container")
    root = tmp_path_factory.mktemp("smtp-tls-certificates")

    def run(*args):
        result = subprocess.run([openssl, *map(str, args)], capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr.decode(errors="replace")

    for name in ("trusted", "other"):
        run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
            "-subj", f"/CN=DIMAX test-only {name} CA",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout", root / f"{name}.key", "-out", root / f"{name}.pem")
    key = root / "server.key"
    csr = root / "server.csr"
    run("req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={HOST}",
        "-keyout", key, "-out", csr)
    for serial, (name, hostname) in enumerate(
        (("valid", HOST), ("wrong-host", "other.dimax.example"), ("expired", HOST)), start=1
    ):
        extensions = root / f"{name}.ext"
        extensions.write_text(
            "[server]\nbasicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            f"subjectAltName=DNS:{hostname}\n", encoding="ascii"
        )
        if name == "expired":
            (root / "index.txt").write_text("", encoding="ascii")
            (root / "serial").write_text("10\n", encoding="ascii")
            ca_config = root / "ca.cnf"
            ca_config.write_text(
                "[ca]\ndefault_ca=test_ca\n[test_ca]\n"
                f"database={root.as_posix()}/index.txt\nserial={root.as_posix()}/serial\n"
                f"new_certs_dir={root.as_posix()}\ncertificate={root.as_posix()}/trusted.pem\n"
                f"private_key={root.as_posix()}/trusted.key\n"
                "default_md=sha256\npolicy=subject_policy\n[subject_policy]\ncommonName=supplied\n",
                encoding="ascii",
            )
            run("ca", "-batch", "-notext", "-config", ca_config, "-in", csr,
                "-startdate", "20000101000000Z", "-enddate", "20010101000000Z",
                "-extfile", extensions, "-extensions", "server", "-out", root / f"{name}.pem")
        else:
            run("x509", "-req", "-in", csr, "-CA", root / "trusted.pem",
                "-CAkey", root / "trusted.key", "-set_serial", serial, "-days", "2",
                "-extfile", extensions, "-extensions", "server", "-out", root / f"{name}.pem")
    return root


class CaptureHandler(socketserver.BaseRequestHandler):
    """One-message SMTP fixture. AUTH is synthetic; messages stay in RAM."""

    def handle(self):
        server = self.server
        connection = self.request
        connection.settimeout(5)
        stream = connection.makefile("rb")
        encrypted = False

        def reply(value):
            connection.sendall(value)

        try:
            reply(b"220 test-only ESMTP\r\n")
            while line := stream.readline(65537):
                if len(line) > 65536:
                    raise AssertionError("SMTP command exceeded fixture limit")
                verb = line.split(maxsplit=1)[0].upper()
                server.commands.append((verb, encrypted))
                if verb in (b"EHLO", b"HELO"):
                    reply(b"250-test-only\r\n250-STARTTLS\r\n250 AUTH PLAIN\r\n")
                elif verb == b"STARTTLS":
                    reply(b"220 Ready for TLS\r\n")
                    stream.close()
                    try:
                        connection = server.tls_context.wrap_socket(connection, server_side=True)
                    except ssl.SSLError:
                        server.tls_rejected = True
                        return
                    stream = connection.makefile("rb")
                    encrypted = True
                elif verb == b"AUTH":
                    if not encrypted:
                        raise AssertionError("Credentials sent before TLS")
                    reply(b"235 Authentication successful\r\n")
                elif verb in (b"MAIL", b"RCPT"):
                    if not encrypted:
                        raise AssertionError("Envelope sent before TLS")
                    server.envelope.append(line.strip())
                    reply(b"250 OK\r\n")
                elif verb == b"DATA":
                    if not encrypted:
                        raise AssertionError("Message sent before TLS")
                    reply(b"354 End with dot\r\n")
                    data = bytearray()
                    while True:
                        part = stream.readline(65537)
                        if part == b".\r\n":
                            break
                        if not part or len(part) > 65536 or len(data) + len(part) > 1048576:
                            raise AssertionError("Incomplete or oversized test message")
                        data.extend(part[1:] if part.startswith(b"..") else part)
                    server.messages.append(bytes(data))
                    reply(b"250 Captured, never relayed\r\n")
                elif verb == b"QUIT":
                    reply(b"221 Bye\r\n")
                    return
                else:
                    raise AssertionError(f"Unexpected SMTP verb: {verb!r}")
        except Exception as error:
            server.errors.append(error)
        finally:
            stream.close()
            connection.close()


@contextmanager
def capture_server(certificates, certificate, *, port=0):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificates / f"{certificate}.pem", certificates / "server.key")
    with socketserver.TCPServer(("127.0.0.1", port), CaptureHandler) as server:
        server.tls_context = context
        server.commands = []
        server.envelope = []
        server.messages = []
        server.errors = []
        server.tls_rejected = False
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=10)
            assert not thread.is_alive(), "Test SMTP server did not stop"
            assert not server.errors, [type(error).__name__ for error in server.errors]


@pytest.fixture
def configure(monkeypatch, certificates, tmp_path):
    empty_ca_directory = tmp_path / "empty-ca-directory"
    empty_ca_directory.mkdir()
    monkeypatch.setenv("SSL_CERT_DIR", str(empty_ca_directory))
    original_resolver = socket.getaddrinfo

    # Resolve only the reserved test name to loopback; keep SNI/hostname verification real.
    def loopback_only(host, port, *args, **kwargs):
        assert host == HOST, "Unexpected network destination in SMTP test"
        return original_resolver("127.0.0.1", port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", loopback_only)

    def setup(server, trust="trusted"):
        monkeypatch.setenv("SSL_CERT_FILE", str(certificates / f"{trust}.pem"))
        monkeypatch.setattr(smtp_sender, "settings", SimpleNamespace(
            SMTP_HOST=HOST, SMTP_PORT=server.server_address[1], SMTP_TLS=True,
            SMTP_USER="synthetic-mailer", SMTP_PASSWORD="synthetic-test-password",
            SMTP_FROM="notifications@dimax.example",
        ))

    return setup


def send(**kwargs):
    smtp_sender.SmtpEmailSender().send(
        to_email="factory@dimax.example", cc_emails=["admin@dimax.example"],
        subject="DIMAX synthetic TLS acceptance", body_text="Test only", **kwargs,
    )


def test_trusted_starttls_delivers_one_message_and_pdf(certificates, configure, tmp_path):
    payload = b"%PDF-1.4\nsynthetic-transport-test-only\n%%EOF"
    pdf = tmp_path / "journal.pdf"
    pdf.write_bytes(payload)
    with capture_server(certificates, "valid") as server:
        configure(server)
        send(body_html="<p>Test only</p>", attachment_path=str(pdf), attachment_name="DIMAX-journal.pdf")

    assert not server.tls_rejected
    assert server.commands == [
        (b"EHLO", False), (b"STARTTLS", False), (b"EHLO", True), (b"AUTH", True),
        (b"MAIL", True), (b"RCPT", True), (b"RCPT", True), (b"DATA", True), (b"QUIT", True),
    ]
    assert server.envelope == [b"mail FROM:<notifications@dimax.example>",
                               b"rcpt TO:<factory@dimax.example>", b"rcpt TO:<admin@dimax.example>"]
    assert len(server.messages) == 1
    message = BytesParser(policy=policy.default).parsebytes(server.messages[0])
    assert message["Subject"] == "DIMAX synthetic TLS acceptance"
    assert message["To"] == "factory@dimax.example"
    assert message["Cc"] == "admin@dimax.example"
    assert message.get_body(preferencelist=("plain",)).get_content().strip() == "Test only"
    assert message.get_body(preferencelist=("html",)).get_content().strip() == "<p>Test only</p>"
    attachment, = message.iter_attachments()
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_filename() == "DIMAX-journal.pdf"
    assert attachment.get_payload(decode=True) == payload


@pytest.mark.parametrize("certificate,trust,reason", [
    ("valid", "other", "issuer certificate"),
    ("wrong-host", "trusted", "hostname mismatch"),
    ("expired", "trusted", "expired"),
], ids=["untrusted-ca", "wrong-host", "expired"])
def test_invalid_certificate_blocks_credentials_and_message(certificates, configure, certificate, trust, reason):
    with capture_server(certificates, certificate) as server:
        configure(server, trust)
        with pytest.raises(ssl.SSLCertVerificationError) as caught:
            send()

    assert reason in caught.value.verify_message.lower()
    assert server.commands == [(b"EHLO", False), (b"STARTTLS", False)]
    assert server.tls_rejected
    assert server.envelope == []
    assert server.messages == []
