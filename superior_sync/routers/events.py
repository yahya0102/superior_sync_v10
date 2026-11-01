"""Server-Sent Events stream.

Authentication notes
--------------------

The browser's native :class:`EventSource` API **cannot** attach custom
headers to its request, so ``Authorization: Bearer`` and
``X-SS-Local-Token`` are unavailable on this endpoint.  Authentication
therefore relies entirely on the ``ss_session`` cookie — which the
browser *does* send automatically, same-origin — and is enforced by
:func:`dependencies.require_permission`, whose resolver falls back to
the cookie when no bearer header is present.
"""
from __future__ import annotations

import asyncio
import queue

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from .. import i18n
from ..dependencies import Principal, require_permission

router = APIRouter(tags=["events"])


@router.get("/api/events")
async def stream_events(
    request: Request,
    principal: Principal = Depends(require_permission("read")),
):
    app = request.app.state.superior
    q: queue.Queue[bytes] = queue.Queue(maxsize=100)
    with app._sse_lock:
        if len(app._sse_clients) >= 20:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=i18n.t("error.rate_limit"),
            )
        app._sse_clients.append(q)

    async def _gen():
        # [FIX-MED-2] ``asyncio.get_event_loop()`` أُهمل في 3.10+
        # وقد يفشل في 3.12+ خارج سياق loop. ``get_running_loop`` هو
        # البديل الصحيح داخل coroutine.
        loop = asyncio.get_running_loop()
        try:
            yield b"retry: 5000\n\n"
            while True:
                try:
                    chunk = await loop.run_in_executor(None, q.get, True, 30)
                    yield chunk
                except queue.Empty:
                    yield b": keepalive\n\n"
                except asyncio.CancelledError:
                    break
        finally:
            with app._sse_lock:
                if q in app._sse_clients:
                    app._sse_clients.remove(q)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )