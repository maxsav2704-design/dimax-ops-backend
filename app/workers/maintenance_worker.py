from __future__ import annotations

import time

from app.modules.files.infrastructure.repositories import FileTokenRepository
from app.shared.infrastructure.db.session import SessionLocal


def cleanup_file_tokens() -> int:
    session = SessionLocal()
    try:
        repo = FileTokenRepository(session)
        deleted = repo.delete_expired_and_used()
        session.commit()
        return deleted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    while True:
        deleted = cleanup_file_tokens()
        if deleted:
            print(f"🧹 file tokens cleaned: {deleted}")
        time.sleep(600)


if __name__ == "__main__":
    main()
