"""Read independent server readiness and mount lightweight JARVIS business routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .companies_routes import router as companies_router
from .company_files_routes import router as company_files_router

# Keep this router at the API root so lightweight feature routers can be mounted
# without touching the very large central server module. Existing agent-server
# URLs stay exactly the same because their full paths are declared below.
router = APIRouter(tags=["agent-server"])
router.include_router(companies_router)
router.include_router(company_files_router)


@router.get("/api/agent-server/status", operation_id="agent_server_status")
def status(request: Request) -> dict[str, Any]:
    """Read agent server ownership and startup state without calling a model."""
    state = request.app.state
    return {
        "independent": bool(getattr(state, "agent_server_mode", False)),
        "ready": bool(getattr(state, "agent_server_ready", False)),
        "error": getattr(state, "agent_server_error", None),
    }


@router.post(
    "/api/agent-server/stop", operation_id="agent_server_stop",
    openapi_extra={"x-jarvis-dangerous": True},
)
def stop(request: Request) -> dict[str, bool]:
    """Explicitly stop the independent server and its agents."""
    state = request.app.state
    callback = getattr(state, "agent_server_stop", None)
    if not getattr(state, "agent_server_mode", False) or not callable(callback):
        raise HTTPException(409, "This backend is not an independent agent server.")
    callback()
    return {"stopping": True}
