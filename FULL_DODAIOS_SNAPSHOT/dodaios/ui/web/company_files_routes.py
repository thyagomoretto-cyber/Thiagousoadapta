"""Persistent file vault scoped to one JARVIS company."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from .companies_routes import _LOCK as _COMPANIES_LOCK
from .companies_routes import _read_state

router = APIRouter(prefix="/api/companies", tags=["companies"])
_MAX_FILE_BYTES = 50 * 1024 * 1024
_MAX_FILES_PER_UPLOAD = 20


def _root(company_id: str) -> Path:
    from dodaios.core.paths import user_data_dir

    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", company_id).strip(".-")
    if not safe or safe != company_id:
        raise HTTPException(status_code=422, detail="Invalid company id")
    return user_data_dir() / "data" / "companies" / safe / "files"


def _require_company(company_id: str) -> None:
    with _COMPANIES_LOCK:
        if not any(company.id == company_id for company in _read_state().companies):
            raise HTTPException(status_code=404, detail="Company not found")


def _safe_name(raw: str | None) -> str:
    name = Path(raw or "file").name.strip().replace("\x00", "")
    if not name or name in {".", ".."}:
        name = "file"
    return name[:240]


def _unique_path(root: Path, name: str) -> Path:
    target = root / name
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    for index in range(2, 10_000):
        candidate = root / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise HTTPException(status_code=409, detail="Could not allocate a unique filename")


def _entry(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "size": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


@router.get("/{company_id}/files")
def list_company_files(company_id: str) -> dict[str, Any]:
    _require_company(company_id)
    root = _root(company_id)
    if not root.exists():
        return {"files": []}
    files = sorted((path for path in root.iterdir() if path.is_file()), key=lambda item: item.stat().st_mtime_ns, reverse=True)
    return {"files": [_entry(path) for path in files]}


@router.post("/{company_id}/files", status_code=201)
async def upload_company_files(
    company_id: str,
    files: list[UploadFile] = File(...),  # noqa: B008
) -> dict[str, Any]:
    _require_company(company_id)
    if len(files) > _MAX_FILES_PER_UPLOAD:
        raise HTTPException(status_code=413, detail=f"Upload at most {_MAX_FILES_PER_UPLOAD} files at once")
    root = _root(company_id)
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        for upload in files:
            name = _safe_name(upload.filename)
            target = _unique_path(root, name)
            fd, tmp_name = tempfile.mkstemp(prefix="upload-", suffix=".tmp", dir=root)
            total = 0
            try:
                with os.fdopen(fd, "wb") as handle:
                    while True:
                        chunk = await upload.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > _MAX_FILE_BYTES:
                            raise HTTPException(status_code=413, detail=f"{name} exceeds 50 MB")
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, target)
                written.append(target)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
    except Exception:
        for path in written:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return {"files": [_entry(path) for path in written]}


@router.delete("/{company_id}/files/{filename}")
def delete_company_file(company_id: str, filename: str) -> dict[str, Any]:
    _require_company(company_id)
    name = _safe_name(filename)
    if name != filename:
        raise HTTPException(status_code=422, detail="Invalid filename")
    target = _root(company_id) / name
    removed = target.exists() and target.is_file()
    if removed:
        target.unlink()
    return {"ok": True, "removed": removed}
