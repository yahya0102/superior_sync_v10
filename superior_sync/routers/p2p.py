"""P2P peer-to-peer protocol endpoints (HMAC-signed, no session cookie)."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from .. import APP_VERSION, i18n
from ..network import sign_request
from ..utils import (FORBIDDEN_EXECUTABLE_EXT, PathError, safe_eq,
                     sanitize_relpath, unique_path)

router = APIRouter(prefix="/p2p", tags=["p2p"])

RECV_CHUNK = 1 << 20
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def _app(request: Request):
    return request.app.state.superior


async def _verify(request: Request, target: str,
                  body_sha_expected: str | None = None):
    """[FIX-CRIT-1] التحقّق من توقيع الطلب.

    الكود الميت السابق::

        if not app.engine.p2p_protocol.running:
            pass

    كان بلا أي تأثير. الحماية الفعلية تأتي من التحقّق من HMAC، لذا
    أُزيل الفرع بالكامل بدل تركه موهِماً بأنه يفحص شيئاً.
    """
    app = _app(request)
    h = request.headers
    node = h.get("x-ss-node", "")
    ts = h.get("x-ss-ts", "")
    sig = h.get("x-ss-sig", "")
    claimed = h.get("x-ss-body", "")
    nonce = h.get("x-ss-nonce", "")
    # [FIX-CRIT] العميل يوقّع الطلب مع nonce ويرسله في X-SS-Nonce، بينما كان الخادم
    # يحسب التوقيع المتوقع بدونه، فكان كل طلب P2P يُرفض بـ "invalid signature".
    if not nonce or len(nonce) > 128:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail="missing nonce")
    try:
        if abs(time.time() - int(ts)) > 120:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                detail="stale timestamp")
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail="invalid headers") from exc

    expected = sign_request(app.config.group_key, request.method, target,
                            ts, claimed, node, nonce)
    if not safe_eq(expected, sig):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail="invalid signature")
    # [FIX] حماية من إعادة التشغيل: كل nonce يُقبل مرة واحدة خلال نافذة الطابع الزمني.
    # يُفحص بعد التحقق من التوقيع حتى لا يملأ مهاجم مجهول الذاكرة المؤقتة.
    if not app.engine.p2p_protocol.remember_nonce(node, nonce):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail="replayed request")
    if body_sha_expected is not None and claimed and \
            not safe_eq(claimed, body_sha_expected):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="body hash mismatch")
    return node, claimed, sig


async def _read_body(request: Request, expected_sha: str) -> bytes:
    body = await request.body()
    actual = hashlib.sha256(body).hexdigest()
    if not safe_eq(actual, expected_sha):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="body hash mismatch")
    return body


@router.get("/hello")
async def hello(request: Request):
    await _verify(request, str(request.url.path)
                  + (f"?{request.url.query}" if request.url.query else ""),
                  EMPTY_SHA)
    app = _app(request)
    return {
        "id": app.config.node_id,
        "name": app.config.node_name,
        "version": APP_VERSION,
        "shares": list(app.config.shares()),
    }


@router.get("/manifest")
async def manifest(request: Request, share: str = Query(...)):
    app = _app(request)
    target = str(request.url.path) + f"?share={urllib.parse.quote(share)}"
    await _verify(request, target, EMPTY_SHA)
    if share not in app.config.shares():
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=i18n.t("error.not_found"))
    # [FIX] manifest() يمسح القرص ويقرأ كل جدول الملفات؛ تشغيله مباشرة داخل
    # async def كان يجمّد حلقة الأحداث (واجهة المستخدم وكل الطلبات) أثناء المسح.
    files = await asyncio.to_thread(app.engine.manifest, share)
    return {"node": app.config.node_id, "files": files}


@router.post("/notify")
async def notify(request: Request):
    app = _app(request)
    target = str(request.url.path)
    # [FIX] نتحقق من التوقيع (ترويسات فقط) قبل قراءة الجسم، فلا يستطيع مجهول
    # إجبار الخادم على تحميل جسم كبير في الذاكرة.
    _node, claimed, _sig = await _verify(request, target)
    body = await _read_body(request, claimed)
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="invalid json") from exc
    share = payload.get("share", "")
    node = request.headers.get("x-ss-node", "")
    if node and share in app.config.shares():
        app.engine.request_sync(share, node)
    return {"ok": True}


@router.post("/delta")
async def delta(request: Request):
    app = _app(request)
    target = str(request.url.path)
    _node, claimed, _sig = await _verify(request, target)
    body = await _read_body(request, claimed)
    try:
        req = json.loads(body)
        rel = sanitize_relpath(req["path"])
        share = req["share"]
    except (KeyError, ValueError, PathError, json.JSONDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=i18n.t("error.invalid_input")) from exc

    if share not in app.config.shares():
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=i18n.t("error.not_found"))

    def _stream():
        for frame in app.engine.p2p_delta_stream(share, rel,
                                                 req.get("signature")):
            yield frame

    return StreamingResponse(_stream(),
                             media_type="application/octet-stream")


@router.post("/inbox")
async def inbox(
    request: Request,
    name: Annotated[str, Query(max_length=255)] = "file",
):
    """يستقبل ملفًا مرسَلًا مباشرة من نظير.

    [FIX-CRIT] كان معرَّفًا بـ ``UploadFile = File(...)`` (multipart) بينما يرسل
    ``PeerClient`` الملف كجسم خام بلا Content-Type، فكان FastAPI يرد 422 دائمًا
    وتفشل ميزة «إرسال إلى نظير». نقرأ الآن الجسم المتدفق مباشرة.
    """
    app = _app(request)
    query = request.url.query
    target = str(request.url.path) + (("?" + query) if query else "")
    _node, claimed, _sig = await _verify(request, target)
    if not claimed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="missing body hash")

    try:
        safe_name = os.path.basename(sanitize_relpath(name))
    except PathError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=i18n.t("error.path_unsafe")) from exc
    ext = os.path.splitext(safe_name)[1].lower()
    # [FIX-MED-3] استخدام الثابت المشترك بدل تكرار القائمة.
    if app.config.block_executable_extensions and ext in FORBIDDEN_EXECUTABLE_EXT:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail=i18n.t("error.extension_blocked", ext=ext))

    root = app.config.receive_folder
    tmpdir = Path(root) / ".p2p_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    tmp = str(tmpdir / f"in-{uuid.uuid4().hex}")
    max_size = int(app.config.max_file_size)

    hasher = hashlib.sha256()
    size = 0
    try:
        with open(tmp, "wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > max_size:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                        detail=i18n.t("error.file_too_large"))
                hasher.update(chunk)
                fh.write(chunk)
            fh.flush()
            os.fsync(fh.fileno())

        if not safe_eq(hasher.hexdigest(), claimed):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                detail="body hash mismatch")

        dest = unique_path(os.path.join(root, safe_name))
        os.replace(tmp, dest)
    finally:
        # [FIX] كان الملف المؤقت يبقى عند انقطاع الاتصال أو أي استثناء.
        if os.path.exists(tmp):
            with contextlib.suppress(OSError):
                os.remove(tmp)

    app.engine.counters["bytes_received"] += size
    loc = app.engine.locate(dest)
    if loc:
        app.engine.index_path(*loc)
        app.engine._schedule_notify(loc[0])
    app.notifier.show_notification(i18n.t("notif.file_received_title"),
                                   os.path.basename(dest), "success")
    return {"ok": True, "name": os.path.basename(dest)}
