from __future__ import annotations

from pathlib import Path
import json

ROOT = Path.home() / ".dodaios"
POLICY = ROOT / "ja_policies" / "change_classification.json"


def load_policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8-sig"))


def classify_change(
    *,
    inside_companies: bool,
    structural: bool,
) -> str:
    if not inside_companies:
        return "core_global"

    if structural:
        return "companies_structural"

    return "company_specific"


def should_publish_update(category: str) -> bool:
    policy = load_policy()
    return bool(
        policy["categories"][category]["publish_update"]
    )


def distribution_scope(category: str) -> str:
    policy = load_policy()
    return str(
        policy["categories"][category]["distribution"]
    )
