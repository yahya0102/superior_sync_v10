"""File browse / upload / download endpoints."""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import (APIRouter, Depends, File, HTTPException, Query, Request,
                     UploadFile, status)
from fastapi.responses import (FileResponse, Response, StreamingResponse)

from .. import i18n
from ..dependencies import Principal, require_permission
from ..schemas import FileEntry, FileListResponse, ShareInfo, ZipRequest
from ..utils import (FORBIDDEN_EXECUTABLE_EXT, MAX_HASH_SIZE_BYTES, PathError, file_hash,
                     is_ignored, safe_join, sanitize_relpath, unique_path)

router = APIRouter(prefix="/api/files", tags=["files"])

CHUNK = 1 << 20


def _app(request: Request):
    return request.app.state.superior


def _root(app, share: str) -> str:
    root = app.config.shares().get(share)
    if not root:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=i18n.t("error.not_found"))
    return root


def _resolve(app, share: str, rel: str) -> tuple[str, str]:
    root = _root(app, share)
    try:
        return root, (safe_join(root, rel) if rel else root)
    except PathError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=i18n.t("error.path_unsafe")) from exc


@router.get("", response_model=FileListResponse)
async def list_files(
    request: Request,
    share: str = Query("received"),
    folder: str = Query(""),
    principal: Principal = Depends(require_permission("read")),
):
    app = _app(request)
    root, base = _resolve(app, share, folder)
    if not os.path.isdir(base):
        return FileListResponse(files=[], share=share, folder=folder)

    entries: list[FileEntry] = []
    for item in os.scandir(base):
        if is_ignored(item.name, app.config.ignore_patterns) or \
                ".sync-tmp-" in item.name:
            continue
        try:
            st = item.stat()
        except OSError:
            continue
        is_dir = item.is_dir()
        entries.append(FileEntry(
            name=item.name,
            path=(folder + "/" if folder else "") + item.name,
            size=0 if is_dir else st.st_size,
            modified=st.st_mtime,
            type="folder" if is_dir else "file",
        ))
    entries.sort(key=lambda e: (e.type != "folder", e.name.lower()))
    return FileListResponse(files=entries, share=share, folder=folder)


@router.get("/shares", response_model=list[ShareInfo])
async def list_shares(
    request: Request,
    principal: Principal = Depends(require_permission("read")),
):
    app = _app(request)
    return [ShareInfo(id=k, path=v) for k, v in app.config.shares().items()]


@router.get("/info")
async def file_info(
    request: Request,
    share: str = Query("received"),
    path: str = Query(...),
    principal: Principal = Depends(require_permission("read")),
):
    app = _app(request)
    root, full = _resolve(app, share, path)
    if not os.path.exists(full):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=i18n.t("error.not_found"))
    st = os.stat(full)
    info = {
        "name": os.path.basename(full), "path": path, "share": share,
        "size": st.st_size, "modified": st.st_mtime, "created": st.st_ctime,
        "type": "folder" if os.path.isdir(full) else "file",
    }
    # [FIX-MED-4] file_hash قد يستغرق ثوانٍ للملفات الكبيرة. تشغيله
    # في thread منفصل يمنع حجب الـ event loop الذي يخدم بقية الطلبات.
    if os.path.isfile(full) and st.st_size <= MAX_HASH_SIZE_BYTES:
        info["hash"] = await asyncio.to_thread(file_hash, full)
    return info


@router.delete("")
async def delete_file(
    request: Request,
    share: str = Query("received"),
    path: str = Query(...),
    permanent: bool = Query(False),
    principal: Principal = Depends(require_permission("delete")),
):
    app = _app(request)
    root, full = _resolve(app, share, path)
    if not path or not os.path.exists(full):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=i18n.t("error.not_found"))

    if permanent:
        if principal.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail=i18n.t("auth.forbidden"))
        shutil.rmtree(full) if os.path.isdir(full) else os.remove(full)
    elif not app.engine.conflict_resolver.move_to_trash(full, "user_delete"):
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=i18n.t("error.internal"))

    app.engine.index_path(share, path)
    app.engine._schedule_notify(share)
    app.fire_webhook("file_deleted", {"share": share, "path": path})
    return {"success": True, "message": i18n.t("file.deleted")}


@router.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    share: str = Query("received"),
    folder: str = Query(""),
    overwrite: bool = Query(False),
    principal: Principal = Depends(require_permission("write")),
):
    app = _app(request)
    root = _root(app, share)
    name = file.filename or "file"
    # [FIX-MED-3] استخدام الثابت المشترك.
    if share == "received" and app.config.block_executable_extensions:
        ext = os.path.splitext(name)[1].lower()
        if ext in FORBIDDEN_EXECUTABLE_EXT:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                detail=i18n.t("error.extension_blocked",
                                              ext=ext))
    try:
        rel = sanitize_relpath((folder + "/" if folder else "") + name)
        dest = safe_join(root, rel)
    except PathError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=i18n.t("error.path_unsafe")) from exc

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = os.path.join(os.path.dirname(dest),
                       f".sync-tmp-{uuid.uuid4().hex[:10]}")
    try:
        with open(tmp, "wb") as fh:
            while chunk := await file.read(CHUNK):
                fh.write(chunk)
            fh.flush()
            os.fsync(fh.fileno())
        if os.path.exists(dest) and not overwrite:
            dest = unique_path(dest)
        elif os.path.isfile(dest):
            # [FIX] الاستبدال كان يُتلف المحتوى القديم بلا أثر؛ نحفظ نسخة أولًا.
            app.engine.conflict_resolver.create_version(dest, "pre_overwrite")
        final_name = os.path.basename(dest)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    loc = app.engine.locate(dest)
    if loc:
        app.engine.index_path(*loc)
        app.engine._schedule_notify(loc[0])
    app.fire_webhook("file_uploaded", {
        "share": share,
        "path": os.path.relpath(dest, root).replace(os.sep, "/"),
    })
    return {"success": True,
            "message": i18n.t("file.uploaded", name=final_name),
            "name": final_name}


@router.get("/download")
async def download(
    request: Request,
    share: str = Query("received"),
    path: str = Query(...),
    principal: Principal = Depends(require_permission("read")),
):
    app = _app(request)
    root, full = _resolve(app, share, path)
    if not os.path.isfile(full):
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=i18n.t("error.not_found"))
    return FileResponse(full, filename=os.path.basename(full))


@router.post("/download-zip")
async def download_zip(
    payload: ZipRequest,
    request: Request,
    principal: Principal = Depends(require_permission("read")),
):
    app = _app(request)
    root = _root(app, payload.share)
    tmpdir = Path(app.config.data_dir) / "zip_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    fd, tmppath = tempfile.mkstemp(prefix="ss-zip-", suffix=".zip",
                                   dir=str(tmpdir))
    os.close(fd)
    patterns = app.config.ignore_patterns

    def _build():
        # [FIX] كان الضغط يجري داخل async def فيجمّد حلقة الأحداث، ويتجاهل
        # المجلدات (اختيار مجلد يعطي ملف zip فارغًا)، ويترك الملف المؤقت عند الفشل.
        with zipfile.ZipFile(tmppath, "w", zipfile.ZIP_DEFLATED,
                             allowZip64=True) as zf:
            for rel in payload.paths:
                try:
                    full = safe_join(root, rel)
                except PathError:
                    continue
                if os.path.isfile(full):
                    zf.write(full, arcname=rel)
                elif os.path.isdir(full):
                    for dirpath, dirnames, filenames in os.walk(full):
                        dirnames[:] = [d for d in dirnames
                                       if not is_ignored(d, patterns)]
                        for fn in filenames:
                            if is_ignored(fn, patterns):
                                continue
                            fp = os.path.join(dirpath, fn)
                            if os.path.islink(fp):
                                continue
                            arc = os.path.relpath(fp, root).replace(os.sep, "/")
                            zf.write(fp, arcname=arc)

    try:
        await asyncio.to_thread(_build)
    except Exception:
        with __import__("contextlib").suppress(OSError):
            os.remove(tmppath)
        raise

    async def _stream():
        try:
            with open(tmppath, "rb") as fh:
                while chunk := fh.read(CHUNK):
                    yield chunk
        finally:
            with __import__("contextlib").suppress(OSError):
                os.remove(tmppath)

    return StreamingResponse(
        _stream(),
        media_type="application/zip",
        headers={"Content-Disposition":
                 'attachment; filename="sync_files.zip"'},
    )