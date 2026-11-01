#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""الإعدادات، قاعدة البيانات، وإدارة الأمان."""
from __future__ import annotations

import base64
import contextlib
import functools
import hashlib
import hmac
import ipaddress
import os
import platform
import re
import secrets
import sqlite3
import struct
import threading
import time
import uuid
from pathlib import Path

from . import i18n
from .utils import (atomic_write_bytes, atomic_write_json, read_json,
                    default_data_dir, log)

try:
    from cryptography.fernet import Fernet, InvalidToken
    HAS_CRYPTO = True
except ImportError:
    Fernet = None
    InvalidToken = Exception
    HAS_CRYPTO = False


CONFLICT_STRATEGIES = ("newer", "older", "larger", "source", "target", "ask")

MIN_GROUP_KEY_LEN = 24

# ------------------------------------------------------------------
# PBKDF2 iteration counts — single source of truth.
#
# Every KDF in the codebase MUST read its iteration count from this
# table.  Never hard-code a new value at a call site: add an entry here
# instead, so an auditor can review all KDF parameters in one place.
# ------------------------------------------------------------------
KDF_ITERATIONS = {
    # User passwords (SecurityManager._hash_password).
    "users":          240_000,
    # Fernet master key (SecurityManager.unlock).
    "master":         390_000,
    # Group key at rest (Config._derive_config_key).
    "config":         480_000,
    # P2P request-signing HMAC (network.derive_hmac_key / Config.hmac_key).
    "hmac_v4":        200_000,
    # Frame-codec transport encryption (network.derive_transport_key).
    "transport_v3":   150_000,
    # Cloud credentials at rest (CloudIntegration._creds_key).
    "cloud_creds_v2": 120_000,
}

# Salt prefixes — pinned here so an accidental edit shows up in one diff.
# All P2P code uses the v4 salts; the transport codec keeps v3 for
# session continuity.  Bump the version suffix when you rotate the salt.
_SALT_HMAC_V4      = b"ss-group-hmac-v4"
_SALT_TRANSPORT_V3 = b"ss-transport-kdf-v3"
_SALT_CONFIG_V4    = b"ss-config-kdf-v4"
_SALT_CLOUD_V2     = b"ss-cloud-creds-v2"


@functools.lru_cache(maxsize=16)
def derive_hmac_key(group_key: str) -> bytes:
    """Derive the P2P request-signing HMAC key from the group key.

    Shared by :func:`network.sign_request` and :meth:`Config.hmac_key`
    so the two can never drift apart again (previously v3/100k vs v4/200k).
    """
    return hashlib.pbkdf2_hmac(
        "sha256", group_key.encode("utf-8"),
        _SALT_HMAC_V4, KDF_ITERATIONS["hmac_v4"], 32,
    )


@functools.lru_cache(maxsize=16)
def derive_transport_key(group_key: str) -> bytes:
    """Derive the frame-codec (transport) key from the group key."""
    return hashlib.pbkdf2_hmac(
        "sha256", group_key.encode("utf-8"),
        _SALT_TRANSPORT_V3, KDF_ITERATIONS["transport_v3"], 32,
    )


@functools.lru_cache(maxsize=16)
def derive_cloud_creds_key(group_key: str) -> bytes:
    """Derive the at-rest key protecting cloud-provider credentials."""
    return hashlib.pbkdf2_hmac(
        "sha256", group_key.encode("utf-8"),
        _SALT_CLOUD_V2, KDF_ITERATIONS["cloud_creds_v2"], 32,
    )


class GroupKeyError(RuntimeError):
    """تعذّر فك تشفير مفتاح المجموعة المخزَّن (كلمة مرور رئيسية خاطئة أو سر جهاز مفقود).

    [FIX] كان ``Config.load()`` يتجاهل الخطأ ويولّد مفتاحًا جديدًا ثم يحفظه فوق
    القديم، فيُفصل الجهاز عن مجموعة المزامنة نهائيًا بسبب خطأ كتابة واحد.
    الآن نتوقف برسالة واضحة دون لمس الملف.
    """


_FORBIDDEN_RECEIVE_ROOTS = {
    "etc", "usr", "bin", "sbin", "lib", "lib64", "boot",
    "sys", "proc", "dev", "root", "System", "Library",
}
_FORBIDDEN_WINDOWS_ROOTS = {"windows", "program files", "program files (x86)",
                            "programdata"}


def _under_home(p: str) -> bool:
    home = os.path.realpath(os.path.expanduser("~"))
    return home not in ("", os.sep) and (p == home or p.startswith(home + os.sep))


def _machine_secret_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        root = Path(base)
    elif platform.system() == "Windows":
        root = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif platform.system() == "Darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path.home() / ".config"
    d = root / "superior-sync"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d / "machine_secret"


def validate_receive_folder(raw) -> str:
    p = os.path.realpath(os.path.abspath(os.path.expanduser(str(raw))))
    if not p or p == os.sep:
        raise ValueError("unsafe path")
    if os.name == "nt":
        drive, tail = os.path.splitdrive(p)
        if not tail.strip("\\/"):
            raise ValueError("unsafe path")
        parts = [x.lower() for x in tail.replace("\\", "/").split("/") if x]
        if parts and parts[0] in _FORBIDDEN_WINDOWS_ROOTS:
            raise ValueError("unsafe path")
    else:
        parts = [x for x in p.split(os.sep) if x]
        # [FIX] /root مسموح إن كان هو الـ home الفعلي (حاويات Docker تعمل كـ root)،
        # و /var/<شيء> مسموح (NAS مثل /var/services) ويُمنع /var نفسه فقط.
        if parts and parts[0] in _FORBIDDEN_RECEIVE_ROOTS and not _under_home(p):
            raise ValueError("unsafe path")
        if parts == ["var"]:
            raise ValueError("unsafe path")
    return p


def validate_sync_folder(raw, data_dir) -> str:
    """تحقّق من مجلد مزامنة: نفس قواعد مجلد الاستقبال + لا يتقاطع مع data_dir.

    [FIX] ``add_sync_folder`` لم يكن يتحقق من شيء؛ كان يمكن إضافة ``/etc`` أو مجلد
    يحتوي data_dir (فتُشارك قاعدة البيانات وملفات الإعداد مع النظراء).
    """
    p = validate_receive_folder(raw)
    data = os.path.realpath(str(data_dir))
    if p == data or p.startswith(data + os.sep) or data.startswith(p + os.sep):
        raise ValueError("overlaps data dir")
    return p


def _normalise_trusted_proxies(values):
    if not isinstance(values, list):
        raise ValueError("trusted_proxies must be a list")
    networks = []
    for value in values:
        text = str(value).strip()
        if text:
            networks.append(str(ipaddress.ip_network(text, strict=False)))
    return list(dict.fromkeys(networks))


class Config:
    PERSISTED = {
        "receive_folder": None, "server_port": 8080, "sync_folders": [],
        "dark_mode": False, "sync_interval": 10, "watch_subdirectories": True,
        "detect_moves": True, "conflict_resolution": "newer", "max_workers": 8,
        "chunk_size": 4 * 1024 * 1024, "max_file_size": 10 * 1024 ** 3,
        "enable_compression": True, "enable_encryption": True,
        "node_id": None, "node_name": None, "group_key": None,
        "allow_registration": False, "auto_open_browser": True,
        "version_retention_days": 30, "trash_retention_days": 30,
        "max_versions_per_file": 20, "ignore_patterns": [], "manual_peers": [],
        "block_executable_extensions": True,
        "peer_mtime_skew_seconds": 300,
        "trusted_hosts": [],
        "trusted_proxies": [],
    }

    def __init__(self, data_dir=None, master_password=None):
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.data_dir / "config.json"
        self.lock = threading.RLock()
        self.server_host = "127.0.0.1"
        self.active_port = None
        self._tls_active = False
        self._shares_cache = None
        self._shares_lock = threading.Lock()
        self._hmac_key_cache = None
        self._group_key_cache = None
        self._master_password = master_password or os.environ.get("SS_MASTER_PASSWORD")
        for k, v in self.PERSISTED.items():
            setattr(self, k, list(v) if isinstance(v, list) else v)
        self.load()

    # ------------------------------------------------------------------
    def _derive_config_key(self):
        salt_file = self.data_dir / ".config_salt"
        if not salt_file.exists():
            with contextlib.suppress(OSError):
                atomic_write_bytes(salt_file, os.urandom(32), 0o600)
        try:
            salt = salt_file.read_bytes()
        except OSError:
            salt = b"ss-fallback-salt-v3"
        if self._master_password:
            seed = self._master_password.encode("utf-8")
        else:
            secret_file = _machine_secret_path()
            if not secret_file.exists():
                with contextlib.suppress(OSError):
                    atomic_write_bytes(secret_file, os.urandom(32), 0o600)
            try:
                seed = secret_file.read_bytes()
            except OSError:
                seed = b"ss-fallback-seed-v3"
                log.warning(
                    "لا يوجد master password ولا ملف سرّي للجهاز — التشفير ضعيف")
        return hashlib.pbkdf2_hmac(
            "sha256", seed, salt + _SALT_CONFIG_V4,
            KDF_ITERATIONS["config"], 32)

    def hmac_key(self):
        """Legacy accessor — now delegates to the shared derivation.

        Previously this used a v3 salt with 100k iterations while
        ``network.sign_request`` used a v4 salt with 200k.  Both call
        sites now share :func:`derive_hmac_key`, so external callers
        agree with the P2P protocol.
        """
        with self.lock:
            gk = self.group_key or "uninitialized"
            if (self._hmac_key_cache is not None
                    and self._group_key_cache == gk):
                return self._hmac_key_cache
            key = derive_hmac_key(gk)
            self._hmac_key_cache = key
            self._group_key_cache = gk
            return key

    # ------------------------------------------------------------------
    def _encrypt_group_key(self, plaintext):
        if HAS_CRYPTO:
            try:
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                key = self._derive_config_key()
                nonce = os.urandom(12)
                ct = AESGCM(key).encrypt(
                    nonce, plaintext.encode("utf-8"),
                    b"ss-group-key-v4-aad")
                return {"v": 4, "algo": "aesgcm",
                        "nonce": base64.b64encode(nonce).decode(),
                        "ct": base64.b64encode(ct).decode()}
            except Exception as e:
                log.warning("AESGCM فشل (%s) — سأستخدم HMAC-CTR", e)
        key = self._derive_config_key()
        enc_key = hmac.new(key, b"enc", hashlib.sha256).digest()
        mac_key = hmac.new(key, b"mac", hashlib.sha256).digest()
        nonce = os.urandom(16)
        pt = plaintext.encode("utf-8")
        ks = bytearray()
        ctr = 0
        while len(ks) < len(pt):
            ks.extend(hmac.new(
                enc_key,
                b"aad-v4" + nonce + struct.pack(">Q", ctr),
                hashlib.sha256).digest())
            ctr += 1
        ct = bytes(a ^ b for a, b in zip(pt, ks))
        mac = hmac.new(mac_key,
                       b"v4" + b"aad-v4" + nonce + ct,
                       hashlib.sha256).hexdigest()
        return {"v": 4, "algo": "hmac-ctr",
                "nonce": base64.b64encode(nonce).decode(),
                "ct": base64.b64encode(ct).decode(),
                "mac": mac}

    def _decrypt_group_key(self, blob):
        version = blob.get("v", 1)
        if version >= 4 and blob.get("algo") == "aesgcm":
            if not HAS_CRYPTO:
                raise ValueError("AESGCM مطلوب لكن cryptography غير مثبتة")
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = self._derive_config_key()
            nonce = base64.b64decode(blob["nonce"])
            ct = base64.b64decode(blob["ct"])
            try:
                return AESGCM(key).decrypt(
                    nonce, ct, b"ss-group-key-v4-aad").decode("utf-8")
            except Exception as e:
                raise ValueError(f"AESGCM decrypt failed: {e}") from e
        if version >= 4 and blob.get("algo") == "hmac-ctr":
            key = self._derive_config_key()
            enc_key = hmac.new(key, b"enc", hashlib.sha256).digest()
            mac_key = hmac.new(key, b"mac", hashlib.sha256).digest()
            nonce = base64.b64decode(blob["nonce"])
            ct = base64.b64decode(blob["ct"])
            expected = hmac.new(mac_key,
                                b"v4" + b"aad-v4" + nonce + ct,
                                hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, blob["mac"]):
                raise ValueError("MAC verification failed")
            ks = bytearray()
            ctr = 0
            while len(ks) < len(ct):
                ks.extend(hmac.new(
                    enc_key,
                    b"aad-v4" + nonce + struct.pack(">Q", ctr),
                    hashlib.sha256).digest())
                ctr += 1
            return bytes(a ^ b for a, b in zip(
                ct, ks[:len(ct)])).decode("utf-8")
        if version >= 3 and blob.get("algo") == "aesgcm":
            if not HAS_CRYPTO:
                raise ValueError("AESGCM مطلوب لكن cryptography غير مثبتة")
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            key = self._derive_config_key()
            nonce = base64.b64decode(blob["nonce"])
            ct = base64.b64decode(blob["ct"])
            return AESGCM(key).decrypt(
                nonce, ct, b"ss-group-key-v3-aad").decode("utf-8")
        if version >= 3 and blob.get("algo") == "hmac-ctr":
            key = self._derive_config_key()
            enc_key = hmac.new(key, b"enc", hashlib.sha256).digest()
            mac_key = hmac.new(key, b"mac", hashlib.sha256).digest()
            nonce = base64.b64decode(blob["nonce"])
            ct = base64.b64decode(blob["ct"])
            expected = hmac.new(mac_key,
                                b"v3" + b"aad-v3" + nonce + ct,
                                hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, blob["mac"]):
                raise ValueError("MAC verification failed")
            ks = bytearray()
            ctr = 0
            while len(ks) < len(ct):
                ks.extend(hmac.new(
                    enc_key,
                    b"aad-v3" + nonce + struct.pack(">Q", ctr),
                    hashlib.sha256).digest())
                ctr += 1
            return bytes(a ^ b for a, b in zip(
                ct, ks[:len(ct)])).decode("utf-8")
        raise ValueError(
            "صيغة تشفير قديمة غير مدعومة — أعد تعيين مفتاح المجموعة")

    # ------------------------------------------------------------------
    def load(self):
        data = read_json(self.config_file, {}) or {}
        migrated = False
        with self.lock:
            for k, default in self.PERSISTED.items():
                if k in data and data[k] is not None:
                    v = data[k]
                    if isinstance(default, bool):
                        v = bool(v)
                    elif isinstance(default, int) and not isinstance(default, bool):
                        try:
                            v = int(v)
                        except (TypeError, ValueError):
                            v = default
                    setattr(self, k, v)
            if "group_key_enc" in data and data["group_key_enc"]:
                try:
                    self.group_key = self._decrypt_group_key(
                        data["group_key_enc"])
                    if data["group_key_enc"].get("v", 1) < 4:
                        migrated = True
                except Exception as e:  # ValueError/KeyError/InvalidTag...
                    log.error("Failed to decrypt group key: %s", e)
                    raise GroupKeyError(
                        "تعذّر فك تشفير مفتاح المجموعة. تحقّق من كلمة المرور الرئيسية "
                        "(--master-password أو SS_MASTER_PASSWORD) ومن أن ملف السر المرتبط بالجهاز "
                        "(machine_secret) لم يُحذف. لم يتم تعديل أي ملف."
                    ) from e
            elif data.get("group_key"):
                self.group_key = data["group_key"]
                migrated = True
            if self.conflict_resolution not in CONFLICT_STRATEGIES:
                self.conflict_resolution = "newer"
            try:
                self.trusted_proxies = _normalise_trusted_proxies(
                    self.trusted_proxies
                )
            except ValueError as exc:
                log.warning("إعداد trusted_proxies غير صالح؛ سيتم تجاهله: %s", exc)
                self.trusted_proxies = []
                migrated = True
            if self.enable_encryption and not HAS_CRYPTO:
                log.warning("⚠️ enable_encryption مطلوب لكن cryptography غير مثبتة")
                self.enable_encryption = False
                migrated = True
            changed = migrated
            if not self.node_id:
                self.node_id = uuid.uuid4().hex[:16]
                changed = True
            if not self.node_name:
                self.node_name = platform.node() or "device"
                changed = True
            if not self.group_key:
                self.group_key = secrets.token_urlsafe(32)
                changed = True
            if not self.receive_folder:
                self.receive_folder = str(Path.home() / "SyncedFiles")
                changed = True
            try:
                self.receive_folder = validate_receive_folder(self.receive_folder)
            except ValueError:
                self.receive_folder = str(Path.home() / "SyncedFiles")
                changed = True
            os.makedirs(self.receive_folder, exist_ok=True)
            self.sync_folders = [os.path.abspath(p) for p in self.sync_folders]
            if changed:
                self.save()
            self.invalidate_shares()

    def save(self):
        with self.lock:
            data = {k: getattr(self, k) for k in self.PERSISTED
                    if k != "group_key"}
            if self.group_key:
                data["group_key_enc"] = self._encrypt_group_key(
                    self.group_key)
            try:
                atomic_write_json(self.config_file, data, mode=0o600)
            except OSError as e:
                log.error("فشل حفظ الإعدادات: %s", e)

    def public_dict(self):
        with self.lock:
            d = {k: getattr(self, k) for k in self.PERSISTED
                 if k != "group_key"}
            d["server_port"] = self.server_port
            d["active_port"] = self.active_port
            d["server_host"] = self.server_host
            d["node_name"] = self.node_name
            d["crypto_available"] = HAS_CRYPTO
            d["tls_active"] = self._tls_active
            return d

    def update(self, data):
        """يطبّق التحديث بشكل ذري: عند أي خطأ تحقّق تُسترجع كل القيم السابقة.

        [FIX] كانت الحقول تُطبَّق واحدًا بعد الآخر، فإذا فشل حقل متأخر بقيت الحقول
        السابقة معدّلة في الذاكرة (وتُحفظ لاحقًا مع أي save()).
        """
        import copy
        with self.lock:
            snapshot = {k: copy.deepcopy(getattr(self, k, None)) for k in self.PERSISTED}
            result = self._update_locked(data, snapshot)
            if not result[0]:
                for k, v in snapshot.items():
                    setattr(self, k, v)
                self._hmac_key_cache = None
                self._group_key_cache = None
                self.invalidate_shares()
            return result

    def _update_locked(self, data, snapshot=None):
        restart = False
        with self.lock:
            try:
                if "server_port" in data:
                    p = int(data["server_port"])
                    if not 1024 <= p <= 65535:
                        return False, i18n.t("error.port_range"), False
                    restart = restart or p != self.server_port
                    self.server_port = p
                if "sync_interval" in data:
                    v = int(data["sync_interval"])
                    if not 1 <= v <= 3600:
                        return False, i18n.t("error.interval_range"), False
                    self.sync_interval = v
                if "conflict_resolution" in data:
                    if data["conflict_resolution"] not in CONFLICT_STRATEGIES:
                        return False, i18n.t("error.unknown_strategy"), False
                    self.conflict_resolution = data["conflict_resolution"]
                for k in ("dark_mode", "watch_subdirectories", "detect_moves",
                          "enable_compression", "enable_encryption",
                          "allow_registration", "auto_open_browser",
                          "block_executable_extensions"):
                    if k in data:
                        if k == "enable_encryption" and data[k] and not HAS_CRYPTO:
                            return False, i18n.t("error.crypto_required"), False
                        setattr(self, k, bool(data[k]))
                for k in ("version_retention_days", "trash_retention_days",
                          "max_versions_per_file", "peer_mtime_skew_seconds"):
                    if k in data:
                        v = int(data[k])
                        if v < 1:
                            return False, i18n.t("error.invalid_value", detail=k), False
                        setattr(self, k, v)
                if "max_file_size" in data:
                    v = int(data["max_file_size"])
                    if not 1024 * 1024 <= v <= 1024 ** 4:
                        return False, i18n.t("error.out_of_range",
                                             name="max_file_size",
                                             lo="1MB", hi="1TB"), False
                    self.max_file_size = v
                if "chunk_size" in data:
                    v = int(data["chunk_size"])
                    if not 64 * 1024 <= v <= 64 * 1024 * 1024:
                        return False, i18n.t("error.out_of_range",
                                             name="chunk_size",
                                             lo="64KB", hi="64MB"), False
                    self.chunk_size = v
                if "max_workers" in data:
                    v = int(data["max_workers"])
                    if not 1 <= v <= 32:
                        return False, i18n.t("error.out_of_range",
                                             name="max_workers", lo=1, hi=32), False
                    self.max_workers = v
                if "node_name" in data and str(data["node_name"]).strip():
                    self.node_name = str(data["node_name"]).strip()[:64]
                if "ignore_patterns" in data and isinstance(
                        data["ignore_patterns"], list):
                    self.ignore_patterns = [str(x) for x in data["ignore_patterns"]
                                            if str(x).strip()]
                if "trusted_hosts" in data and isinstance(
                        data["trusted_hosts"], list):
                    self.trusted_hosts = [
                        str(x).strip() for x in data["trusted_hosts"]
                        if str(x).strip() and str(x).strip() != "*"]
                if "trusted_proxies" in data:
                    self.trusted_proxies = _normalise_trusted_proxies(
                        data["trusted_proxies"]
                    )
                if "receive_folder" in data:
                    try:
                        rf = validate_receive_folder(data["receive_folder"])
                    except ValueError:
                        return False, i18n.t("error.path_unsafe"), False
                    os.makedirs(rf, exist_ok=True)
                    self.receive_folder = rf
                if "group_key" in data:
                    k = str(data["group_key"]).strip()
                    if len(k) < MIN_GROUP_KEY_LEN:
                        return False, i18n.t("config.key_short", n=MIN_GROUP_KEY_LEN), False
                    self.group_key = k
                    self._hmac_key_cache = None
                    self._group_key_cache = None
            except (TypeError, ValueError, OSError) as e:
                return False, i18n.t("error.invalid_value", detail=e), False
            changed = snapshot is None or any(
                getattr(self, key, None) != value
                for key, value in snapshot.items()
            )
            if changed:
                self.invalidate_shares()
                self.save()
        return True, None, restart

    def shares(self):
        with self._shares_lock:
            if self._shares_cache is not None:
                return dict(self._shares_cache)
        out = {"received": os.path.abspath(self.receive_folder)}
        with self.lock:
            for p in self.sync_folders:
                sid = re.sub(r"[^\w\-. ]", "_",
                             os.path.basename(p.rstrip("/\\")) or "root")
                base, n = sid, 2
                while sid in out:
                    sid = f"{base}-{n}"
                    n += 1
                out[sid] = p
        with self._shares_lock:
            self._shares_cache = dict(out)
        return dict(out)

    def invalidate_shares(self):
        with self._shares_lock:
            self._shares_cache = None


# ==================================================================
# قاعدة البيانات
# ==================================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  share TEXT NOT NULL, path TEXT NOT NULL, size INTEGER, mtime_ns INTEGER, hash TEXT,
  deleted INTEGER DEFAULT 0, mod_time REAL,
  oversized INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(share, path));
CREATE TABLE IF NOT EXISTS peer_base(
  peer TEXT NOT NULL, share TEXT NOT NULL, path TEXT NOT NULL, hash TEXT,
  PRIMARY KEY(peer, share, path));
CREATE TABLE IF NOT EXISTS conflicts(
  id TEXT PRIMARY KEY, share TEXT, path TEXT, peer TEXT, strategy TEXT, winner TEXT,
  local_hash TEXT, remote_hash TEXT, detected_at REAL, resolved INTEGER DEFAULT 0,
  resolved_at REAL, resolution TEXT, needs_review INTEGER DEFAULT 0, copy_path TEXT, info TEXT);
CREATE TABLE IF NOT EXISTS versions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT, version_path TEXT, created_at REAL,
  size INTEGER, hash TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS idx_versions_path ON versions(file_path);
CREATE TABLE IF NOT EXISTS trash(
  id INTEGER PRIMARY KEY AUTOINCREMENT, original_path TEXT, trash_path TEXT, deleted_at REAL,
  reason TEXT, size INTEGER);
CREATE TABLE IF NOT EXISTS sync_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, share TEXT, path TEXT, peer TEXT,
  action TEXT, size INTEGER, ok INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS webhooks(
  id TEXT PRIMARY KEY, url TEXT, events TEXT, secret TEXT, enabled INTEGER DEFAULT 1,
  created_at REAL);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, actor TEXT, action TEXT,
  target TEXT, ip TEXT, result TEXT, detail TEXT);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


class Database:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False,
                                    isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(SCHEMA)
            columns = {
                row["name"] for row in self.conn.execute("PRAGMA table_info(files)")
            }
            if "oversized" not in columns:
                self.conn.execute(
                    "ALTER TABLE files ADD COLUMN oversized INTEGER NOT NULL DEFAULT 0"
                )

    def query(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in
                    self.conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            return cur.lastrowid

    def many(self, sql, seq):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.executemany(sql, seq)
                self.conn.execute("COMMIT")
            except BaseException:
                with contextlib.suppress(sqlite3.Error):
                    self.conn.execute("ROLLBACK")
                raise

    def close(self):
        with self.lock:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass


# ==================================================================
# الأمان
# ==================================================================
class SecurityError(Exception):
    pass


ROLE_PERMISSIONS = {
    "admin": ["read", "write", "delete", "share", "manage_users",
              "view_logs", "configure"],
    "user": ["read", "write", "share"],
    "guest": ["read"],
}


class SecurityManager:
    # Re-exported from KDF_ITERATIONS so existing introspection
    # (``SecurityManager.PBKDF2_ITERATIONS``) keeps working.
    PBKDF2_ITERATIONS = KDF_ITERATIONS["users"]
    MAGIC = b"SSENC2\n"
    _MAX_FAILS = 10_000
    _SESSION_MAX_TOTAL = 5_000
    _SESSION_MAX_PER_USER = 20

    def __init__(self, data_dir, master_password=None):
        self.dir = Path(data_dir) / "security"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.users_db = self.dir / "users.json"
        self.sessions_db = self.dir / "sessions.json"
        self.lock = threading.RLock()
        self.users = read_json(self.users_db, {}) or {}
        self.encryption_enabled = HAS_CRYPTO
        self.master_key = None
        self._tokens = {}
        self._fails = {}
        self._cleanup_stop = threading.Event()
        self._load_sessions()
        salt_file = self.dir / "kdf_salt"
        if not salt_file.exists():
            atomic_write_bytes(salt_file, os.urandom(16), 0o600)
        self._salt = salt_file.read_bytes()
        self._dummy_pw = self._hash_password("dummy", b"0" * 16)
        if master_password:
            self.unlock(master_password)
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="sessions-cleanup")
        self._cleanup_thread.start()

    # ------------------------------------------------------------------
    def _load_sessions(self):
        data = read_json(self.sessions_db, {}) or {}
        now = time.time()
        clean = {}
        if isinstance(data, dict):
            for k, v in data.items():
                if (isinstance(v, dict)
                        and isinstance(v.get("user"), str)
                        and float(v.get("expires", 0)) > now):
                    clean[k] = {
                        "user": v["user"],
                        "expires": float(v["expires"]),
                        "ttl": float(v.get("ttl", 86400)),
                        "absolute_expires": float(
                            v.get("absolute_expires", v["expires"])),
                    }
        self._tokens = clean

    def _save_sessions(self):
        with self.lock:
            atomic_write_json(self.sessions_db, self._tokens, mode=0o600)

    def _cleanup_loop(self):
        while not self._cleanup_stop.wait(300):
            with self.lock:
                now = time.time()
                changed = False
                before = len(self._tokens)
                self._tokens = {
                    k: v for k, v in self._tokens.items()
                    if v["expires"] > now and v.get("absolute_expires", 0) > now
                }
                if len(self._tokens) != before:
                    changed = True
                if len(self._tokens) > self._SESSION_MAX_TOTAL:
                    ordered = sorted(
                        self._tokens.items(),
                        key=lambda x: x[1]["expires"], reverse=True)
                    self._tokens = dict(ordered[: self._SESSION_MAX_TOTAL])
                    changed = True
            if changed:
                with contextlib.suppress(OSError):
                    self._save_sessions()

    def close(self):
        self._cleanup_stop.set()
        if self._cleanup_thread is not threading.current_thread():
            self._cleanup_thread.join()

    # ------------------------------------------------------------------
    def _save_users(self):
        with self.lock:
            atomic_write_json(self.users_db, self.users, mode=0o600)

    def _hash_password(self, password, salt=None, iterations=None):
        salt = salt or os.urandom(16)
        iterations = iterations or KDF_ITERATIONS["users"]
        h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                salt, iterations)
        return {"algo": "pbkdf2_sha256", "iterations": iterations,
                "salt": salt.hex(), "hash": h.hex()}

    def create_user(self, username, password, role="user"):
        username = (username or "").strip()
        if (not re.fullmatch(r"[\w.\-@]{2,64}", username)
                or len(password or "") < 8):
            return False
        if role not in ROLE_PERMISSIONS:
            role = "user"
        with self.lock:
            if username in self.users:
                return False
            self.users[username] = {
                "pw": self._hash_password(password), "role": role,
                "created_at": time.time(),
                "permissions": self._get_default_permissions(role)}
            self._save_users()
        return True

    def authenticate_user(self, username, password, ip="-"):
        """Validate credentials.

        Brute-force throttling is keyed by *IP only*, so an attacker cannot
        bypass the lockout by rotating usernames from the same address.
        """
        key = ip or "-"
        now = time.time()

        with self.lock:
            if len(self._fails) > self._MAX_FAILS:
                self._fails = {k: v for k, v in self._fails.items()
                               if v[1] > now}
                if len(self._fails) > self._MAX_FAILS:
                    ordered = sorted(
                        self._fails.items(),
                        key=lambda x: x[1][1], reverse=True,
                    )[: self._MAX_FAILS]
                    self._fails = dict(ordered)
            f = self._fails.get(key)
            if f and f[1] > now:
                return False

        user = self.users.get(username) if username else None
        pw = user["pw"] if user else self._dummy_pw
        calc = hashlib.pbkdf2_hmac(
            "sha256", (password or "").encode("utf-8"),
            bytes.fromhex(pw["salt"]), pw["iterations"],
        ).hex()
        ok = bool(user) and hmac.compare_digest(calc, pw["hash"])

        with self.lock:
            if ok:
                self._fails.pop(key, None)
                return True
            f = self._fails.get(key)
            cnt = (f[0] if f else 0) + 1
            if cnt >= 5:
                levels = [60, 300, 900, 3600]
                lock_seconds = levels[min(cnt - 5, len(levels) - 1)]
                self._fails[key] = [cnt, now + lock_seconds]
            else:
                self._fails[key] = [cnt, 0]
        return False

    def set_password(self, username, password):
        with self.lock:
            if username not in self.users or len(password or "") < 8:
                return False
            self.users[username]["pw"] = self._hash_password(password)
            self._save_users()
        self.revoke_user_tokens(username)
        return True

    def delete_user(self, username):
        with self.lock:
            if username not in self.users:
                return False
            # [FIX] الحارس داخل القفل: كان الفحص في الـ router خارجه، فيمكن لطلبين
            # متزامنين حذف آخر أدمنين معًا.
            if self.users[username].get("role") == "admin" and sum(
                    1 for u in self.users.values() if u.get("role") == "admin") <= 1:
                return False
            del self.users[username]
            self._save_users()
        self.revoke_user_tokens(username)
        return True

    def ensure_admin(self):
        with self.lock:
            if any(u.get("role") == "admin"
                   for u in self.users.values()):
                return None
            pw = secrets.token_urlsafe(18)
            self.create_user("admin", pw, "admin")
        return pw

    @staticmethod
    def _get_default_permissions(role):
        return list(ROLE_PERMISSIONS.get(role, ["read"]))

    def check_permission(self, username, permission):
        u = self.users.get(username)
        return bool(u) and permission in u.get("permissions", [])

    def get_user_role(self, username):
        u = self.users.get(username)
        return u.get("role", "guest") if u else None

    def public_users(self):
        return [{"username": n, "role": u.get("role"),
                 "created_at": u.get("created_at"),
                 "permissions": u.get("permissions", [])}
                for n, u in self.users.items()]

    # ------------------------------------------------------------------
    def generate_session_token(self, user_id, expires_hours=24):
        token = secrets.token_urlsafe(32)
        with self.lock:
            now = time.time()
            self._tokens = {k: v for k, v in self._tokens.items()
                            if v["expires"] > now}
            per_user = [k for k, v in self._tokens.items()
                        if v["user"] == user_id]
            if len(per_user) >= self._SESSION_MAX_PER_USER:
                per_user.sort(key=lambda k: self._tokens[k]["expires"])
                for k in per_user[: len(per_user) - self._SESSION_MAX_PER_USER + 1]:
                    self._tokens.pop(k, None)
            # [FIX-MED-7] كان ``absolute_expires`` مثبّتاً على 24h حتى
            # عندما يُطلب TTL أقصر (مثلاً 1h)، مما يجعل السقف المطلق
            # غير متّسق مع النافذة المعلنة.  الآن السقف = max(ttl, 24h)
            # حتى لا يقطع جلسة مشروعة طويلة، ولا يمدّد جلسة قصيرة.
            ttl_seconds = max(1, int(expires_hours)) * 3600
            absolute = now + max(ttl_seconds, 24 * 3600)
            self._tokens[hashlib.sha256(token.encode()).hexdigest()] = {
                "user": user_id,
                "expires": now + ttl_seconds,
                "ttl": ttl_seconds,
                "absolute_expires": absolute,
            }
            self._save_sessions()
        return token

    def validate_token(self, token):
        if not token:
            return None
        k = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            t = self._tokens.get(k)
            now = time.time()
            if (not t or t["expires"] < now
                    or t.get("absolute_expires", 0) < now
                    or t["user"] not in self.users):
                self._tokens.pop(k, None)
                return None
            t["expires"] = now + t["ttl"]
            return t["user"]

    def revoke_token(self, token):
        with self.lock:
            key = hashlib.sha256((token or "").encode()).hexdigest()
            if self._tokens.pop(key, None) is not None:
                self._save_sessions()

    def revoke_user_tokens(self, username):
        with self.lock:
            before = len(self._tokens)
            self._tokens = {k: v for k, v in self._tokens.items()
                            if v["user"] != username}
            if len(self._tokens) != before:
                self._save_sessions()

    # ------------------------------------------------------------------
    def unlock(self, password):
        if not HAS_CRYPTO:
            return False
        key = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            self._salt, KDF_ITERATIONS["master"], 32)
        self.master_key = Fernet(base64.urlsafe_b64encode(key))
        return True

    def _need_key(self):
        if not HAS_CRYPTO:
            raise SecurityError("التشفير يتطلب: pip install cryptography")
        if not self.master_key:
            raise SecurityError("المفتاح الرئيسي غير مُفعّل")

    def encrypt_data(self, data):
        self._need_key()
        raw = data.encode("utf-8") if isinstance(data, str) else data
        return self.master_key.encrypt(raw).decode("ascii")

    def decrypt_data(self, token):
        self._need_key()
        try:
            return self.master_key.decrypt(
                token.encode("ascii")
                if isinstance(token, str) else token).decode("utf-8")
        except InvalidToken as e:
            raise SecurityError("كلمة المرور خاطئة أو البيانات تالفة") from e

    # ------------------------------------------------------------------
    def encrypt_file(self, src, dst=None, chunk=1 << 20):
        self._need_key()
        dst = dst or src + ".enc"
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            fo.write(self.MAGIC)
            seq = 0
            while True:
                b = fi.read(chunk)
                if not b:
                    break
                plain = struct.pack(">I", seq) + b
                tok = self.master_key.encrypt(plain)
                fo.write(struct.pack(">I", len(tok)) + tok)
                seq += 1
            end_tok = self.master_key.encrypt(
                struct.pack(">I", 0xFFFFFFFF))
            fo.write(struct.pack(">I", len(end_tok)) + end_tok)
        return dst

    def decrypt_file(self, src, dst=None):
        self._need_key()
        if not dst:
            dst = src[:-4] if src.endswith(".enc") else src + ".dec"
        with open(src, "rb") as fi:
            magic = fi.read(len(self.MAGIC))
            legacy = (magic == b"SSENC1\n")
            if not legacy and magic != self.MAGIC:
                raise SecurityError("ملف غير مشفّر بهذا النظام")
            tmp = dst + ".part"
            try:
                with open(tmp, "wb") as fo:
                    expected_seq = 0
                    saw_end = False
                    while True:
                        hdr = fi.read(4)
                        if not hdr:
                            break
                        (n,) = struct.unpack(">I", hdr)
                        try:
                            plain = self.master_key.decrypt(fi.read(n))
                        except InvalidToken as e:
                            raise SecurityError(
                                "كلمة المرور خاطئة أو الملف تالف") from e
                        if legacy:
                            fo.write(plain)
                            continue
                        if len(plain) < 4:
                            raise SecurityError("مقطع تالف")
                        seq = struct.unpack(">I", plain[:4])[0]
                        if seq == 0xFFFFFFFF:
                            saw_end = True
                            break
                        if seq != expected_seq:
                            raise SecurityError(
                                "ترتيب مقاطع غير صالح — الملف عُدِّل")
                        fo.write(plain[4:])
                        expected_seq += 1
                    if not legacy and not saw_end:
                        raise SecurityError(
                            "الملف مقطوع — علامة النهاية مفقودة")
                os.replace(tmp, dst)
            finally:
                with contextlib.suppress(OSError):
                    os.remove(tmp)
        return dst