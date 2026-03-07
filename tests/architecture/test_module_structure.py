from __future__ import annotations

from pathlib import Path


STANDARD_MODULE_LAYERS = {
    "api",
    "application",
    "domain",
    "infrastructure",
}

# Explicit exceptions for technical/infrastructure-first modules.
MODULE_LAYER_ALLOWLIST = {
    "audit": {"application", "infrastructure"},
    "files": {"api", "application", "infrastructure"},
    "rates": {"infrastructure"},
}


def _modules_root() -> Path:
    return Path(__file__).resolve().parents[2] / "app" / "modules"


def _module_layers(module_path: Path) -> set[str]:
    return {
        item.name
        for item in module_path.iterdir()
        if item.is_dir() and not item.name.startswith("__")
    }


def test_module_structure_contract() -> None:
    root = _modules_root()
    errors: list[str] = []

    for module_path in sorted(
        p for p in root.iterdir() if p.is_dir() and not p.name.startswith("__")
    ):
        module_name = module_path.name
        actual_layers = _module_layers(module_path)
        expected_layers = MODULE_LAYER_ALLOWLIST.get(
            module_name, STANDARD_MODULE_LAYERS
        )

        if actual_layers != expected_layers:
            errors.append(
                f"{module_name}: expected {sorted(expected_layers)}, got {sorted(actual_layers)}"
            )

    assert not errors, "Module structure contract failed:\n" + "\n".join(errors)
