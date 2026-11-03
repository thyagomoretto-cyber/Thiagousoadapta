"""Restringe acoes de manutencao ao administrador do JA."""
from __future__ import annotations

from fastapi import HTTPException

from dodaios.core.user_rules import (
    active_profile_id,
    active_profile_role,
    administrator_profile_id,
)


def is_update_administrator() -> bool:
    return (
        active_profile_id() == administrator_profile_id()
        or active_profile_role() == "administrator"
    )


def require_update_administrator() -> None:
    if not is_update_administrator():
        raise HTTPException(
            status_code=403,
            detail="Somente o administrador pode executar esta acao.",
        )
