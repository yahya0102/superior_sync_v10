"""Analytics, system diagnostics, and Server-Sent Events."""
from __future__ import annotations

import os
import platform as _platform
import socket
import sys
import time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from .. import APP_VERSION, i18n
from ..dependencies import Principal, require_permission
from ..utils import (HAS_CRYPTO, HAS_PSUTIL, HAS_WATCHFILES,
                     get_local_ips, human_size)

router = APIRouter(tags=["analytics"])

ALLOWED_KINDS = {"line", "bar", "pie", "scatter"}
ALLOWED_METRICS = {
    "cpu_percent", "memory_percent", "recv_rate", "send_rate",
    "bytes_sent", "bytes_recv", "disk_percent",
}


def _app(request: Request):
    return request.app.state.superior


@router.get("/api/analytics")
async def analytics(
    request: Request,
    range: str = Query("hour"),
    principal: Principal = Depends(require_permission("read")),
):
    return _app(request).analytics.get_dashboard_data(range)


@router.get("/api/analytics/chart")
async def chart(
    request: Request,
    type: str = Query("line"),
    metric: str = Query("cpu_percent"),
    range: str = Query("hour"),
    principal: Principal = Depends(require_permission("read")),
):
    app = _app(request)
    if type not in ALLOWED_KINDS or metric not in ALLOWED_METRICS:
        return Response(status_code=400)
    source = ("network_usage"
              if metric in {"recv_rate", "send_rate", "bytes_sent", "bytes_recv"}
              else "system_performance")
    rows = app.analytics.get_metrics(
        source, range if range in app.analytics.RANGES else "hour")
    data = [(r["timestamp"], r.get(metric)) for r in rows
            if r.get(metric) is not None]
    svg = app.analytics.generate_chart(type, data, {"title": metric})
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/api/system")
async def system_info(
    request: Request,
    principal: Principal = Depends(require_permission("read")),
):
    app = _app(request)
    return {
        "hostname": socket.gethostname(),
        "platform": _platform.platform(),
        "python": sys.version.split()[0],
        "app_version": APP_VERSION,
        "data_dir": str(app.config.data_dir),
        "ips": get_local_ips(),
        "cpu_count": os.cpu_count(),
        "psutil": HAS_PSUTIL,
        "watchfiles": HAS_WATCHFILES,
        "cryptography": HAS_CRYPTO,
        "node_id": app.config.node_id,
        "port": app.config.active_port,
        "tls": app.config._tls_active,
    }


@router.get("/api/diagnostics")
async def diagnostics(
    request: Request,
    principal: Principal = Depends(require_permission("configure")),
):
    import shutil
    app = _app(request)
    c, e = app.config, app.engine
    checks: list[dict] = []

    def _add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    _add(i18n.t("diag.db_ok"), os.access(c.receive_folder, os.W_OK),
         c.receive_folder)
    for sid, path in c.shares().items():
        _add(f"share[{sid}]",
             os.path.isdir(path) and os.access(path, os.R_OK | os.W_OK),
             path)
    _add(i18n.t("sync.started"), e.running)
    _add("watcher", e.file_watcher.running, e.file_watcher.backend_name())
    _add("p2p", e.p2p_protocol.running,
         f"{len(e.p2p_protocol.online_peers())}")
    _add(i18n.t("diag.encryption_on" if c.enable_encryption and HAS_CRYPTO
                else "diag.encryption_off"),
         bool(c.enable_encryption and HAS_CRYPTO))
    _add(i18n.t("diag.tls_on" if c._tls_active else "diag.tls_off"),
         c._tls_active)
    try:
        du = shutil.disk_usage(c.receive_folder)
        _add("disk", du.free > 500 * 1024 * 1024, human_size(du.free))
    except OSError:
        pass
    _add("database",
         (e.db.one("PRAGMA integrity_check") or {}).get("integrity_check")
         == "ok")
    return {"checks": checks, "ok": all(x["ok"] for x in checks)}


@router.post("/api/cache/clear")
async def clear_cache(
    request: Request,
    principal: Principal = Depends(require_permission("configure")),
):
    app = _app(request)
    removed = 0
    for root in app.config.shares().values():
        for r, _, files in os.walk(root):
            for name in files:
                if not name.startswith(".sync-tmp-"):
                    continue
                full = os.path.join(r, name)
                # [FIX-MED-5] قد يُحذف الملف بين walk وgetmtime —
                # نتجاهل OSError بدل أن نُسقط الطلب.
                try:
                    mtime = os.path.getmtime(full)
                except OSError:
                    continue
                if time.time() - mtime > 600:
                    try:
                        os.remove(full)
                        removed += 1
                    except OSError:
                        pass
    import gc
    gc.collect()
    return {"success": True, "removed_temp_files": removed}