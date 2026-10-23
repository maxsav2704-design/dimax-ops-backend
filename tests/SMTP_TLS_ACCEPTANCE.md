# Isolated SMTP STARTTLS acceptance

These tests exercise `SmtpEmailSender`, Python smtplib and OpenSSL over an actual
TCP/TLS connection. They do not use a database, application startup, a relay,
external DNS or a real mailbox. They complement `test_smtp_sender.py` unit tests.

The test-only SMTP fixture binds to an ephemeral loopback port. The reserved
`smtp.dimax.example` name resolves only to that loopback listener inside the test
process; SNI and certificate/hostname validation remain real. Certificates and
private keys are generated with OpenSSL in pytest temporary storage. Trust is
limited to the test process via SSL_CERT_FILE/SSL_CERT_DIR; no system CA is installed.
Only synthetic credentials, recipients and a byte-preservation PDF fixture are used.
This is not PDF rendering validation or proof of external delivery.

## Run from the backend directory (PowerShell)

Use an already cached, reviewed backend image ID containing Python, pytest and
the OpenSSL CLI. Do not use a moving tag or start the normal entrypoint. Set
`$Image` to that image ID (`sha256:...`), then:

```powershell
$Backend = (Resolve-Path -LiteralPath '.').Path
docker run --rm --pull never --network none --read-only `
  --memory 256m --pids-limit 128 --cap-drop ALL `
  --security-opt no-new-privileges:true `
  --tmpfs /tmp:rw,noexec,nosuid,size=32m --workdir /tmp `
  --env PYTHONPATH=/app --env APP_ENV=test `
  --mount "type=bind,source=$Backend\app,target=/app/app,readonly" `
  --mount "type=bind,source=$Backend\tests\test_smtp_sender.py,target=/tests/test_smtp_sender.py,readonly" `
  --mount "type=bind,source=$Backend\tests\test_smtp_tls_transport.py,target=/tests/test_smtp_tls_transport.py,readonly" `
  --entrypoint python $Image -B -m pytest --noconftest -p no:cacheprovider -q /tests
```

No published ports, Docker socket, working volumes or .env files are mounted.
`--network none` permits loopback inside the container but no external delivery.
`--noconftest` excludes the repository's database-dependent test configuration.
Both application source and tests are mounted read-only; generated keys and PDFs
live only in the container's tmpfs and disappear when the container is removed.

Expected: 14 passing cases (10 unit cases plus 4 real transport cases).
Valid TLS sends exactly one captured message with its recipients and PDF intact.
Unknown CA, wrong hostname and expired certificates fail before AUTH, MAIL or DATA.
No test silently skips when OpenSSL is missing; use the reviewed runtime image.

Public HTTPS, external SMTP delivery, sender-domain authentication and the complete
factory confirmation workflow remain separate staging checks after provisioning.

## Local acceptance evidence (2026-10-23)

- Cached Python 3.12 runtime image:
  `sha256:f5af3ba59394a1d77dd98f74b7a57c96018d96be616e8534fcdbeaa67e335b74`.
- Both test modules: **14 passed**, 4.44 seconds of pytest runtime.
- Sensitivity check: replacing the protected STARTTLS call with the former
  `starttls()` only in process memory caused the real wrong-host test to fail
  with `DID NOT RAISE SSLCertVerificationError`, as required. Source mounts
  stayed read-only; this intentionally failing probe is not a product regression.
- Working services, application settings, database and system trust stores were
  not changed. One-off containers used `--rm`; their tmpfs held all generated keys.
