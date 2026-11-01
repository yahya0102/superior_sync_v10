"""Conflict resolution, versions, and trash."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from .. import i18n
from ..dependencies import Principal, require_permission
from ..schemas import ResolveConflictRequest

router = APIRouter(prefix="/api", tags=["conflicts"])


def _app(request: Request):
    return request.app.state.superior


@router.get("/conflicts")
async def list_conflicts(request: Request, open: bool = Query(False),
                         principal: Principal = Depends(require_permission("read"))):
    cr = _app(request).engine.conflict_resolver
    return {"conflicts": cr.list_conflicts(open)}


@router.post("/conflicts/{cid}/resolve")
async def resolve(cid: str, payload: ResolveConflictRequest, request: Request,
                  principal: Principal = Depends(require_permission("write"))):
    app = _app(request)
    cr = app.engine.conflict_resolver
    row = cr.db.one("SELECT share FROM conflicts WHERE id=?", (cid,))
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=i18n.t("error.not_found"))
    share_root = app.config.shares().get(row["share"])
    if not share_root:   # [FIX] KeyError → 500 إذا أُزيلت المشاركة
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=i18n.t("error.not_found"))
    ok, err = cr.resolve_manual(cid, payload.action, share_root)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=err)
    path_row = cr.db.one("SELECT path FROM conflicts WHERE id=?", (cid,))
    app.engine.index_path(row["share"], path_row["path"])
    return {"success": True}


@router.get("/versions")
async def versions(request: Request, path: str | None = Query(None),
                   principal: Principal = Depends(require_permission("read"))):
    cr = _app(request).engine.conflict_resolver
    return {"versions": cr.get_file_versions(path)}


@router.post("/versions/{vid}/restore")
async def restore_version(vid: int, request: Request,
                          principal: Principal = Depends(require_permission("write"))):
    if not _app(request).engine.conflict_resolver.restore_version(vid):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=i18n.t("error.not_found"))
    return {"success": True}


@router.get("/trash")
async def trash(request: Request, principal: Principal = Depends(require_permission("read"))):
    cr = _app(request).engine.conflict_resolver
    return {"items": cr.list_trash(), "size": cr.get_stats()["trash_size"]}


@router.post("/trash/{tid}/restore")
async def restore_trash(tid: int, request: Request,
                        principal: Principal = Depends(require_permission("write"))):
    if not _app(request).engine.conflict_resolver.restore_from_trash(tid):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=i18n.t("error.not_found"))
    return {"success": True}


@router.post("/trash/empty")
async def empty_trash(
    request: Request,
    days: int | None = Query(
        None, ge=0, le=3650,
        description=(
            "Delete items older than N days.  Omit to honour "
            "config.trash_retention_days.  Pass 0 to force-purge everything."
        ),
    ),
    principal: Principal = Depends(require_permission("delete")),
):
    """Empty the trash, honouring the configured retention policy.

    By default, items newer than ``config.trash_retention_days`` are
    preserved — so an accidental click cannot destroy recently-deleted
    files.  Pass ``?days=0`` to override and permanently purge everything.
    """
    app = _app(request)
    if days is None:
        days = max(1, int(app.config.trash_retention_days))
    # 0 means "no cutoff" inside the resolver → purge all.
    removed = app.engine.conflict_resolver.empty_trash(days if days > 0 else None)
    app.audit(principal.name, "trash.empty", detail=f"days={days}")
    return {
        "success": True,
        "removed": removed,
        "retention_days": days,
    }