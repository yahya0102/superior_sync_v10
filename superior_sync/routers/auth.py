"""Authentication, session management, and self-registration."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from .. import i18n
from ..dependencies import Principal, get_principal, require_permission
from ..schemas import (
    ChangePasswordRequest,
    CreateUserRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UpdateUserRequest,
    UserPublic,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/admin/users", tags=["admin"])


def _app(request: Request):
    """Utility helper to access application state."""
    return request.app.state.superior


def _set_session_cookie(response: Response, token: str, secure: bool) -> None:
    """Sets the secure HTTP-Only session cookie."""
    response.set_cookie(
        "ss_session",
        token,
        httponly=True,
        samesite="strict",
        secure=secure,
        max_age=86400,
        path="/",
    )


# ---------------------------------------------------------------- Authentication Routes

@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request, response: Response):
    app = _app(request)
    ip = request.client.host if request.client else "-"

    if not app.security.authenticate_user(payload.username, payload.password, ip):
        app.audit(payload.username, "auth.login_failed", ip=ip, result="failed")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail=i18n.t("auth.invalid_credentials"))

    token = app.security.generate_session_token(payload.username)
    _set_session_cookie(response, token, app.config._tls_active)
    role = app.security.get_user_role(payload.username)

    app.audit(payload.username, "auth.login", ip=ip, result="ok")
    return LoginResponse(
        token=token,
        user={"username": payload.username, "role": role},
    )


@router.post("/register", response_model=LoginResponse)
async def register(payload: RegisterRequest, request: Request, response: Response):
    app = _app(request)
    if not app.config.allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=i18n.t("auth.forbidden"))

    if not app.security.create_user(payload.username, payload.password, "user"):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=i18n.t("error.invalid_input"))

    ip = request.client.host if request.client else "-"
    app.audit(payload.username, "auth.register", ip=ip, result="ok")
    return await login(payload, request, response)


@router.get("/me")
async def me(principal: Principal = Depends(get_principal)):
    if not principal.authenticated:
        return {"login_required": True}
    return {
        "username": principal.name,
        "role": principal.role,
        "local": principal.is_local and principal.name == "local",
    }


@router.post("/logout")
async def logout(request: Request, response: Response,
                 principal: Principal = Depends(get_principal)):
    app = _app(request)
    if principal.token:
        app.security.revoke_token(principal.token)
    response.delete_cookie("ss_session", path="/")

    if principal.authenticated:
        app.audit(principal.name, "auth.logout", ip=principal.ip)
    return {"success": True, "message": i18n.t("auth.logged_out")}


@router.post("/password")
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    principal: Principal = Depends(get_principal),
):
    app = _app(request)
    if not principal.authenticated:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            detail=i18n.t("auth.login_required"))
    if principal.name == "local":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=i18n.t("error.invalid_input"))

    if not app.security.authenticate_user(principal.name, payload.old, principal.ip):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail=i18n.t("auth.invalid_credentials"))

    if not app.security.set_password(principal.name, payload.new):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail=i18n.t("error.invalid_input"))

    app.audit(principal.name, "auth.password_change", ip=principal.ip)
    return {"success": True, "message": i18n.t("auth.password_changed")}


# ---------------------------------------------------------------- Admin User Management Routes

@admin_router.get("")
async def list_users(
    request: Request,
    principal: Principal = Depends(require_permission("manage_users")),
):
    app = _app(request)
    return {"users": [UserPublic(**u) for u in app.security.public_users()]}


@admin_router.post("")
async def create_user(
    payload: CreateUserRequest,
    request: Request,
    principal: Principal = Depends(require_permission("manage_users")),
):
    app = _app(request)
    if not app.security.create_user(payload.username, payload.password, payload.role):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=i18n.t("error.invalid_input"))

    app.audit(principal.name, "user.create", payload.username, ip=principal.ip)
    return {"success": True}


@admin_router.put("/{username}")
async def update_user(
    username: str,
    payload: UpdateUserRequest,
    request: Request,
    principal: Principal = Depends(require_permission("manage_users")),
):
    """Update a user's role and/or password.

    Role changes are applied in-place under the security lock (so the
    "last admin" invariant can be enforced atomically).  Password changes
    go through :meth:`SecurityManager.set_password`, which handles
    re-hashing, persistence, and token revocation as a single operation —
    we never call ``_hash_password`` directly from outside the module.
    """
    from ..config import ROLE_PERMISSIONS

    app = _app(request)

    role_changed = False
    with app.security.lock:
        user = app.security.users.get(username)
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                detail=i18n.t("error.not_found"))

        if payload.role is not None:
            if payload.role not in ROLE_PERMISSIONS:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    detail=i18n.t("error.invalid_input"))
            if user["role"] == "admin" and payload.role != "admin":
                admins = sum(1 for u in app.security.users.values()
                             if u["role"] == "admin")
                if admins <= 1:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                        detail=i18n.t("auth.forbidden"))
            user["role"] = payload.role
            user["permissions"] = list(ROLE_PERMISSIONS[payload.role])
            app.security._save_users()
            role_changed = True

    if payload.password:
        # Public API: hashes + saves + revokes tokens atomically.
        if not app.security.set_password(username, payload.password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                detail=i18n.t("error.invalid_input"))
    elif role_changed:
        # Role changed but password unchanged → force re-auth so the new
        # permissions take effect on the next request.
        app.security.revoke_user_tokens(username)

    app.audit(principal.name, "user.update", username, ip=principal.ip)
    return {"success": True}


@admin_router.delete("/{username}")
async def delete_user(
    username: str,
    request: Request,
    principal: Principal = Depends(require_permission("manage_users")),
):
    app = _app(request)
    user = app.security.users.get(username)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=i18n.t("error.not_found"))

    if user["role"] == "admin" and sum(
            1 for u in app.security.users.values() if u["role"] == "admin") <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=i18n.t("auth.forbidden"))

    # الحارس الذري داخل delete_user: يرفض حذف آخر أدمن حتى مع طلبات متزامنة.
    if not app.security.delete_user(username):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=i18n.t("auth.forbidden"))
    app.audit(principal.name, "user.delete", username, ip=principal.ip)
    return {"success": True}