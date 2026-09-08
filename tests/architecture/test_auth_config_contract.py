from pathlib import Path

import pytest
from dotenv import dotenv_values

from app.core.config import Settings


@pytest.mark.parametrize("filename", [".env.example", ".env.production.example"])
def test_example_access_token_ttl_matches_runtime_default(filename: str) -> None:
    backend_root = Path(__file__).resolve().parents[2]
    example = dotenv_values(backend_root / filename, interpolate=False)

    assert Settings.model_fields["JWT_ACCESS_TTL_MIN"].default == 15
    assert example["JWT_ACCESS_TTL_MIN"] == "15"
