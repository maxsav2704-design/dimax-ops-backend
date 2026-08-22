from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _top_level_imports(relative_path: str) -> set[str]:
    source = (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    return imports


def test_optional_network_clients_are_not_loaded_during_api_import() -> None:
    cases = {
        "app/integrations/storage/minio_client.py": {"minio"},
        "app/integrations/storage/storage_service.py": {"minio.error"},
        "app/integrations/whatsapp/twilio_sender.py": {"requests"},
        "app/modules/sync/application/health_service.py": {"httpx"},
        "app/modules/companies/application/alerts_service.py": {"httpx"},
    }

    for relative_path, forbidden in cases.items():
        assert _top_level_imports(relative_path).isdisjoint(forbidden)


def test_pdf_renderer_is_loaded_only_when_a_journal_pdf_is_generated() -> None:
    imports = _top_level_imports("app/modules/journal/application/use_cases.py")

    assert "app.integrations.pdf.generator" not in imports
