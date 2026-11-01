"""Superior Sync integration subsystem."""

from __future__ import annotations

from ._shared import *
from .errors import ErrorCategory, ErrorLevel, ErrorLog
from ..config import KDF_ITERATIONS, derive_cloud_creds_key


class CloudError(Exception):
    def __init__(self, message: str, *, status: int | None = None,
                 retryable: bool = False, context: dict | None = None):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.context = context or {}


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, ip: str, port: int, host_header: str, timeout: float):
        super().__init__(ip, port, timeout=timeout)
        self._host_header = host_header

    def putheader(self, header, *values):
        if header.lower() == "host":
            header = "Host"
            values = (self._host_header,)
        return super().putheader(header, *values)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, ip: str, port: int, host_header: str, timeout: float):
        super().__init__(ip, port, timeout=timeout, context=ssl.create_default_context())
        self._host_header = host_header
        # اسم المضيف الحقيقي (بلا المنفذ) لاستخدامه في SNI والتحقق من الشهادة.
        self._sni_host = urllib.parse.urlsplit("//" + (host_header or ip)).hostname or ip

    def connect(self):
        # [FIX-CRIT] الاتصال يتم بعنوان IP المثبَّت (لمنع DNS-rebinding)، لكن
        # HTTPSConnection الافتراضية كانت تستخدم الـ IP كـ server_hostname، فيفشل
        # التحقق من الشهادة دائمًا ("IP address mismatch") وتتعطل كل اتصالات HTTPS
        # (Dropbox / Drive / OneDrive / WebDAV / webhooks). نتصل بالـ IP ونتحقق
        # من الشهادة ونرسل SNI على اسم المضيف الحقيقي.
        http.client.HTTPConnection.connect(self)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self._sni_host)

    def putheader(self, header, *values):
        if header.lower() == "host":
            header = "Host"
            values = (self._host_header,)
        return super().putheader(header, *values)


def _resolve_and_pin(url: str, allow_private: bool = False) -> tuple[str, str, int, str, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise CloudError("يُسمح بـ http/https فقط", retryable=False,
                         context={"url": url, "scheme": parsed.scheme})
    host = parsed.hostname
    if not host:
        raise CloudError("المضيف مفقود", retryable=False, context={"url": url})
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise CloudError(f"تعذّر تحليل اسم المضيف: {exc}", retryable=True,
                         context={"host": host}) from exc
    chosen: str | None = None
    for family, _, _, _, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not allow_private and (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            continue
        chosen = ip_str
        break
    if not chosen:
        raise CloudError("لا يوجد عنوان IP عام آمن", retryable=False,
                         context={"host": host})
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return parsed.scheme, chosen, port, host, path


def _http(
    method: str,
    url: str,
    headers: dict | None = None,
    data: bytes | None = None,
    timeout: float = 60,
    allow_internal: bool = False,
    *,
    max_attempts: int = 3,
    backoff_base: float = 0.6,
    error_log: "ErrorLog | None" = None,
) -> tuple[int, bytes]:
    last_error: Exception | None = None
    attempt = 0
    while attempt < max(1, max_attempts):
        attempt += 1
        try:
            return _http_once(method, url, headers, data, timeout, allow_internal)
        except CloudError as exc:
            last_error = exc
            retryable = exc.retryable and attempt < max_attempts
            if error_log is not None:
                error_log.log(
                    f"فشل طلب HTTP إلى {url}",
                    level=ErrorLevel.WARNING if retryable else ErrorLevel.ERROR,
                    category=ErrorCategory.CLOUD,
                    exc=exc,
                    context={"method": method, "url": url,
                             "attempt": attempt, "status": exc.status},
                )
            if not retryable:
                raise
            sleep = backoff_base * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
            time.sleep(min(sleep, 8.0))
    if last_error is not None:
        raise last_error
    raise CloudError("فشل غير معروف", retryable=False)


def _http_once(
    method: str,
    url: str,
    headers: dict | None,
    data: bytes | None,
    timeout: float,
    allow_internal: bool,
) -> tuple[int, bytes]:
    scheme, ip, port, host, path = _resolve_and_pin(url, allow_internal)
    conn = (_PinnedHTTPSConnection(ip, port, host, timeout)
            if scheme == "https"
            else _PinnedHTTPConnection(ip, port, host, timeout))
    hdrs = dict(headers or {})
    hdrs["Host"] = host
    hdrs.setdefault("User-Agent", "SuperiorSync/4.1.1")
    try:
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        body = resp.read()
        status = resp.status
    except (OSError, http.client.HTTPException) as exc:
        with contextlib.suppress(Exception):
            conn.close()
        raise CloudError(
            f"تعذّر الاتصال بـ {host}: {exc}",
            retryable=True,
            context={"host": host, "port": port, "method": method, "path": path},
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    if status == 429:
        raise CloudError("تجاوز حد الطلبات", status=status, retryable=True,
                         context={"host": host, "url": url})
    if 500 <= status < 600:
        raise CloudError(
            f"خطأ من الخدمة ({status})",
            status=status, retryable=True,
            context={"host": host, "url": url,
                     "body_excerpt": body[:200].decode("utf-8", "replace")},
        )
    if status >= 400:
        raise CloudError(
            f"HTTP {status}: {body[:300].decode('utf-8', 'replace')}",
            status=status, retryable=False,
            context={"host": host, "url": url},
        )
    return status, body


# ==================================================================
# مزودات السحابة — مع قاطع دارة وإعادة محاولة
# ==================================================================

class _CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_after: float = 60.0):
        self.failure_threshold = failure_threshold
        self.reset_after = reset_after
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = 0.0

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at and time.time() - self._opened_at >= self.reset_after:
                self._opened_at = 0.0
                self._failures = 0
                return False
            return self._opened_at > 0

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = 0.0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = time.time()

    def state(self) -> dict:
        with self._lock:
            return {
                "failures": self._failures,
                "open": self._opened_at > 0,
                "opened_at": self._opened_at or None,
                "resets_in": max(0.0, self.reset_after - (time.time() - self._opened_at))
                if self._opened_at else 0.0,
            }


class FolderProvider:
    name = "folder"

    def __init__(self, cred):
        self.root = os.path.abspath(cred.get("path", ""))
        if not os.path.isdir(self.root):
            raise CloudError("المسار غير موجود", retryable=False,
                             context={"path": self.root})

    def upload(self, local: str, remote: str) -> int:
        dst = safe_join(self.root, remote)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(local, dst)
        return os.path.getsize(dst)

    def download(self, remote: str, local: str) -> None:
        shutil.copy2(safe_join(self.root, remote), local)

    def list(self, path: str = "/") -> list[dict]:
        base = safe_join(self.root, path.strip("/") or ".") if path.strip("/") else self.root
        out = []
        for entry in sorted(os.scandir(base), key=lambda e: e.name.lower()):
            st = entry.stat()
            out.append({
                "name": entry.name,
                "path": os.path.relpath(entry.path, self.root).replace(os.sep, "/"),
                "size": 0 if entry.is_dir() else st.st_size,
                "modified": st.st_mtime,
                "type": "folder" if entry.is_dir() else "file",
            })
        return out


class DropboxProvider:
    name = "dropbox"

    def __init__(self, cred):
        token = cred.get("token", "")
        if not token:
            raise CloudError("رمز Dropbox مفقود", retryable=False)
        self.h = {"Authorization": "Bearer " + token}

    def upload(self, local: str, remote: str) -> int:
        with open(local, "rb") as fh:
            data = fh.read()
        arg = json.dumps({"path": "/" + remote.strip("/"), "mode": "overwrite", "mute": True})
        _http("POST", "https://content.dropboxapi.com/2/files/upload",
              {**self.h, "Dropbox-API-Arg": arg,
               "Content-Type": "application/octet-stream"},
              data, 600)
        return len(data)

    def download(self, remote: str, local: str) -> None:
        _, body = _http(
            "POST",
            "https://content.dropboxapi.com/2/files/download",
            {**self.h, "Dropbox-API-Arg": json.dumps({"path": "/" + remote.strip("/")})},
            b"", 600,
        )
        atomic_write_bytes(local, body)

    def list(self, path: str = "/") -> list[dict]:
        p = "" if path.strip("/") == "" else "/" + path.strip("/")
        _, body = _http(
            "POST",
            "https://api.dropboxapi.com/2/files/list_folder",
            {**self.h, "Content-Type": "application/json"},
            json.dumps({"path": p}).encode(),
        )
        return [{
            "name": e["name"],
            "path": e.get("path_display", ""),
            "size": e.get("size", 0),
            "modified": 0,
            "type": "folder" if e[".tag"] == "folder" else "file",
        } for e in json.loads(body).get("entries", [])]


class OneDriveProvider:
    name = "onedrive"
    BASE = "https://graph.microsoft.com/v1.0/me/drive"

    def __init__(self, cred):
        token = cred.get("token", "")
        if not token:
            raise CloudError("رمز OneDrive مفقود", retryable=False)
        self.h = {"Authorization": "Bearer " + token}

    def upload(self, local: str, remote: str) -> int:
        with open(local, "rb") as fh:
            data = fh.read()
        if len(data) > 4 * 1024 * 1024:
            raise CloudError(
                "OneDrive: الرفع البسيط محدود بـ 4MB (استخدم مجلد OneDrive المحلي)",
                retryable=False,
            )
        _http("PUT", f"{self.BASE}/root:/{urllib.parse.quote(remote.strip('/'))}:/content",
              {**self.h, "Content-Type": "application/octet-stream"}, data, 300)
        return len(data)

    def download(self, remote: str, local: str) -> None:
        _, body = _http("GET",
                        f"{self.BASE}/root:/{urllib.parse.quote(remote.strip('/'))}:/content",
                        self.h, None, 600)
        atomic_write_bytes(local, body)

    def list(self, path: str = "/") -> list[dict]:
        p = path.strip("/")
        url = (f"{self.BASE}/root/children" if not p
               else f"{self.BASE}/root:/{urllib.parse.quote(p)}:/children")
        _, body = _http("GET", url, self.h)
        return [{
            "name": e["name"],
            "path": (p + "/" if p else "") + e["name"],
            "size": e.get("size", 0),
            "modified": 0,
            "type": "folder" if "folder" in e else "file",
        } for e in json.loads(body).get("value", [])]


class GoogleDriveProvider:
    name = "google_drive"

    def __init__(self, cred):
        token = cred.get("token", "")
        if not token:
            raise CloudError("رمز Google Drive مفقود", retryable=False)
        self.h = {"Authorization": "Bearer " + token}

    def upload(self, local: str, remote: str) -> int:
        with open(local, "rb") as fh:
            data = fh.read()
        boundary = uuid.uuid4().hex
        meta = json.dumps({"name": os.path.basename(remote)}).encode()
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
            + meta
            + f"\r\n--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n".encode()
            + data
            + f"\r\n--{boundary}--".encode()
        )
        _http("POST",
              "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
              {**self.h, "Content-Type": f"multipart/related; boundary={boundary}"},
              body, 600)
        return len(data)

    def download(self, remote: str, local: str) -> None:
        _, body = _http("GET",
                        f"https://www.googleapis.com/drive/v3/files/"
                        f"{urllib.parse.quote(remote)}?alt=media",
                        self.h, None, 600)
        atomic_write_bytes(local, body)

    def list(self, path: str = "/") -> list[dict]:
        _, body = _http(
            "GET",
            "https://www.googleapis.com/drive/v3/files?pageSize=100"
            "&fields=files(id,name,size,mimeType,modifiedTime)",
            self.h,
        )
        return [{
            "name": f["name"],
            "path": f["id"],
            "size": int(f.get("size", 0) or 0),
            "modified": 0,
            "type": "folder" if f["mimeType"].endswith("folder") else "file",
        } for f in json.loads(body).get("files", [])]


class WebDAVProvider:
    name = "webdav"

    def __init__(self, cred):
        self.base = cred.get("url", "").rstrip("/")
        token = base64.b64encode(
            f"{cred.get('username', '')}:{cred.get('password', '')}".encode()
        ).decode()
        self.h = {"Authorization": "Basic " + token}
        if not self.base.startswith(("http://", "https://")):
            raise CloudError("رابط WebDAV غير صالح", retryable=False)

    def _url(self, path: str) -> str:
        return self.base + "/" + urllib.parse.quote(path.strip("/"))

    def upload(self, local: str, remote: str) -> int:
        with open(local, "rb") as fh:
            data = fh.read()
        _http("PUT", self._url(remote), self.h, data, 600)
        return len(data)

    def download(self, remote: str, local: str) -> None:
        _, body = _http("GET", self._url(remote), self.h, None, 600)
        atomic_write_bytes(local, body)

    def list(self, path: str = "/") -> list[dict]:
        import xml.etree.ElementTree as ET
        _, body = _http("PROPFIND", self._url(path), {**self.h, "Depth": "1"})
        ns = {"d": "DAV:"}
        out = []
        for response in ET.fromstring(body).findall("d:response", ns)[1:]:
            href = urllib.parse.unquote(response.findtext("d:href", "", ns))
            is_dir = response.find(".//d:resourcetype/d:collection", ns) is not None
            out.append({
                "name": href.rstrip("/").split("/")[-1],
                "path": href,
                "size": int(response.findtext(".//d:getcontentlength", "0", ns) or 0),
                "modified": 0,
                "type": "folder" if is_dir else "file",
            })
        return out


# ==================================================================
# تكامل السحابة — ربط المزودات بالإعدادات والسجل
# ==================================================================

class CloudIntegration:
    PROVIDERS = {
        "folder": FolderProvider,
        "dropbox": DropboxProvider,
        "google_drive": GoogleDriveProvider,
        "onedrive": OneDriveProvider,
        "webdav": WebDAVProvider,
    }

    def __init__(self, config_or_dir, error_log: ErrorLog | None = None, hub=None):
        if hasattr(config_or_dir, "data_dir"):
            self.config = config_or_dir
            self.data_dir = Path(config_or_dir.data_dir)
        else:
            self.config = None
            self.data_dir = Path(config_or_dir)
        self.file = self.data_dir / "cloud_config.json"
        self.lock = threading.RLock()
        self.cloud_config = read_json(self.file, {}) or {}
        self.supported_services = self.PROVIDERS
        self.active_connections: dict[str, Any] = {}
        self.error_log = error_log
        self.hub = hub
        self._breakers: dict[str, _CircuitBreaker] = {}
        self._retry_attempts = self._cfg_int("cloud_retry_attempts", 3)
        self._breaker_reset = self._cfg_int("cloud_circuit_breaker_seconds", 60)
        for name, spec in self.cloud_config.get("cloud_services", {}).items():
            if spec.get("connected"):
                # [FIX] كان أي فشل (مثل تغيّر مفتاح المجموعة) يُبتلع بصمت فتختفي
                # الاتصالات دون أي أثر؛ نسجّل السبب الآن.
                try:
                    creds = self._decrypt_credentials(
                        spec.get("credentials_enc") or spec.get("credentials", {})
                    )
                    self.active_connections[name] = self.PROVIDERS[name](creds)
                    self._breakers[name] = _CircuitBreaker(
                        reset_after=float(self._breaker_reset)
                    )
                except Exception as exc:
                    log.warning("تعذّر استعادة اتصال السحابة '%s': %s", name, exc)

    def _cfg_int(self, name: str, default: int) -> int:
        if self.config is None:
            return default
        try:
            return int(getattr(self.config, name, default))
        except (TypeError, ValueError):
            return default

    def _report(self, message: str, exc: BaseException | None = None,
                *, level=ErrorLevel.ERROR, context: dict | None = None) -> None:
        if self.hub is not None:
            self.hub.report(exc or RuntimeError(message), message,
                            level=level, category=ErrorCategory.CLOUD,
                            context=context)
        elif self.error_log is not None:
            self.error_log.log(message, level=level, category=ErrorCategory.CLOUD,
                               exc=exc, context=context)
        else:
            log.error("%s — %s", message, exc)

    def _creds_key(self) -> bytes:
        """Derive the at-rest key protecting cloud-provider credentials.

        Delegates to :func:`config.derive_cloud_creds_key` so the KDF
        parameters (salt + iteration count) live in the central
        ``KDF_ITERATIONS`` table instead of being inlined here.  Before
        this refactor the method hard-coded ``120_000`` iterations with a
        salt that only existed in this file, making it easy to miss
        during a security review.
        """
        if self.config is not None:
            group_key = getattr(self.config, "group_key", "") or "no-config"
        else:
            group_key = "no-config"
        return derive_cloud_creds_key(group_key)

    def _encrypt_credentials(self, creds: dict) -> dict:
        if not HAS_CRYPTO:
            log.warning("⚠️ بيانات اعتماد السحابة تُخزّن نصاً صريحاً — ثبّت cryptography")
            return {"_plaintext": True, **creds}
        try:
            f = Fernet(base64.urlsafe_b64encode(self._creds_key()))
            return {"_enc": f.encrypt(json.dumps(creds).encode("utf-8")).decode("ascii")}
        except Exception as exc:
            self._report("فشل تشفير بيانات الاعتماد", exc,
                         level=ErrorLevel.WARNING,
                         context={"service": creds.get("service", "?")})
            return {"_plaintext": True, **creds}

    def _decrypt_credentials(self, blob: dict) -> dict:
        if isinstance(blob, dict) and "_enc" in blob:
            if not HAS_CRYPTO:
                raise CloudError("بيانات اعتماد مشفّرة لكن cryptography غير مثبتة",
                                 retryable=False)
            f = Fernet(base64.urlsafe_b64encode(self._creds_key()))
            try:
                return json.loads(f.decrypt(blob["_enc"].encode("ascii")).decode("utf-8"))
            except (InvalidToken, ValueError) as exc:
                raise CloudError("فشل فك تشفير بيانات الاعتماد (تغيّر مفتاح المجموعة؟)",
                                 retryable=False) from exc
        if isinstance(blob, dict) and blob.get("_plaintext"):
            return {k: v for k, v in blob.items() if not k.startswith("_")}
        return blob if isinstance(blob, dict) else {}

    def _save(self) -> None:
        try:
            atomic_write_json(self.file, self.cloud_config, mode=0o600)
        except OSError as exc:
            self._report("تعذّر حفظ إعدادات السحابة", exc)

    def _breaker(self, name: str) -> _CircuitBreaker:
        with self.lock:
            if name not in self._breakers:
                self._breakers[name] = _CircuitBreaker(
                    reset_after=float(self._breaker_reset)
                )
            return self._breakers[name]

    def connect_service(self, name: str, credentials: dict) -> dict:
        if name not in self.PROVIDERS:
            return {"success": False,
                    "error": "خدمة غير مدعومة. المتاح: " + ", ".join(self.PROVIDERS)}
        try:
            provider = self.PROVIDERS[name](credentials)
            provider.list("/")
        except (CloudError, OSError, ValueError, KeyError) as exc:
            self._report(f"فشل الاتصال بـ {name}", exc,
                         context={"service": name})
            return {"success": False, "error": f"فشل الاتصال: {exc}"}
        with self.lock:
            self.cloud_config.setdefault("cloud_services", {})[name] = {
                "connected": True,
                "connected_at": time.time(),
                "credentials_enc": self._encrypt_credentials(credentials),
            }
            self._save()
            self.active_connections[name] = provider
            self._breaker(name).record_success()
        if self.hub is not None:
            self.hub.notify("تم الاتصال بالسحابة",
                            f"الخدمة {name} متصلة",
                            notification_type="success", category="cloud")
        return {"success": True, "message": f"تم الاتصال بـ {name}"}

    def disconnect_service(self, name: str) -> dict:
        with self.lock:
            self.active_connections.pop(name, None)
            self._breakers.pop(name, None)
            spec = self.cloud_config.get("cloud_services", {}).get(name)
            if spec:
                spec["connected"] = False
                spec["credentials_enc"] = {}
                spec.pop("credentials", None)
                self._save()
        if self.hub is not None:
            self.hub.notify("تم قطع الاتصال بالسحابة",
                            f"الخدمة {name} غير متصلة",
                            notification_type="info", category="cloud")
        return {"success": True, "message": f"تم قطع الاتصال بـ {name}"}

    def _provider(self, name: str) -> Any:
        breaker = self._breaker(name)
        if breaker.is_open():
            state = breaker.state()
            raise CloudError(
                f"الخدمة {name} معطّلة مؤقتاً (قاطع الدارة مفتوح، "
                f"يعيد المحاولة خلال {state['resets_in']:.0f}s)",
                retryable=True,
                context={"service": name, "breaker": state},
            )
        provider = self.active_connections.get(name)
        if not provider:
            raise CloudError("الخدمة غير متصلة", retryable=False,
                             context={"service": name})
        return provider

    def _call(self, name: str, operation: str, fn, *args, **kwargs):
        breaker = self._breaker(name)
        try:
            result = fn(*args, **kwargs)
            breaker.record_success()
            return result
        except CloudError:
            breaker.record_failure()
            raise
        except Exception as exc:
            breaker.record_failure()
            raise CloudError(
                f"فشل {operation} عبر {name}: {exc}",
                retryable=True,
                context={"service": name, "operation": operation},
            ) from exc

    def upload_to_cloud(self, name: str, file_path: str, cloud_path: str | None = None) -> dict:
        try:
            if not os.path.isfile(file_path):
                return {"success": False, "error": "الملف غير موجود"}
            provider = self._provider(name)
            target = cloud_path or os.path.basename(file_path)
            size = self._call(name, "upload", provider.upload, file_path, target)
            return {"success": True, "file_size": size, "cloud_path": target}
        except (CloudError, OSError, PathError) as exc:
            self._report(f"فشل رفع {file_path} إلى {name}", exc,
                         context={"service": name, "file": file_path})
            return {"success": False, "error": str(exc)}

    def download_from_cloud(self, name: str, cloud_path: str, local_path: str) -> dict:
        try:
            provider = self._provider(name)
            self._call(name, "download", provider.download, cloud_path, local_path)
            return {"success": True, "local_path": local_path}
        except (CloudError, OSError, PathError) as exc:
            self._report(f"فشل تنزيل {cloud_path} من {name}", exc,
                         context={"service": name, "remote": cloud_path})
            return {"success": False, "error": str(exc)}

    def list_cloud_files(self, name: str, path: str = "/") -> dict:
        try:
            provider = self._provider(name)
            files = self._call(name, "list", provider.list, path)
            return {"success": True, "files": files, "path": path}
        except (CloudError, OSError, PathError) as exc:
            self._report(f"فشل سرد {path} في {name}", exc,
                         context={"service": name, "path": path})
            return {"success": False, "error": str(exc)}

    def schedule_backup(self, name: str, local_path: str, cloud_path: str, schedule: str) -> dict:
        if schedule not in ("hourly", "daily", "weekly", "monthly"):
            return {"success": False, "error": "الجدولة: hourly|daily|weekly|monthly"}
        job = {
            "id": uuid.uuid4().hex[:8],
            "service_name": name,
            "local_path": os.path.abspath(local_path),
            "cloud_path": cloud_path,
            "schedule": schedule,
            "last_run": None,
            "next_run": self._next_run(schedule),
            "enabled": True,
        }
        with self.lock:
            self.cloud_config.setdefault("backup_jobs", []).append(job)
            self._save()
        return {"success": True, "message": "تمت الجدولة", "job": job["id"]}

    @staticmethod
    def _next_run(schedule: str) -> float:
        return time.time() + {
            "hourly": 3600, "daily": 86400,
            "weekly": 604800, "monthly": 2592000,
        }.get(schedule, 86400)

    def run_due_backups(self) -> int:
        now, ran = time.time(), 0
        for job in self.cloud_config.get("backup_jobs", []):
            if (not job.get("enabled") or job["next_run"] > now
                    or job["service_name"] not in self.active_connections):
                continue
            src = job["local_path"]
            files = ([src] if os.path.isfile(src)
                     else [os.path.join(r, f) for r, _, fs in os.walk(src) for f in fs
                           if not is_ignored(f)])
            base = os.path.dirname(src) if os.path.isfile(src) else src
            prev_state = job.get("file_state", {})
            new_state: dict = {}
            failed = 0
            for file_path in files:
                try:
                    st = os.stat(file_path)
                except OSError:
                    continue
                rel = os.path.relpath(file_path, base).replace(os.sep, "/")
                new_state[rel] = (st.st_size, int(st.st_mtime))
                old = prev_state.get(rel)
                if old and old[0] == new_state[rel][0] and old[1] == new_state[rel][1]:
                    continue
                result = self.upload_to_cloud(
                    job["service_name"], file_path,
                    (job["cloud_path"].rstrip("/") + "/" + rel).strip("/"),
                )
                if not result.get("success"):
                    # [FIX] كانت الحالة تُسجَّل «منسوخًا» حتى لو فشل الرفع (قيمة
                    # الإرجاع تُتجاهل)، فلا يُعاد الملف أبدًا حتى يتغير. الآن نُبقي
                    # الحالة السابقة ليُعاد في الدورة التالية.
                    failed += 1
                    job["last_error"] = result.get("error")
                    if old:
                        new_state[rel] = tuple(old)
                    else:
                        new_state.pop(rel, None)
            job["file_state"] = new_state
            job["last_run"] = now
            job["failed_files"] = failed
            if not failed:
                job.pop("last_error", None)
            # عند وجود إخفاقات نعيد المحاولة بعد 15 دقيقة بدل انتظار الجدولة كاملة.
            job["next_run"] = (now + 900) if failed else self._next_run(job["schedule"])
            ran += 1
        if ran:
            with self.lock:
                self._save()
        return ran

    def get_connected_services(self) -> list[str]:
        return sorted(self.active_connections)

    def health(self) -> dict:
        services = {}
        for name in self.PROVIDERS:
            breaker = self._breakers.get(name)
            services[name] = {
                "connected": name in self.active_connections,
                "breaker": breaker.state() if breaker else None,
            }
        return {"services": services, "jobs": len(self.cloud_config.get("backup_jobs", []))}


# ==================================================================
# التشغيل التلقائي
# ==================================================================
