"""Pydantic request / response models.

Central contract for every HTTP boundary. All input models enforce strict
type validation, forbid unknown fields, normalise strings, and expose
rich OpenAPI metadata (descriptions + examples) so the documentation at
``/api/docs`` is self-explanatory.

Design rules:

* **Strict by default** — ``extra="forbid"`` on every request model so
  typos and injection attempts fail fast with a 422.
* **Normalised inputs** — usernames, paths, and addresses are stripped
  of surrounding whitespace before validation.
* **Reusable annotated types** — the same primitive (``Username``,
  ``PortNumber``, ``AddressPattern``…) is shared across models, keeping
  validation *fast* (no duplicated validators) and *consistent*.
* **Cross-field validation** — complex payloads (``ConfigPayload``,
  ``CloudConnectRequest``) validate their fields together with
  ``model_validator(mode="after")``.
* **Immutable responses** — response models are ``frozen=True`` so they
  can be cached, hashed, and compared safely.
"""
from __future__ import annotations

import ipaddress
import os
import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


# ======================================================================
# Shared primitives
# ======================================================================

ConflictStrategy = Literal["newer", "older", "larger", "source", "target", "ask"]
Role = Literal["admin", "user", "guest"]
CloudService = Literal["folder", "dropbox", "google_drive", "onedrive", "webdav"]
BackupSchedule = Literal["hourly", "daily", "weekly", "monthly"]
FileType = Literal["file", "folder"]
PeerStatus = Literal["online", "offline"]

_USERNAME_RE = r"^[\w.\-@]{2,64}$"
_GROUP_KEY_RE = r"^\S{24,512}$"
_ADDRESS_RE = r"^[^\s:]+:\d{1,5}$"
_URL_RE = r"^https?://[^\s]+$"
_HEX_RE = r"^[A-Fa-f0-9]+$"

# Windows reserved device names — rejected on any platform to stay portable.
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul",
     *(f"com{i}" for i in range(1, 10)),
     *(f"lpt{i}" for i in range(1, 10))}
)


def _looks_like_path_traversal(value: str) -> bool:
    """Return True when the path escapes its root (``..`` or absolute)."""
    v = value.replace("\\", "/").strip()
    if not v:
        return False
    if v.startswith("/") or re.match(r"^[A-Za-z]:", v):
        return True
    parts = [p for p in v.split("/") if p and p != "."]
    return ".." in parts


def _is_safe_absolute_path(value: str) -> bool:
    """مسار مطلق (أو يبدأ بـ ~) بلا ``..`` ولا بايت NUL.

    [FIX] ``_looks_like_path_traversal`` يعتبر أي مسار مطلق اجتيازًا، فكان
    حقل ``receive_folder`` (الذي يطلب مسارًا مطلقًا حسب رسالة الخطأ نفسها) يرفض
    كل المسارات المطلقة ولا يقبل إلا النسبية التي تُحلّ لاحقًا نسبةً لمجلد التشغيل.
    """
    v = value.replace("\\", "/").strip()
    if not v or "\x00" in v:
        return False
    absolute = v.startswith("/") or v.startswith("~") or bool(re.match(r"^[A-Za-z]:/", v))
    parts = [p for p in v.split("/") if p and p != "."]
    return absolute and ".." not in parts


# [FIX-MED-8] التحقّق من نطاق منفذ ``host:port``.
#
# النمط ``_ADDRESS_RE`` يقبل ``99999`` كمنفذ. نتحقّق هنا من النطاق
# المسموح (1024–65535) الذي يتوافق مع ``PortNumber`` ومنطق ``Config``.
def _validate_address(value: str) -> str:
    host, sep, port = value.rpartition(":")
    if not sep or not host:
        raise ValueError("Expected format: host:port")
    if not port.isdigit():
        raise ValueError("Port must be numeric")
    n = int(port)
    if not 1024 <= n <= 65535:
        raise ValueError("Port out of range (1024–65535)")
    return value


# --- Reusable annotated types ----------------------------------------

Username = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=_USERNAME_RE),
]
Password = Annotated[str, StringConstraints(min_length=8, max_length=256)]
PasswordAttempt = Annotated[str, StringConstraints(min_length=1, max_length=256)]

PortNumber = Annotated[int, Field(ge=1024, le=65535)]
NodeName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
ShareId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
RelPath = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
GroupKey = Annotated[str, StringConstraints(pattern=_GROUP_KEY_RE)]
Address = Annotated[str, StringConstraints(strip_whitespace=True, pattern=_ADDRESS_RE)]
HttpUrl = Annotated[str, StringConstraints(strip_whitespace=True, pattern=_URL_RE)]
HexId = Annotated[str, StringConstraints(pattern=_HEX_RE, min_length=1, max_length=64)]


# ======================================================================
# Base classes
# ======================================================================

class _RequestModel(BaseModel):
    """Base class for every *input* model."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=False,
        populate_by_name=True,
        use_enum_values=False,
        arbitrary_types_allowed=False,
    )


class _ResponseModel(BaseModel):
    """Base class for every *output* model — frozen and JSON-clean."""

    model_config = ConfigDict(
        extra="ignore",
        frozen=True,
        str_strip_whitespace=False,
    )


# ======================================================================
# Generic envelopes
# ======================================================================

class Message(_ResponseModel):
    """Standard success envelope."""
    success: bool = True
    message: str = Field(default="", description="Human-readable result message")


class ErrorBody(_ResponseModel):
    """Standard error envelope returned by the exception handlers."""
    error: str = Field(description="Short machine-readable error code")
    detail: str | None = Field(default=None, description="Optional long description")


# ======================================================================
# Authentication
# ======================================================================

class LoginRequest(_RequestModel):
    """Credentials for ``POST /api/auth/login``."""
    username: Username = Field(..., examples=["admin"])
    password: PasswordAttempt = Field(..., examples=["correct horse battery staple"])


class LoginResponse(_ResponseModel):
    """Session token returned by a successful login."""
    success: bool = True
    token: str = Field(..., description="Opaque bearer token (cookie is set as well)")
    user: dict[str, Any] = Field(..., description="Public user fields")


class RegisterRequest(_RequestModel):
    """Payload for ``POST /api/auth/register`` (كلمة المرور ≥ 8 أحرف).

    [FIX] كان يستخدم ``LoginRequest`` (PasswordAttempt بحد أدنى حرف واحد) فيرد
    الخادم برسالة 409 غامضة بدل 422 واضحة عند كلمة مرور قصيرة.
    """
    username: Username = Field(..., examples=["alice"])
    password: Password


class ChangePasswordRequest(_RequestModel):
    """Payload for ``POST /api/auth/password``."""
    old: PasswordAttempt
    new: Password = Field(..., description="New password (≥ 8 characters)")

    @model_validator(mode="after")
    def _differs(self) -> "ChangePasswordRequest":
        if self.old == self.new:
            raise ValueError("New password must differ from the current one")
        return self


class UserPublic(_ResponseModel):
    """Public view of a user account (never includes secrets)."""
    username: Username
    role: Role
    permissions: list[str] = Field(default_factory=list)
    created_at: float | None = None


class CreateUserRequest(_RequestModel):
    """Payload for ``POST /api/admin/users``."""
    username: Username
    password: Password
    role: Role = "user"


class UpdateUserRequest(_RequestModel):
    """Payload for ``PUT /api/admin/users/{username}`` — every field optional."""
    role: Role | None = None
    password: Password | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "UpdateUserRequest":
        if self.role is None and self.password is None:
            raise ValueError("At least one of 'role' or 'password' must be provided")
        return self


# ======================================================================
# Files
# ======================================================================

class FileEntry(_ResponseModel):
    """A single row in a folder listing."""
    name: str = Field(..., max_length=255)
    path: RelPath
    size: int = Field(..., ge=0)
    modified: float = Field(..., ge=0)
    type: FileType


class FileListResponse(_ResponseModel):
    """Body of ``GET /api/files``."""
    files: list[FileEntry]
    share: ShareId
    folder: str = Field(default="", description="Relative folder path (empty = root)")


class ShareInfo(_ResponseModel):
    """Description of a configured share."""
    id: ShareId
    path: str = Field(..., max_length=4096)


class ZipRequest(_RequestModel):
    """Payload for ``POST /api/files/download-zip``."""
    share: ShareId = "received"
    paths: list[RelPath] = Field(..., min_length=1, max_length=1000)

    @field_validator("paths")
    @classmethod
    def _no_traversal(cls, value: list[str]) -> list[str]:
        for item in value:
            if _looks_like_path_traversal(item):
                raise ValueError(f"Unsafe path in list: {item!r}")
        return value


# ======================================================================
# Config
# ======================================================================

class ConfigPayload(_RequestModel):
    """Partial update for ``POST /api/config``.

    Every field is optional; ``model_dump(exclude_unset=True)`` sends only
    the keys the client actually provided, preserving PATCH semantics.
    """
    node_name: NodeName | None = None
    receive_folder: str | None = Field(default=None, max_length=4096)
    server_port: PortNumber | None = None
    sync_interval: int | None = Field(default=None, ge=1, le=3600)
    conflict_resolution: ConflictStrategy | None = None
    version_retention_days: int | None = Field(default=None, ge=1, le=3650)
    trash_retention_days: int | None = Field(default=None, ge=1, le=3650)
    peer_mtime_skew_seconds: int | None = Field(default=None, ge=1, le=86400)
    max_workers: int | None = Field(default=None, ge=1, le=32)
    max_file_size: int | None = Field(default=None, ge=1024 * 1024, le=1024 ** 4)
    chunk_size: int | None = Field(default=None, ge=64 * 1024, le=64 * 1024 * 1024)
    ignore_patterns: list[str] | None = Field(default=None, max_length=500)

    dark_mode: bool | None = None
    watch_subdirectories: bool | None = None
    detect_moves: bool | None = None
    enable_compression: bool | None = None
    enable_encryption: bool | None = None
    allow_registration: bool | None = None
    auto_open_browser: bool | None = None
    block_executable_extensions: bool | None = None
    trusted_hosts: list[str] | None = Field(default=None, max_length=100)
    trusted_proxies: list[str] | None = Field(default=None, max_length=100)

    group_key: GroupKey | None = None

    @field_validator("receive_folder")
    @classmethod
    def _check_receive_folder(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("receive_folder cannot be empty")
        if not _is_safe_absolute_path(cleaned):
            raise ValueError("receive_folder must be an absolute path without '..'")
        normalized = os.path.normpath(cleaned)
        parts = [p for p in normalized.replace("\\", "/").split("/") if p]
        if parts and parts[0].lower() in _WINDOWS_RESERVED:
            raise ValueError("receive_folder points to a reserved system path")
        return normalized

    @field_validator("ignore_patterns")
    @classmethod
    def _clean_patterns(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [str(p).strip() for p in value if str(p).strip()]
        return cleaned[:500]

    @field_validator("trusted_hosts")
    @classmethod
    def _clean_trusted_hosts(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return [
            host for item in value
            if (host := item.strip()) and host != "*"
        ]

    @field_validator("trusted_proxies")
    @classmethod
    def _clean_trusted_proxies(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        networks = []
        for item in value:
            text = item.strip()
            if text:
                networks.append(str(ipaddress.ip_network(text, strict=False)))
        return list(dict.fromkeys(networks))


# ======================================================================
# Peers / P2P
# ======================================================================

class PeerInfo(_ResponseModel):
    """Snapshot of a known peer."""
    id: HexId
    name: str = Field(..., max_length=64)
    ip: str = Field(..., max_length=64)
    port: PortNumber
    status: PeerStatus
    via: str | None = None
    services: list[str] = Field(default_factory=list)
    shares: list[ShareId] = Field(default_factory=list)
    last_seen: float = Field(default=0.0, ge=0)


class AddPeerRequest(_RequestModel):
    """Payload for ``POST /api/peers``."""
    address: Address = Field(..., examples=["192.168.1.10:8080"])

    # [FIX-MED-8] الـ pattern يقبل ``99999`` كمنفذ — نتحقّق من النطاق.
    @field_validator("address")
    @classmethod
    def _check_port_range(cls, value: str) -> str:
        return _validate_address(value)


class SendToPeerRequest(_RequestModel):
    """Payload for ``POST /api/peers/{id}/send``."""
    path: RelPath

    @field_validator("path")
    @classmethod
    def _no_traversal(cls, value: str) -> str:
        if _looks_like_path_traversal(value):
            raise ValueError("Path escapes its share root")
        return value


# ======================================================================
# Conflicts / Versions
# ======================================================================

class ResolveConflictRequest(_RequestModel):
    """Payload for ``POST /api/conflicts/{id}/resolve``."""
    action: Literal["accept", "swap"] = "accept"


# ======================================================================
# Cloud
# ======================================================================

class CloudConnectRequest(_RequestModel):
    """Payload for ``POST /api/cloud/connect``."""
    service: CloudService
    credentials: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _require_credentials(self) -> "CloudConnectRequest":
        if self.service == "folder" and not self.credentials.get("path"):
            raise ValueError("'folder' service requires a 'path' credential")
        if self.service == "webdav" and not self.credentials.get("url"):
            raise ValueError("'webdav' service requires a 'url' credential")
        if self.service in {"dropbox", "google_drive", "onedrive"} \
                and not self.credentials.get("token"):
            raise ValueError(f"'{self.service}' service requires a 'token' credential")
        return self


class CloudDisconnectRequest(_RequestModel):
    """Payload for ``POST /api/cloud/disconnect``."""
    service: CloudService


class CloudUploadRequest(_RequestModel):
    """Payload for ``POST /api/cloud/upload``."""
    service: CloudService
    share: ShareId = "received"
    path: RelPath
    cloud_path: str | None = Field(default=None, max_length=1024)

    @field_validator("path")
    @classmethod
    def _no_traversal(cls, value: str) -> str:
        if _looks_like_path_traversal(value):
            raise ValueError("Path escapes its share root")
        return value


class CloudBackupRequest(_RequestModel):
    """Payload for ``POST /api/cloud/backup``."""
    service: CloudService
    share: ShareId = "received"
    path: str = Field(default="", max_length=1024)
    cloud_path: str = Field(default="backup", max_length=1024)
    schedule: BackupSchedule = "daily"


# ======================================================================
# Webhooks
# ======================================================================

class WebhookCreate(_RequestModel):
    """Payload for ``POST /api/webhooks``."""
    url: HttpUrl
    events: str = Field(default="*", max_length=512,
                        description="Comma-separated event names, or '*' for all")
    secret: str | None = Field(default=None, min_length=16, max_length=512)


# ======================================================================
# Public API
# ======================================================================

__all__ = [
    # primitives
    "ConflictStrategy", "Role", "CloudService", "BackupSchedule",
    "FileType", "PeerStatus",
    # envelopes
    "Message", "ErrorBody",
    # auth
    "LoginRequest", "LoginResponse", "ChangePasswordRequest",
    "UserPublic", "CreateUserRequest", "UpdateUserRequest",
    # files
    "FileEntry", "FileListResponse", "ShareInfo", "ZipRequest",
    # config
    "ConfigPayload",
    # peers
    "PeerInfo", "AddPeerRequest", "SendToPeerRequest",
    # conflicts
    "ResolveConflictRequest",
    # cloud
    "CloudConnectRequest", "CloudDisconnectRequest",
    "CloudUploadRequest", "CloudBackupRequest",
    # webhooks
    "WebhookCreate",
]