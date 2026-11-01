"""Config management, audit log, and webhooks."""
from __future__ import annotations

import hashlib
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from .. import i18n
from ..dependencies import Principal, require_permission
from ..schemas import ConfigPayload, WebhookCreate
from ..utils import is_safe_external_url

router = APIRouter(prefix="/api", tags=["admin"])


def _app(request: Request):
    return request.app.state.superior


@router.get("/config")
async def get_config(request: Request, principal: Principal = Depends(require_permission("read"))):
    return _app(request).config.public_dict()


@router.post("/config")
async def update_config(payload: ConfigPayload, request: Request,
                        principal: Principal = Depends(require_permission("configure"))):
    app = _app(request)
    patch = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    ok, err, restart = app.config.update(patch)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=err)
    app.engine.codec.invalidate_cache()
    app.audit(principal.name, "config.update", "keys")
    return {
        "success": True,
        "message": i18n.t("config.saved") + (" — " + i18n.t("config.restart_required") if restart else ""),
        "restart_required": restart,
    }


def _group_key_fingerprint(key: str) -> str:
    """Stable short fingerprint of a group key.

    SHA-256 truncated to 16 hex chars.  This is enough to let two devices
    confirm they share the same key without ever transmitting, logging, or
    caching the key itself.  Brute-forcing the underlying 32-byte URL-safe
    token from the fingerprint is computationally infeasible.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


@router.get("/config/group_key/fingerprint")
async def group_key_fingerprint(
    request: Request,
    principal: Principal = Depends(require_permission("manage_users")),
):
    """Return a short fingerprint of the current group key.

    The raw key is intentionally **never** returned via the API — even to
    admins.  To copy the key to another device, read it from
    ``<data-dir>/config.json`` on the machine itself, or call the rotate
    endpoint below to generate a fresh one.
    """
    app = _app(request)
    fp = _group_key_fingerprint(app.config.group_key or "")
    app.audit(principal.name, "group_key.fingerprint", "")
    return {"fingerprint": fp}


@router.post("/config/group_key/rotate")
async def rotate_group_key(
    request: Request,
    principal: Principal = Depends(require_permission("manage_users")),
):
    """Rotate the group key to a fresh 32-byte URL-safe token.

    The new key is stored encrypted on disk and is **not** echoed back in
    the response — the operator reads it locally from ``config.json`` (or
    calls the fingerprint endpoint to confirm rotation succeeded).
    """
    app = _app(request)
    new_key = secrets.token_urlsafe(32)
    ok, err, _ = app.config.update({"group_key": new_key})
    if not ok:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=err or i18n.t("error.invalid_input"),
        )
    app.engine.codec.invalidate_cache()
    app.audit(principal.name, "group_key.rotate", "")
    return {
        "success": True,
        "fingerprint": _group_key_fingerprint(new_key),
        "message": i18n.t("config.saved"),
    }


@router.get("/admin/audit")
async def audit_log(request: Request, limit: int = Query(100, ge=1, le=1000),
                    principal: Principal = Depends(require_permission("manage_users"))):
    rows = _app(request).engine.db.query(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    )
    return {"audit": rows}


@router.get("/webhooks")
async def list_webhooks(request: Request, principal: Principal = Depends(require_permission("configure"))):
    return {"webhooks": _app(request).engine.db.query(
        "SELECT id,url,events,enabled,created_at FROM webhooks ORDER BY created_at DESC")}


@router.post("/webhooks")
async def create_webhook(payload: WebhookCreate, request: Request,
                        principal: Principal = Depends(require_permission("configure"))):
    app = _app(request)
    ok, err = is_safe_external_url(payload.url)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=i18n.t("error.invalid_input") + f": {err}")
    wh_id = uuid.uuid4().hex[:12]
    secret_val = payload.secret or secrets.token_urlsafe(32)
    app.engine.db.execute(
        "INSERT INTO webhooks(id,url,events,secret,enabled,created_at) VALUES(?,?,?,?,1,?)",
        (wh_id, payload.url, payload.events, secret_val, time.time()),
    )
    return {"success": True, "id": wh_id, "secret": secret_val}


@router.delete("/webhooks/{wh_id}")
async def delete_webhook(wh_id: str, request: Request,
                        principal: Principal = Depends(require_permission("configure"))):
    _app(request).engine.db.execute("DELETE FROM webhooks WHERE id=?", (wh_id,))
    return {"success": True}