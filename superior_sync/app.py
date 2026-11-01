"""FastAPI application factory and router wiring."""
from __future__ import annotations

import contextlib
import json
import shutil
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import APP_VERSION, dependencies, i18n
from .config import SecurityManager
from .integrations import IntegrationHub
from .routers import (
    admin, analytics, auth, cloud, conflicts, events, files, notifications, p2p, peers, sync,
)
from .sync_core import SyncEngine
from .ui import render_html
from .utils import get_local_ips, safe_eq

# [FIX] كان سقف واحد (500MB) يُطبَّق على كل المسارات: نقاط JSON الصغيرة كانت تقبل
# أجسامًا بهذا الحجم (استنزاف ذاكرة)، بينما يُرفض أي ملف أكبر منه رغم أن
# max_file_size الافتراضي 10GB. الآن: سقف صغير افتراضيًا، وسقف max_file_size
# لمسارات رفع الملفات فقط.
DEFAULT_MAX_BODY_SIZE = 16 * 1024 * 1024
P2P_DELTA_MAX_BODY = 128 * 1024 * 1024
MIN_FREE_DISK_BYTES = 100 * 1024 * 1024

# Bounded pool for webhook deliveries.
#
# ``SyncEngine`` calls ``self._fire_webhook(event, data)`` — wired in
# ``SuperiorSyncApp.__init__`` to :meth:`fire_webhook` below — so every
# webhook delivery funnels through this pool instead of spawning a raw
# ``threading.Thread`` per delivery.  Without it, a peer with N enabled
# webhooks and M events/sec could trivially spawn hundreds of threads; a
# small fixed pool with a queue provides back-pressure instead.
WEBHOOK_POOL_WORKERS = 8


def _send_webhook(url: str, secret: str, event: str, data: dict) -> None:
    from .integrations import _http
    from .utils import is_safe_external_url, log
    import hashlib
    import hmac

    ok, _ = is_safe_external_url(url)
    if not ok:
        log.warning("Skipping unsafe webhook: %s", url)
        return
    payload = json.dumps(
        {"event": event, "data": data, "ts": time.time()}
    ).encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    try:
        _http(
            "POST",
            url,
            {"Content-Type": "application/json", "X-SS-Signature": signature},
            payload,
            timeout=10,
        )
    except Exception as exc:
        log.debug("Webhook %s failed: %s", url, exc)


class _BodyTooLarge(Exception):
    pass


class _BodySizeLimitMiddleware:
    def __init__(self, app, max_size, overrides=None):
        self.app = app
        self.max_size = max_size
        self.overrides = overrides or {}

    def _limit_for(self, path):
        value = self.overrides.get(path)
        if value is None:
            return self.max_size
        return int(value() if callable(value) else value)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in (
                "POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)

        limit = self._limit_for(scope.get("path", ""))
        for name, value in scope.get("headers", ()):
            if name == b"content-length":
                try:
                    if int(value) > limit:
                        return await self._reject(send)
                except ValueError:
                    pass
                break

        total = 0
        responded = False

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                if chunk:
                    total += len(chunk)
                    if total > limit:
                        raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal responded
            if message["type"] == "http.response.start":
                responded = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not responded:
                await self._reject(send)

    @staticmethod
    async def _reject(send):
        body = json.dumps({"error": i18n.t("error.file_too_large")}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class SuperiorSyncApp:
    """Owns the running subsystems and exposes the FastAPI ASGI app."""

    def __init__(self, config, master_password: str | None = None) -> None:
        self.config = config
        self.started_at = time.time()

        self.engine = SyncEngine(config)
        self.security = SecurityManager(
            config.data_dir,
            master_password or getattr(config, "_master_password", None),
        )

        # Central orchestrator.  ``IntegrationHub`` owns the ErrorLog,
        # NotificationSystem, AnalyticsEngine and CloudIntegration, wires
        # errors → notifications, analytics → thresholds, and cloud →
        # circuit breakers.  We keep thin aliases for the attribute names
        # the routers and ``main.py`` already use (``app.analytics``,
        # ``app.notifier``, ``app.cloud``).
        self.hub = IntegrationHub(config, self.engine)
        self.analytics = self.hub.analytics
        self.notifier = self.hub.notifier
        self.cloud = self.hub.cloud
        self.errors = self.hub.errors

        self.engine.notifier = self.notifier
        self.engine._fire_webhook = self.fire_webhook

        self.rate_limiter = dependencies.RateLimiter()
        self.local_admin_token = dependencies.install(
            self.security,
            limiter=self.rate_limiter,
            sync_engine=self.engine,
            trusted_proxies=getattr(config, "trusted_proxies", []),
        )

        # Bounded executor for webhook fan-out (see WEBHOOK_POOL_WORKERS).
        self._webhook_pool = ThreadPoolExecutor(
            max_workers=WEBHOOK_POOL_WORKERS,
            thread_name_prefix="webhook",
        )

        self._sse_clients: list = []
        self._sse_lock = threading.Lock()
        self._bg_stop = threading.Event()
        self._bg_thread = None

        # Wire the hub's event bus onto our SSE stream so ``error_logged``
        # and ``notification_created`` events reach the browser live.
        self.hub.attach_broadcast(self._hub_broadcast)

        self.api = self._build_fastapi()

    # ------------------------------------------------------------------
    # Integration-hub plumbing
    # ------------------------------------------------------------------

    def _hub_broadcast(self, event: str, payload: dict) -> None:
        """Adapter: the hub publishes onto our SSE bus."""
        self.broadcast_event(event, payload)

    # ------------------------------------------------------------------
    def _trusted_hosts(self) -> list[str]:
        hosts = {"localhost", "127.0.0.1", "::1"}
        try:
            hosts.add(socket.gethostname())
            hosts.add(socket.getfqdn())
        except OSError:
            pass
        try:
            hosts.update(get_local_ips())
        except OSError as exc:
            from .utils import log
            log.debug("Local IP discovery failed; using loopback/configured hosts: %s", exc)
        for h in getattr(self.config, "trusted_hosts", []) or []:
            hosts.add(str(h))
        if self.config.server_host and self.config.server_host != "0.0.0.0":
            hosts.add(self.config.server_host)
        return sorted(hosts)

    def _build_fastapi(self) -> FastAPI:
        app = FastAPI(
            title="Superior Sync",
            version=APP_VERSION,
            docs_url="/api/docs",
            redoc_url=None,
            openapi_url="/api/openapi.json",
        )
        app.state.superior = self

        app.add_middleware(GZipMiddleware, minimum_size=1024)
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=self._trusted_hosts(),
        )
        app.add_middleware(
            _BodySizeLimitMiddleware,
            max_size=int(getattr(self.config, "max_upload_size",
                                 DEFAULT_MAX_BODY_SIZE)),
            overrides={
                # +1MB هامش لترويسات multipart
                "/api/files/upload": lambda: int(self.config.max_file_size) + (1 << 20),
                "/p2p/inbox": lambda: int(self.config.max_file_size),
                "/p2p/delta": P2P_DELTA_MAX_BODY,
            },
        )

        @app.middleware("http")
        async def _csrf_header_middleware(request: Request, call_next):
            if request.method in ("POST", "PUT", "PATCH", "DELETE"):
                path = request.url.path
                if not path.startswith("/p2p/"):
                    has_bearer = (
                        request.headers.get("authorization", "")
                        .lower().startswith("bearer ")
                    )
                    if not has_bearer:
                        if not dependencies._origin_matches_request(request):
                            return JSONResponse(
                                {"error": i18n.t("auth.forbidden")},
                                status_code=403,
                            )
                        if request.headers.get("x-requested-with") != "SuperiorSync":
                            return JSONResponse(
                                {"error": i18n.t("auth.forbidden")},
                                status_code=403,
                            )
            return await call_next(request)

        @app.middleware("http")
        async def _disk_guard_middleware(request: Request, call_next):
            if request.method in ("POST", "PUT", "PATCH"):
                path = request.url.path
                if ("/upload" in path or path.startswith("/p2p/inbox")
                        or path.startswith("/api/files/upload")):
                    try:
                        usage = shutil.disk_usage(str(self.config.data_dir))
                        if usage.free < MIN_FREE_DISK_BYTES:
                            return JSONResponse(
                                {"error": i18n.t("diag.disk_low",
                                                 free=f"{usage.free // (1024*1024)} MB")},
                                status_code=507,
                            )
                    except OSError:
                        pass
            return await call_next(request)

        @app.middleware("http")
        async def _rate_limit_middleware(request: Request, call_next):
            ip = dependencies._client_ip(request)
            path = request.url.path
            if path in ("/api/auth/login", "/api/auth/register"):
                bucket = "login"
            elif path.startswith("/p2p/"):
                bucket = "p2p"
            elif path.startswith("/api/files/upload"):
                bucket = "upload"
            else:
                bucket = "api"
            if not self.rate_limiter.check(ip, bucket):
                return JSONResponse(
                    {"error": i18n.t("error.rate_limit")},
                    status_code=429,
                )
            return await call_next(request)

        @app.middleware("http")
        async def _language_middleware(request: Request, call_next):
            raw = request.query_params.get("lang") or \
                request.headers.get("accept-language")
            i18n.set_language(raw)
            return await call_next(request)

        @app.exception_handler(RequestValidationError)
        async def _validation_handler(request, exc):
            from fastapi.encoders import jsonable_encoder
            # [FIX] exc.errors() قد يحوي كائنات غير قابلة للتسلسل (ctx.error) فكان
            # المعالج نفسه يفشل بخطأ 500.
            return JSONResponse(
                {"error": i18n.t("error.invalid_input"),
                 "detail": jsonable_encoder(exc.errors(), custom_encoder={
                     Exception: lambda e: str(e)})},
                status_code=422,
            )

        @app.exception_handler(Exception)
        async def _unhandled(request, exc):  # pragma: no cover
            from .utils import log
            log.exception("Unhandled error on %s %s: %s",
                          request.method, request.url.path, exc)
            return JSONResponse({"error": i18n.t("error.internal")},
                                status_code=500)

        for module in (auth, files, sync, peers, p2p, conflicts, notifications,
                       cloud, analytics, admin, events):
            app.include_router(module.router)
        app.include_router(auth.admin_router)

        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def _index(request: Request):
            # [FIX-SEC] كانت الصفحة تُقدَّم لأي طالب والتوكن الإداري المحلي مدمج فيها؛
            # فخلف reverse proxy لا يضيف ترويسات X-Forwarded-* (nginx الافتراضي) أو
            # عبر نفق SSH أو لأي مستخدم محلي آخر، كان أي زائر يحصل على صلاحيات أدمن.
            # يُدمج التوكن فقط إذا قدّمه الطالب نفسه (?lt=...) وكان العميل فعليًا
            # loopback؛ يدعم ذلك proxy موثوقًا ومصرحًا به صراحةً في الإعدادات.
            supplied = request.query_params.get("lt", "")
            token = ""
            if (supplied
                    and safe_eq(supplied, self.local_admin_token)
                    and dependencies._may_use_local_token(request)):
                token = self.local_admin_token
            html = render_html(token)
            if token:
                # أزل التوكن من شريط العنوان/السجل فور التحميل.
                html = html.replace(
                    "</body>",
                    "<script>try{history.replaceState(null,'',location.pathname)}"
                    "catch(e){}</script></body>", 1)
            return HTMLResponse(html, headers={
                "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})

        @app.get("/ping", include_in_schema=False)
        async def _ping():
            return {
                "status": "online",
                "server": socket.gethostname(),
                "version": APP_VERSION,
                "engine": "running" if self.engine.running else "stopped",
            }

        @app.get("/health", include_in_schema=False)
        async def _health():
            return {
                "status": "healthy",
                "timestamp": time.time(),
                "components": {
                    "file_watcher": self.engine.file_watcher.running,
                    "p2p_protocol": self.engine.p2p_protocol.running,
                    "task_queue": self.engine.task_queue.running,
                    "sync_engine": self.engine.running,
                },
            }

        @app.get("/favicon.ico", include_in_schema=False)
        async def _favicon():
            return PlainTextResponse("", status_code=204)

        return app

    def audit(self, actor: str, action: str, target: str = "", ip: str = "-",
              result: str = "ok", detail: str = "") -> None:
        with contextlib.suppress(Exception):
            self.engine.db.execute(
                "INSERT INTO audit_log(ts,actor,action,target,ip,result,detail) "
                "VALUES(?,?,?,?,?,?,?)",
                (time.time(), str(actor), str(action), str(target),
                 str(ip), str(result), str(detail)),
            )

    def fire_webhook(self, event: str, data: dict) -> None:
        """Dispatch ``event`` to all enabled webhooks.

        SSE broadcast is synchronous; HTTP delivery is scheduled on the
        bounded thread pool (``_webhook_pool``) so a slow or malicious
        webhook target cannot spawn unbounded threads or block the caller.

        ``SyncEngine`` is wired to call this via ``_fire_webhook`` in
        :meth:`__init__`, so no code path can bypass the pool.
        """
        self.hub.emit(event, data)

        pool = self._webhook_pool

        for wh in self.engine.db.query("SELECT * FROM webhooks WHERE enabled=1"):
            events = wh["events"].split(",")
            if event not in events and "*" not in events:
                continue
            try:
                pool.submit(
                    partial(_send_webhook, wh["url"], wh["secret"], event, data)
                )
            except RuntimeError:
                # Pool already shut down (during app shutdown).
                return

    def broadcast_event(self, event_type: str, data: dict) -> None:
        payload = (f"event: {event_type}\n"
                   f"data: {json.dumps(data, ensure_ascii=False)}\n\n").encode()
        with self._sse_lock:
            dead = []
            for q in self._sse_clients:
                try:
                    q.put_nowait(payload)
                except Exception:
                    dead.append(q)
            for q in dead:
                self._sse_clients.remove(q)

    def start_background(self) -> None:
        def _loop():
            while not self._bg_stop.wait(60):
                with contextlib.suppress(Exception):
                    self.cloud.run_due_backups()
                with contextlib.suppress(Exception):
                    self._health_check()

        self._bg_thread = threading.Thread(target=_loop, daemon=True, name="bg")
        self._bg_thread.start()

    def _health_check(self) -> None:
        issues: list[str] = []
        try:
            # [FIX] integrity_check يمسح قاعدة البيانات كاملة (ويحجز قفلها) كل 60
            # ثانية؛ quick_check أخف بكثير ويكفي للكشف الدوري عن التلف.
            row = self.engine.db.one("PRAGMA quick_check")
            if not row or row.get("quick_check") != "ok":
                issues.append(i18n.t("error.internal"))
        except Exception:
            pass
        if not self.config.enable_encryption:
            issues.append(i18n.t("diag.encryption_off"))
        if not self.config._tls_active:
            issues.append(i18n.t("diag.tls_off"))
        if issues:
            # [FIX-MIN-12] ``dedupe_key`` يمنع تكرار نفس التحذير كل 60
            # ثانية: تُحدَّث النسخة القائمة بدل إنشاء واحدة جديدة،
            # فيبقى صندوق الإشعارات نظيفاً.
            # ``timeout=0`` يجعل الإشعار دائماً (لا يختفي تلقائياً).
            self.notifier.show_notification(
                i18n.t("notif.health_title"),
                " | ".join(issues),
                "warning",
                dedupe_key="health:report",
                timeout=0,
            )

    def shutdown(self) -> None:
        self._bg_stop.set()
        self.security.close()
        # Hub owns analytics + error log + notification flush; stopping it
        # via the orchestrator guarantees a consistent teardown order.
        with contextlib.suppress(Exception):
            self.hub.stop()
        with contextlib.suppress(Exception):
            self._webhook_pool.shutdown(wait=False, cancel_futures=True)
        self.engine.close()