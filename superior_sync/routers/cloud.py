"""Cloud provider endpoints."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from .. import i18n
from ..dependencies import Principal, require_permission
from ..integrations import CloudIntegration
from ..schemas import (
    CloudBackupRequest,
    CloudConnectRequest,
    CloudDisconnectRequest,
    CloudUploadRequest,
)
from ..utils import PathError, safe_join

router = APIRouter(prefix="/api/cloud", tags=["cloud"])


def _app(request: Request):
    return request.app.state.superior


@router.get("")
async def services(request: Request, principal: Principal = Depends(require_permission("share"))):
    app = _app(request)
    return {
        "supported": list(CloudIntegration.PROVIDERS),
        "connected": app.cloud.get_connected_services(),
        "jobs": app.cloud.cloud_config.get("backup_jobs", []),
    }


@router.post("/connect")
async def connect(payload: CloudConnectRequest, request: Request,
                  principal: Principal = Depends(require_permission("configure"))):
    app = _app(request)
    result = await asyncio.to_thread(
        app.cloud.connect_service, payload.service, payload.credentials
    )
    if not result["success"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result["error"])
    app.audit(principal.name, "cloud.connect", payload.service)
    return result


@router.post("/disconnect")
async def disconnect(payload: CloudDisconnectRequest, request: Request,
                     principal: Principal = Depends(require_permission("configure"))):
    app = _app(request)
    app.audit(principal.name, "cloud.disconnect", payload.service)
    return await asyncio.to_thread(app.cloud.disconnect_service, payload.service)


@router.post("/upload")
async def upload(payload: CloudUploadRequest, request: Request,
                 principal: Principal = Depends(require_permission("share"))):
    app = _app(request)
    root = app.config.shares().get(payload.share)
    if not root:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=i18n.t("error.not_found"))
    try:
        full = safe_join(root, payload.path)
    except PathError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=i18n.t("error.path_unsafe")) from exc
    result = await asyncio.to_thread(
        app.cloud.upload_to_cloud, payload.service, full, payload.cloud_path
    )
    if not result["success"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return result


@router.get("/list")
async def list_cloud(
    request: Request,
    service: str = Query(...),
    path: str = Query("/"),
    principal: Principal = Depends(require_permission("share")),
):
    result = await asyncio.to_thread(
        _app(request).cloud.list_cloud_files, service, path
    )
    if not result["success"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return result


@router.post("/backup")
async def backup(payload: CloudBackupRequest, request: Request,
                 principal: Principal = Depends(require_permission("configure"))):
    app = _app(request)
    root = app.config.shares().get(payload.share)
    if not root:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=i18n.t("error.not_found"))
    try:
        local = safe_join(root, payload.path) if payload.path else root
    except PathError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=i18n.t("error.path_unsafe")) from exc
    result = await asyncio.to_thread(
        app.cloud.schedule_backup,
        payload.service,
        local,
        payload.cloud_path,
        payload.schedule,
    )
    if not result["success"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return result