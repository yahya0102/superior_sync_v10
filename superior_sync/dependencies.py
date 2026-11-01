"""FastAPI dependency-injection layer for Superior Sync.

This module is deliberately small and orthogonal to :mod:`integrations`:

* :mod:`integrations` owns the optional subsystems (analytics, notifications,
  cloud, autostart, error log, integration hub).
* :mod:`dependencies` owns the per-request plumbing that ties a running
  ``SuperiorSyncApp`` instance to the FastAPI routers.

The registry is intentionally module-level so tests can introspect it
directly (``dependencies._registry``) without instantiating the app.
"""
from __future__ import annotations

import ipaddress
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from . import i18n
from .config import ROLE_PERMISSIONS
from .utils import safe_eq


# ==================================================================
# Registry — populated once at start-up
# ==================================================================

_registry: dict[str, Any] = {
    "security": None,
    "limiter": None,
    "engine": None,
    "local_token": None,
    "trusted_proxies": [],
}


def install(
    security,
    *,
    limiter: "RateLimiter | None" = None,
    sync_engine: Any = None,
    local_token: str | None = None,
    trusted_proxies: list[str] | None = None,
) -> str:
    """Register the running subsystems.

    Returns the loopback-only admin token.  ``SuperiorSyncApp`` should keep
    this value and hand it to :func:`superior_sync.ui.render_html` so the
    in-page JavaScript can authenticate against ``/api/*`` without a cookie.

    Calling ``install`` again preserves the previously generated token
    unless a new one is supplied explicitly.
    """
    token = (
        local_token
        or _registry.get("local_token")
        or secrets.token_urlsafe(32)
    )
    _registry["security"] = security
    _registry["limiter"] = limiter
    _registry["engine"] = sync_engine
    _registry["local_token"] = token
    _registry["trusted_proxies"] = list(trusted_proxies or [])
    return token


def get_security():
    return _registry.get("security")


def get_sync_engine():
    return _registry.get("engine")


def get_rate_limiter():
    return _registry.get("limiter")


def get_local_token():
    return _registry.get("local_token")


# ==================================================================
# Rate limiting — token bucket per (ip, bucket)
# ==================================================================

class RateLimiter:
    """Token-bucket limiter keyed by ``(ip, bucket)``.

    Each logical bucket has its own capacity and refill window, so a login
    flood cannot starve the file API and vice versa.  Safe to call from the
    thread pool uvicorn uses.
    """

    # [FIX-MED-10] كانت ``login`` بسعة 10/دقيقة، وهو قاسٍ على شبكات
    # NAT المشتركة (مكاتب، مقاهي، منازل بأجهزة كثيرة). رفعناها إلى
    # 30/دقيقة، وهو ما يزال يحدّ من هجمات العنف الغاشم بينما يسمح
    # بأخطاء إدخال متكرّرة من شبكة واحدة.
    BUCKETS: dict[str, tuple[float, float]] = {
        # name -> (capacity, window_seconds)
        "login":  (30.0,  60.0),
        "p2p":    (240.0, 60.0),
        "upload": (60.0,  60.0),
        "api":    (600.0, 60.0),
    }

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[tuple[str, str], tuple[float, float]] = {}
        self._last_gc = time.monotonic()

    def _gc_locked(self, now: float, max_age: float = 600.0) -> None:
        if now - self._last_gc < 60.0:
            return
        self._last_gc = now
        stale = [k for k, (_, ts) in self._state.items() if now - ts > max_age]
        for key in stale:
            self._state.pop(key, None)

    def check(self, ip: str, bucket: str = "api") -> bool:
        capacity, window = self.BUCKETS.get(bucket, self.BUCKETS["api"])
        rate = capacity / window
        now = time.monotonic()
        key = (ip or "-", bucket)
        with self._lock:
            self._gc_locked(now)
            tokens, last = self._state.get(key, (capacity, now))
            tokens = min(capacity, tokens + (now - last) * rate)
            if tokens < 1.0:
                self._state[key] = (tokens, now)
                return False
            self._state[key] = (tokens - 1.0, now)
            return True

    def reset(self, ip: str | None = None) -> None:
        with self._lock:
            if ip is None:
                self._state.clear()
                return
            key_ip = ip or "-"
            for key in [k for k in self._state if k[0] == key_ip]:
                self._state.pop(key, None)


# ==================================================================
# Principal — the authenticated caller for a single request
# ==================================================================

@dataclass
class Principal:
    """The authenticated caller for a single request."""

    name: str = "anonymous"
    role: str = "guest"
    authenticated: bool = False
    is_local: bool = False
    ip: str = "-"
    token: str | None = None
    permissions: list[str] = field(default_factory=list)

    def can(self, permission: str) -> bool:
        return permission in self.permissions


def _peer_ip(request: Request) -> str:
    client = getattr(request, "client", None)
    if client is None:
        return "-"
    host = getattr(client, "host", None)
    return host or "-"


def _is_trusted_proxy(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        return False
    for raw in _registry.get("trusted_proxies", []):
        try:
            if address in ipaddress.ip_network(raw, strict=False):
                return True
        except (ValueError, TypeError):
            continue
    return False


def _client_ip(request: Request) -> str:
    peer = _peer_ip(request)
    if not _is_trusted_proxy(peer):
        return peer
    headers = getattr(request, "headers", None)
    forwarded = headers.get("x-forwarded-for") if headers else None
    if not forwarded:
        return peer
    try:
        chain = [
            ipaddress.ip_address(item.strip())
            for item in forwarded.split(",")
        ]
    except (ValueError, TypeError):
        return peer
    current = ipaddress.ip_address(peer)
    for address in reversed(chain):
        if not _is_trusted_proxy(str(current)):
            break
        current = address
    return str(current)


def _is_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_loopback
    except (ValueError, TypeError):
        return False


# Forwarded headers are only trusted when the direct peer matches the
# configured ``trusted_proxies`` networks.
_FORWARDED_HEADER_NAMES = (
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
    "forwarded",
)


def _has_forwarded_header(request: Request) -> bool:
    """Return whether the request contains any recognized proxy header."""
    headers = getattr(request, "headers", None)
    if not headers:
        return False
    for name in _FORWARDED_HEADER_NAMES:
        try:
            value = headers.get(name)
        except (AttributeError, TypeError):
            value = None
        if value:
            return True
    return False


def _may_use_local_token(request: Request) -> bool:
    peer = _peer_ip(request)
    if _has_forwarded_header(request):
        return _is_trusted_proxy(peer) and _is_loopback(_client_ip(request))
    return _is_loopback(peer)


def _origin_matches_request(request: Request) -> bool:
    origin = getattr(request, "headers", {}).get("origin")
    if not origin:
        return True
    try:
        origin_url = urlsplit(origin)
        request_url = urlsplit(str(request.url))
        if origin_url.scheme not in ("http", "https") or not origin_url.hostname:
            return False
        scheme = request_url.scheme
        if _is_trusted_proxy(_peer_ip(request)):
            forwarded_proto = request.headers.get("x-forwarded-proto", "")
            proto = forwarded_proto.split(",", 1)[0].strip().lower()
            if proto in ("http", "https"):
                scheme = proto
        origin_port = origin_url.port or (443 if origin_url.scheme == "https" else 80)
        request_port = request_url.port or (443 if scheme == "https" else 80)
        return (
            origin_url.scheme == scheme
            and origin_url.hostname.casefold() == (request_url.hostname or "").casefold()
            and origin_port == request_port
        )
    except ValueError:
        return False


async def get_principal(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    ss_session: str | None = Cookie(None, alias="ss_session"),
    x_ss_local_token: str | None = Header(None, alias="X-SS-Local-Token"),
) -> Principal:
    """Resolve the caller's :class:`Principal`.

    Resolution order:

    1. **Loopback admin token** — ``X-SS-Local-Token`` matching the token
       generated at start-up, honoured only for direct loopback calls
       (no ``X-Forwarded-*`` / ``X-Real-IP`` / ``Forwarded`` headers).
    2. **Bearer token** — ``Authorization: Bearer <session-token>``.
    3. **Session cookie** — ``ss_session`` set by ``/api/auth/login``.
    """
    ip = _client_ip(request)
    security = _registry.get("security")

    stored_token = _registry.get("local_token")
    if (
        x_ss_local_token
        and stored_token
        and _may_use_local_token(request)
    ):
        if safe_eq(x_ss_local_token, stored_token):
            return Principal(
                name="local",
                role="admin",
                authenticated=True,
                is_local=True,
                ip=ip,
                token=None,
                permissions=list(ROLE_PERMISSIONS.get("admin", [])),
            )

    if security is None:
        return Principal(ip=ip)

    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif ss_session:
        token = ss_session
    if not token:
        cookies = getattr(request, "cookies", None)
        if cookies is not None:
            try:
                token = cookies.get("ss_session")
            except AttributeError:
                token = None

    if not token:
        return Principal(ip=ip)

    username = security.validate_token(token)
    if not username:
        return Principal(ip=ip)

    role = security.get_user_role(username) or "guest"
    users = getattr(security, "users", {}) or {}
    user_data = users.get(username, {}) or {}
    permissions = list(
        user_data.get("permissions")
        or ROLE_PERMISSIONS.get(role, ["read"])
    )

    return Principal(
        name=username,
        role=role,
        authenticated=True,
        is_local=False,
        ip=ip,
        token=token,
        permissions=permissions,
    )


# ==================================================================
# Permission dependency factory
# ==================================================================

def require_permission(permission: str):
    """FastAPI dependency factory enforcing a single permission.

    Router usage::

        @router.get("/x")
        async def x(principal: Principal = Depends(require_permission("read"))):
            ...

    The returned coroutine can also be invoked directly with a
    :class:`Principal` instance (as the offline tests do)::

        await require_permission("read")(principal)
    """

    async def _dep(
        principal: Principal = Depends(get_principal),
    ) -> Principal:
        if not principal.authenticated:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                detail=i18n.t("auth.login_required"),
            )
        if permission not in principal.permissions:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=i18n.t("auth.forbidden"),
            )
        return principal

    return _dep


__all__ = [
    "Principal",
    "RateLimiter",
    "get_local_token",
    "get_principal",
    "get_rate_limiter",
    "get_security",
    "get_sync_engine",
    "install",
    "require_permission",
    "_registry",
]