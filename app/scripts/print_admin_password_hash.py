"""Print bcrypt hash for admin password (for raw SQL seed).
Usage: docker compose exec api python -m app.scripts.print_admin_password_hash
"""
from __future__ import annotations

from app.core.security.password import hash_password

if __name__ == "__main__":
    print(hash_password("Admin12345!"))
