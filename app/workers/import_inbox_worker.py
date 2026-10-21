"""Import inbox worker: feeds factory documents into the inbox without anyone clicking.

Two sources, both optional and switched on by settings:
- a watched folder (IMPORT_INBOX_DIR): files in <dir>/<company_id>/ (or in <dir> itself for
  IMPORT_INBOX_COMPANY_ID) are ingested and moved to processed/ or failed/;
- a mailbox (IMPORT_INBOX_IMAP_*): unseen messages from allowed senders are read, their
  supported attachments ingested for IMPORT_INBOX_IMAP_COMPANY_ID, and the message is marked seen.
The inbox service then matches the project, analyzes and imports clean files by itself.
"""
from __future__ import annotations

import email
import imaplib
import time
import uuid
from email.message import Message
from pathlib import Path

from app.core.config import settings
from app.modules.projects.application.import_inbox_service import SUPPORTED_EXTENSIONS, ImportInboxService
from app.shared.infrastructure.db.uow_sqlalchemy import SqlAlchemyUnitOfWork


def log(message: str) -> None:
    print(message, flush=True)  # container logs must not wait for the buffer


def _company_from(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value).strip()) if value and str(value).strip() else None
    except ValueError:
        return None


def _supported(name: str) -> bool:
    return "." in name and name.rsplit(".", 1)[-1].lower() in SUPPORTED_EXTENSIONS


def ingest_bytes(company_id: uuid.UUID, filename: str, content: bytes, *, source: str, source_ref: str) -> str:
    uow = SqlAlchemyUnitOfWork()
    with uow:
        item, created = ImportInboxService.ingest(uow, company_id=company_id, actor_user_id=None, filename=filename, content=content,
                                                  source=source, source_ref=source_ref)
        uow.commit()
        return f"{item.status}{'' if created else ' (duplicate)'}"


# ---- watched folder --------------------------------------------------------------------------------

def ingest_folder(root: Path | None = None, *, default_company: uuid.UUID | None = None) -> int:
    """Ingest every supported file under the folder once; returns the number of files handled."""
    root = root or (Path(settings.IMPORT_INBOX_DIR) if settings.IMPORT_INBOX_DIR.strip() else None)
    if root is None or not root.is_dir():
        return 0
    default_company = default_company or _company_from(settings.IMPORT_INBOX_COMPANY_ID)
    handled = 0
    targets: list[tuple[uuid.UUID, Path]] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and entry.name not in {"processed", "failed"}:
            company = _company_from(entry.name)
            if company is not None:
                targets.extend((company, path) for path in sorted(entry.iterdir()) if path.is_file() and _supported(path.name))
        elif entry.is_file() and _supported(entry.name) and default_company is not None:
            targets.append((default_company, entry))
    for company, path in targets:
        try:
            outcome = ingest_bytes(company, path.name, path.read_bytes(), source="FOLDER", source_ref=str(path))
            destination = path.parent / "processed"
            log(f"import inbox: {path.name} -> {outcome}")
        except Exception as exc:  # one bad file must not stop the others
            destination = path.parent / "failed"
            log(f"import inbox: {path.name} failed: {type(exc).__name__}")
        destination.mkdir(exist_ok=True)
        target = destination / path.name
        if target.exists():
            target = destination / f"{path.stem}-{int(time.time())}{path.suffix}"
        path.replace(target)
        handled += 1
    return handled


# ---- mailbox -----------------------------------------------------------------------------------------

class ImapFetcher:
    """Minimal IMAP reader: unseen messages, their attachments, mark as seen. Credentials stay in settings."""

    def __init__(self):
        self.client = None

    def __enter__(self):
        self.client = imaplib.IMAP4_SSL(settings.IMPORT_INBOX_IMAP_HOST, settings.IMPORT_INBOX_IMAP_PORT)
        self.client.login(settings.IMPORT_INBOX_IMAP_USER, settings.IMPORT_INBOX_IMAP_PASSWORD.get_secret_value())
        self.client.select(settings.IMPORT_INBOX_IMAP_FOLDER or "INBOX")
        return self

    def __exit__(self, *exc):
        try:
            self.client.logout()
        except Exception:
            pass

    def unseen(self) -> list[tuple[bytes, Message]]:
        status, data = self.client.search(None, "UNSEEN")
        if status != "OK" or not data or not data[0]:
            return []
        messages = []
        for uid in data[0].split()[:50]:
            status, parts = self.client.fetch(uid, "(RFC822)")
            if status == "OK" and parts and isinstance(parts[0], tuple):
                messages.append((uid, email.message_from_bytes(parts[0][1])))
        return messages

    def mark_seen(self, uid: bytes) -> None:
        self.client.store(uid, "+FLAGS", "\\Seen")


def attachments(message: Message) -> list[tuple[str, bytes]]:
    found = []
    for part in message.walk():
        name = part.get_filename()
        if name and _supported(name):
            payload = part.get_payload(decode=True)
            if payload:
                found.append((name, payload))
    return found


def ingest_mailbox(fetcher=None, *, company_id: uuid.UUID | None = None) -> int:
    """Read unseen messages from allowed senders and ingest their attachments; returns the number of attachments."""
    company_id = company_id or _company_from(settings.IMPORT_INBOX_IMAP_COMPANY_ID)
    if company_id is None:
        return 0
    allowed = {s.strip().lower() for s in settings.IMPORT_INBOX_ALLOWED_SENDERS.split(",") if s.strip()}
    handled = 0
    own = fetcher is None
    fetcher = fetcher or ImapFetcher()
    if own:
        fetcher.__enter__()
    try:
        for uid, message in fetcher.unseen():
            sender = (email.utils.parseaddr(message.get("From", ""))[1] or "").lower()
            if allowed and sender not in allowed:
                fetcher.mark_seen(uid)
                log(f"import inbox: message from {sender or 'unknown'} ignored (not an allowed sender)")
                continue
            message_id = (message.get("Message-ID") or f"uid:{uid.decode() if isinstance(uid, bytes) else uid}").strip()
            for name, content in attachments(message):
                try:
                    outcome = ingest_bytes(company_id, name, content, source="EMAIL", source_ref=message_id)
                    log(f"import inbox: {name} from {sender} -> {outcome}")
                except Exception as exc:
                    log(f"import inbox: {name} from {sender} failed: {type(exc).__name__}")
                handled += 1
            fetcher.mark_seen(uid)
    finally:
        if own:
            fetcher.__exit__(None, None, None)
    return handled


def run_once() -> int:
    handled = ingest_folder()
    if settings.IMPORT_INBOX_IMAP_HOST.strip() and settings.IMPORT_INBOX_IMAP_USER.strip():
        try:
            handled += ingest_mailbox()
        except Exception as exc:
            log(f"import inbox: mailbox check failed: {type(exc).__name__}")
    return handled


def main() -> None:
    log("DIMAX import inbox worker started"
          + (f" (folder {settings.IMPORT_INBOX_DIR})" if settings.IMPORT_INBOX_DIR.strip() else " (no folder configured)")
          + (" (mailbox configured)" if settings.IMPORT_INBOX_IMAP_HOST.strip() else " (no mailbox configured)"))
    while True:
        try:
            run_once()
        except Exception as exc:
            log(f"import inbox worker loop error: {type(exc).__name__}")
        time.sleep(settings.IMPORT_INBOX_POLL_SEC)


if __name__ == "__main__":
    main()
