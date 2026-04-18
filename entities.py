import json
from pathlib import Path

ENTITIES_DIR = Path(__file__).parent / "entities"
APP_CONTEXT_PATH = Path(__file__).parent / "app_context.json"

_APP_CONTEXT_DEFAULTS = {
    "general_context": "",
    "default_policies": "",
    "default_standards": "",
}


def load_app_context() -> dict:
    if APP_CONTEXT_PATH.exists():
        return json.loads(APP_CONTEXT_PATH.read_text(encoding="utf-8"))
    return dict(_APP_CONTEXT_DEFAULTS)


def save_app_context(data: dict) -> None:
    APP_CONTEXT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def app_context_block() -> str:
    a = load_app_context()
    parts = ["APPLICATION CONTEXT"]
    if a.get("general_context"):
        parts.append(f"General Context:\n{a['general_context']}")
    if a.get("default_policies"):
        parts.append(f"Default Accounting Policies:\n{a['default_policies']}")
    if a.get("default_standards"):
        parts.append(f"Default Accounting Standards:\n{a['default_standards']}")
    return "\n\n".join(parts) if len(parts) > 1 else ""


def _ensure_dir():
    ENTITIES_DIR.mkdir(exist_ok=True)


def list_entities() -> list[str]:
    _ensure_dir()
    return sorted(p.stem for p in ENTITIES_DIR.glob("*.json"))


def load_entity(name: str) -> dict:
    return json.loads((ENTITIES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def save_entity(data: dict) -> None:
    _ensure_dir()
    (ENTITIES_DIR / f"{data['name']}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def delete_entity(name: str) -> None:
    path = ENTITIES_DIR / f"{name}.json"
    if path.exists():
        path.unlink()


def entity_context_block(name: str) -> str:
    e = load_entity(name)
    parts = [f"ENTITY CONTEXT: {e['name']}"]
    if e.get("business_context"):
        parts.append(f"Business Context:\n{e['business_context']}")
    if e.get("accounting_policies"):
        parts.append(f"Accounting Policy Choices:\n{e['accounting_policies']}")
    if e.get("accounting_standards"):
        parts.append(f"Accounting Standards:\n{e['accounting_standards']}")
    return "\n\n".join(parts)
