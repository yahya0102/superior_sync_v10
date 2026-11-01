"""Notification endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..dependencies import Principal, require_permission

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _app(request: Request):
    return request.app.state.superior


@router.get("")
async def list_notifs(request: Request, unread: bool = Query(False),
                      principal: Principal = Depends(require_permission("read"))):
    notifier = _app(request).notifier
    return {"notifications": notifier.get_notifications(unread_only=unread), "unread": notifier.unread_count}


@router.post("/read")
async def read_all(request: Request, principal: Principal = Depends(require_permission("read"))):
    _app(request).notifier.mark_all_as_read()
    return {"success": True}


@router.delete("")
async def clear(request: Request, principal: Principal = Depends(require_permission("read"))):
    _app(request).notifier.clear_all()
    return {"success": True}