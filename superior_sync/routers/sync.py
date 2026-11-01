"""Sync engine control and status endpoints."""
from __future__ import annotations

import os

from fastapi import (APIRouter, Depends, HTTPException, Query, Request,
                     status)
from pydantic import BaseModel, Field, field_validator

from .. import i18n
from ..dependencies import Principal, require_permission

router = APIRouter(prefix="/api/sync", tags=["sync"])


def _app(request: Request):
    return request.app.state.superior


class FolderPayload(BaseModel):
    """[FIX-MED-9] نتحقّق من المسار قبل تمريره إلى المحرك.

    قبل الإصلاح كان ``folder_path: str`` يقبل أي شيء (حتى مسارات فارغة
    أو مسارات غير مطلقة)، وكان الفشل يظهر داخل المحرك برسالة أقل وضوحاً.
    """
    folder_path: str = Field(..., min_length=1, max_length=4096)

    @field_validator("folder_path")
    @classmethod
    def _normalise(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("folder_path cannot be empty")
        if os.name == "nt" and (
            value == "~" or value.startswith("~/") or value.startswith("~\\")
        ):
            home = os.path.expanduser("~")
            if home == "~":
                home = os.environ.get("USERPROFILE", "")
            if home:
                suffix = value[1:].lstrip("/\\")
                value = os.path.join(home, suffix) if suffix else home
        else:
            value = os.path.expanduser(value)
        if not os.path.isabs(value):
            raise ValueError("folder_path must be an absolute path")
        # نطبّع الفواصل ونمنع ``..`` في الوسط.
        normalised = os.path.normpath(value)
        parts = [p for p in normalised.replace("\\", "/").split("/") if p]
        if ".." in parts:
            raise ValueError("folder_path must not contain '..'")
        return normalised

    model_config = {"extra": "forbid", "str_strip_whitespace": True}


@router.get("/status")
async def status_(
    request: Request,
    principal: Principal = Depends(require_permission("read")),
):
    engine = _app(request).engine
    return {"status": "running" if engine.running else "stopped",
            "stats": engine.get_stats()}


@router.post("/start")
async def start(
    request: Request,
    principal: Principal = Depends(require_permission("configure")),
):
    _app(request).engine.start()
    return {"success": True, "message": i18n.t("sync.started")}


@router.post("/stop")
async def stop(
    request: Request,
    principal: Principal = Depends(require_permission("configure")),
):
    _app(request).engine.stop()
    return {"success": True, "message": i18n.t("sync.stopped")}


@router.post("/now")
async def sync_now(
    request: Request,
    principal: Principal = Depends(require_permission("write")),
):
    engine = _app(request).engine
    if not engine.running:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=i18n.t("error.invalid_input"))
    engine.sync_now()
    return {"success": True}


@router.get("/folders")
async def folders(
    request: Request,
    principal: Principal = Depends(require_permission("read")),
):
    return {"folders": list(_app(request).config.sync_folders)}


@router.post("/folder")
async def add_folder(
    payload: FolderPayload,
    request: Request,
    principal: Principal = Depends(require_permission("configure")),
):
    ok, err = _app(request).engine.add_sync_folder(payload.folder_path)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=err)
    return {"success": True, "message": i18n.t("sync.folder_added")}


@router.delete("/folder")
async def remove_folder(
    request: Request,
    path: str = Query(..., min_length=1, max_length=4096),
    principal: Principal = Depends(require_permission("configure")),
):
    if not _app(request).engine.remove_sync_folder(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=i18n.t("error.not_found"))
    return {"success": True, "message": i18n.t("sync.folder_removed")}