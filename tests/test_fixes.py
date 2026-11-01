"""Regression tests for the bugs found in the v4.1.x code review.

كل اختبار هنا يفشل على النسخة القديمة وينجح بعد الإصلاح. لا يحتاج أي منها إلى
FastAPI؛ ما يخص الـ routers يُفحص عبر AST.

Run:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import ast
import datetime
import hashlib
import importlib.util
import io
import logging
import os
import pathlib
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
import uuid
import zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "superior_sync"
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

HAS_NODE = shutil.which("node") is not None
HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


def _put(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def _restore_env(name, was_set, value):
    if was_set:
        os.environ[name] = value
    else:
        os.environ.pop(name, None)


def _env(tmp, add_cleanup):
    for name, value in (
        ("XDG_CONFIG_HOME", os.path.join(tmp, "xdg")),
        ("HOME", tmp),
    ):
        was_set = name in os.environ
        previous = os.environ.get(name)
        add_cleanup(_restore_env, name, was_set, previous)
        os.environ[name] = value


def _make_engine(tmp, add_cleanup):
    _env(tmp, add_cleanup)
    from superior_sync.config import Config
    from superior_sync.sync_core import SyncEngine
    cfg = Config(data_dir=os.path.join(tmp, "data"), master_password="pw-for-tests-123")
    root = os.path.join(tmp, "share")
    os.makedirs(root)
    cfg.sync_folders = [root]
    cfg.invalidate_shares()
    eng = SyncEngine(cfg)
    eng._rebuild_path_index()
    share = next(s for s, p in cfg.shares().items() if p == root)
    return cfg, eng, root, share


def _write(root, rel, text="x", age=60):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(text)
    old = time.time() - age
    os.utime(p, (old, old))
    return p


# ----------------------------------------------------------------------
class WatcherPollingTests(unittest.TestCase):
    def test_polling_detects_modifications_and_subfolders(self):
        import superior_sync.utils as u
        saved = u.HAS_WATCHFILES
        u.HAS_WATCHFILES = False
        self.addCleanup(setattr, u, "HAS_WATCHFILES", saved)
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(f"{root}/sub")
        _put(f"{root}/a.txt", "v1")
        _put(f"{root}/sub/b.txt", "v1")
        cfg = types.SimpleNamespace(ignore_patterns=[], detect_moves=True)
        w = u.FileWatcher(cfg, debounce=0.1, polling_interval=0.2)
        events = []
        w.register_callback(lambda e: events.append((e["type"], os.path.relpath(e["path"], root))))
        w.add_watch_path(root)
        w.start()
        self.addCleanup(w.stop)
        time.sleep(0.8)

        events.clear()
        _put(f"{root}/a.txt", "v2-changed-longer")
        time.sleep(1.2)
        self.assertTrue(any(p == "a.txt" for _, p in events), events)

        events.clear()
        _put(f"{root}/sub/b.txt", "v2-changed-longer")
        time.sleep(1.2)
        self.assertTrue(any(p.endswith("b.txt") for _, p in events), events)


class IgnoreTests(unittest.TestCase):
    def test_engine_temp_names_are_ignored(self):
        from superior_sync.utils import is_ignored
        for name in (f"report.txt.sync-tmp-{uuid.uuid4().hex}",
                     f"x.bin.restore-{uuid.uuid4().hex[:10]}",
                     ".sync-tmp-abc", ".p2p_tmp", ".tmp-xyz"):
            self.assertTrue(is_ignored(name), name)
        self.assertFalse(is_ignored("report.txt"))
        self.assertFalse(is_ignored(".conflicts"))   # يجب أن تبقى متزامنة

    def test_safe_eq_handles_non_ascii(self):
        from superior_sync.utils import safe_eq
        self.assertFalse(safe_eq("é", "a"))
        self.assertTrue(safe_eq("é", "é"))


# ----------------------------------------------------------------------
class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        _env(self.tmp, self.addCleanup)

    def test_wrong_master_password_never_overwrites_group_key(self):
        from superior_sync.config import Config, GroupKeyError
        data = os.path.join(self.tmp, "data")
        c1 = Config(data_dir=data, master_password="correct-horse-battery")
        key = c1.group_key
        before = open(os.path.join(data, "config.json")).read()
        with self.assertRaises(GroupKeyError):
            Config(data_dir=data, master_password="WRONG-password")
        self.assertEqual(before, open(os.path.join(data, "config.json")).read())
        self.assertEqual(Config(data_dir=data, master_password="correct-horse-battery").group_key, key)

    def test_show_group_key_uses_cli_master_password(self):
        from contextlib import redirect_stdout
        from superior_sync.config import Config
        from superior_sync.main import main

        data = os.path.join(self.tmp, "data")
        expected = Config(data_dir=data, master_password="correct-horse-battery").group_key
        output = io.StringIO()
        with redirect_stdout(output):
            result = main([
                "--data-dir", data,
                "--master-password", "correct-horse-battery",
                "--show-group-key",
            ])
        self.assertEqual(result, 0)
        self.assertIn(expected, output.getvalue())

    def test_initial_admin_password_is_saved(self):
        from contextlib import redirect_stdout
        from superior_sync.main import main

        class FakeApp:
            def __init__(self, config, master_password):
                self.api = object()
                self.security = types.SimpleNamespace(
                    ensure_admin=lambda: "initial-secret"
                )
                self.engine = types.SimpleNamespace(start=lambda: None)
                self.analytics = types.SimpleNamespace(start=lambda: None)
                self.start_background = lambda: None
                self.shutdown = lambda: None
                self.local_admin_token = ""

        class FakeServer:
            def __init__(self, config):
                self.should_exit = False

            def run(self):
                return None

        from superior_sync import main as main_module

        with (
            patch.object(main_module, "SuperiorSyncApp", FakeApp),
            patch.object(main_module.uvicorn, "Server", FakeServer),
            patch.object(main_module, "get_local_ip", return_value="127.0.0.1"),
            patch.object(main_module, "setup_logging"),
            redirect_stdout(io.StringIO()),
        ):
            result = main([
                "--data-dir", os.path.join(self.tmp, "data"),
                "--master-password", "correct-horse-battery",
                "--mode", "background", "--no-sync", "--no-browser",
            ])
        self.assertEqual(result, 0)
        saved = os.path.join(
            self.tmp, "data", "security", "initial_admin_password.txt"
        )
        with open(saved, encoding="utf-8") as password_file:
            self.assertEqual(password_file.read(), "initial-secret")

    def test_failed_update_rolls_back_every_field(self):
        from superior_sync.config import Config
        c = Config(data_dir=os.path.join(self.tmp, "data"), master_password="pw-for-tests-123")
        port, interval = c.server_port, c.sync_interval
        ok, _, _ = c.update({"server_port": 9999, "sync_interval": 10 ** 6})
        self.assertFalse(ok)
        self.assertEqual((c.server_port, c.sync_interval), (port, interval))

    def test_unchanged_config_update_does_not_save(self):
        from superior_sync.config import Config
        c = Config(
            data_dir=os.path.join(self.tmp, "no-op-data"),
            master_password="pw-for-tests-123",
        )
        with patch.object(c, "save") as save:
            ok, error, restart = c.update({"server_port": c.server_port})
        self.assertTrue(ok, error)
        self.assertFalse(restart)
        save.assert_not_called()

    def test_trusted_proxies_are_normalized_and_validated(self):
        from pydantic import ValidationError
        from superior_sync.config import Config
        from superior_sync.schemas import ConfigPayload

        payload = ConfigPayload(
            trusted_proxies=["10.0.0.2", "192.0.2.0/24", "10.0.0.2"]
        )
        self.assertEqual(
            payload.trusted_proxies,
            ["10.0.0.2/32", "192.0.2.0/24"],
        )
        with self.assertRaises(ValidationError):
            ConfigPayload(trusted_proxies=["not-an-ip"])

        config = Config(
            data_dir=os.path.join(self.tmp, "proxy-data"),
            master_password="pw-for-tests-123",
        )
        ok, error, _ = config.update(
            {"trusted_proxies": payload.trusted_proxies}
        )
        self.assertTrue(ok, error)
        self.assertEqual(config.trusted_proxies, payload.trusted_proxies)

    def test_security_cleanup_thread_stops_on_close(self):
        from superior_sync.config import SecurityManager
        security = SecurityManager(os.path.join(self.tmp, "security-data"))
        thread = security._cleanup_thread
        security.close()
        self.assertFalse(thread.is_alive())

    def test_config_payload_includes_browser_and_trusted_host_fields(self):
        from superior_sync.config import Config
        from superior_sync.schemas import ConfigPayload

        payload = ConfigPayload(
            auto_open_browser=False,
            trusted_hosts=[" example.test ", "", "*"],
        )
        self.assertEqual(
            payload.model_dump(exclude_unset=True),
            {"auto_open_browser": False, "trusted_hosts": ["example.test"]},
        )

        config = Config(
            data_dir=os.path.join(self.tmp, "payload-data"),
            master_password="pw-for-tests-123",
        )
        ok, error, _ = config.update(
            payload.model_dump(exclude_unset=True)
        )
        self.assertTrue(ok, error)
        self.assertFalse(config.auto_open_browser)
        self.assertEqual(config.trusted_hosts, ["example.test"])

    def test_path_validation(self):
        from superior_sync.config import validate_receive_folder, validate_sync_folder
        if os.name != "nt":
            with self.assertRaises(ValueError):
                validate_receive_folder("/etc/x")
            with self.assertRaises(ValueError):
                validate_receive_folder("/var")
        validate_receive_folder("/var/lib/superior-sync-test")   # NAS-style paths allowed
        data = os.path.join(self.tmp, "data")
        os.makedirs(data)
        with self.assertRaises(ValueError):
            validate_sync_folder(self.tmp, data)                 # contains data_dir
        with self.assertRaises(ValueError):
            validate_sync_folder(os.path.join(data, "inner"), data)

    def test_cannot_delete_last_admin(self):
        from superior_sync.config import Config, SecurityManager
        c = Config(data_dir=os.path.join(self.tmp, "data"), master_password="pw-for-tests-123")
        sm = SecurityManager(c.data_dir)
        sm.create_user("alice", "password-123", "admin")
        admins = [u for u, d in sm.users.items() if d["role"] == "admin"]
        for name in admins[:-1]:
            self.assertTrue(sm.delete_user(name))
        self.assertFalse(sm.delete_user(admins[-1]))


# ----------------------------------------------------------------------
class NetworkTests(unittest.TestCase):
    def _codec(self, enc=True):
        from superior_sync.network import FrameCodec
        cfg = types.SimpleNamespace(group_key="k" * 32, enable_compression=True, enable_encryption=enc)
        return FrameCodec(cfg)

    def test_kdf_is_cached(self):
        from superior_sync.network import sign_request
        sign_request("cache-me" * 4, "GET", "/x", "1", "s", "n", "z")
        t = time.perf_counter()
        for _ in range(50):
            sign_request("cache-me" * 4, "GET", "/x", "1", "s", "n", "z")
        self.assertLess((time.perf_counter() - t) / 50, 0.01)   # كان ~120ms

    def test_add_manual_peer_sends_empty_hello_body(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from superior_sync.network import P2PProtocol
        from superior_sync.routers.p2p import router

        group_key = "shared-group-key-for-peer-test"
        local_config = types.SimpleNamespace(
            node_id="local-id", group_key=group_key, manual_peers=[]
        )
        protocol = P2PProtocol(local_config)
        remote_app = FastAPI()
        remote_app.state.superior = types.SimpleNamespace(
            config=types.SimpleNamespace(
                node_id="remote-id",
                node_name="remote",
                group_key=group_key,
                shares=lambda: {"docs": "C:/docs"},
            ),
            engine=types.SimpleNamespace(
                p2p_protocol=types.SimpleNamespace(
                    remember_nonce=lambda node, nonce: True
                )
            ),
        )
        remote_app.include_router(router)
        asgi_client = TestClient(
            remote_app,
            base_url="http://localhost",
            client=("127.0.0.1", 50000),
        )

        class ProxyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                response = asgi_client.get(
                    self.path, headers=dict(self.headers.items())
                )
                self.send_response(response.status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response.content)))
                self.end_headers()
                self.wfile.write(response.content)

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = protocol.add_manual_peer(
                f"127.0.0.1:{server.server_port}", persist=False
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            asgi_client.close()

        self.assertEqual(result, (True, "remote-id"))
        peer = protocol.get_peer("remote-id")
        self.assertEqual(peer["via"], "manual")
        self.assertEqual(peer["shares"], ["docs"])

    @unittest.skipUnless(HAS_CRYPTO, "cryptography missing")
    def test_plaintext_frame_rejected_when_encryption_enabled(self):
        codec = self._codec(True)
        payload = b"ATTACKER"
        forged = struct.pack(">BI", 0, len(payload)) + payload
        with self.assertRaises(IOError):
            list(codec.read_frames(io.BytesIO(forged)))
        legit = codec.encode(b"hello")
        self.assertEqual(next(codec.read_frames(io.BytesIO(legit)))[0], b"hello")

    def test_decompression_bomb_rejected(self):
        codec = self._codec(False)
        bomb = zlib.compress(b"\0" * (200 * 1024 * 1024), 9)
        frame = struct.pack(">BI", 1, len(bomb)) + bomb
        with self.assertRaises(IOError):
            list(codec.read_frames(io.BytesIO(frame)))
        ok = codec.encode(b"a" * 5000)
        self.assertEqual(next(codec.read_frames(io.BytesIO(ok)))[0], b"a" * 5000)

    def test_p2p_server_verifies_signature_with_the_clients_nonce(self):
        """النسخة القديمة كانت تحسب التوقيع المتوقع بلا nonce فيُرفض كل طلب P2P."""
        tree = ast.parse((PKG / "routers" / "p2p.py").read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "sign_request"]
        self.assertTrue(calls)
        for call in calls:
            self.assertGreaterEqual(len(call.args) + len(call.keywords), 7,
                                    "sign_request must receive the nonce on the server side")
        src = (PKG / "routers" / "p2p.py").read_text(encoding="utf-8")
        self.assertIn("remember_nonce", src)

    def test_inbox_reads_raw_body_not_multipart(self):
        src = (PKG / "routers" / "p2p.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "inbox")
        annotations = " ".join(ast.unparse(a.annotation) for a in fn.args.args if a.annotation)
        defaults = " ".join(ast.unparse(d) for d in fn.args.defaults)
        self.assertNotIn("UploadFile", annotations)
        self.assertNotIn("File(", defaults)
        self.assertIn("request.stream()", ast.unparse(fn))


# ----------------------------------------------------------------------
@unittest.skipUnless(HAS_CRYPTO, "cryptography missing")
class PinnedHttpsTests(unittest.TestCase):
    def test_pinned_http_host_is_set_by_putheader(self):
        from superior_sync.integrations import _PinnedHTTPConnection
        connection = _PinnedHTTPConnection("127.0.0.1", 80, "api.example.test", 1)
        try:
            connection.putrequest("GET", "/")
            request = b"".join(connection._buffer)
            self.assertIn(b"Host: api.example.test", request)
            self.assertFalse(hasattr(connection, "_http_vsn_str_host"))
        finally:
            connection.close()

    def test_https_with_valid_cert_works_through_pinned_connection(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, True)
        now = datetime.datetime.now(datetime.timezone.utc)

        def mk(subject, issuer, pub, signer, san=None, ca=False):
            b = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
                 .public_key(pub).serial_number(x509.random_serial_number())
                 .not_valid_before(now - datetime.timedelta(days=1))
                 .not_valid_after(now + datetime.timedelta(days=2))
                 .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
            b = b.add_extension(
                x509.SubjectKeyIdentifier.from_public_key(pub), critical=False
            )
            b = b.add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(
                    signer.public_key()
                ),
                critical=False,
            )
            b = b.add_extension(
                x509.KeyUsage(
                    digital_signature=not ca,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=ca,
                    crl_sign=ca,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            if not ca:
                b = b.add_extension(
                    x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                    critical=False,
                )
            if san:
                b = b.add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False)
            return b.sign(signer, hashes.SHA256())

        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
        ca_cert = mk(ca_name, ca_name, ca_key.public_key(), ca_key, ca=True)
        sk = ec.generate_private_key(ec.SECP256R1())
        sn = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "api.example.test")])
        sc = mk(sn, ca_name, sk.public_key(), ca_key, san="api.example.test")
        P = lambda n: os.path.join(td, n)
        open(P("ca.pem"), "wb").write(ca_cert.public_bytes(serialization.Encoding.PEM))
        open(P("s.pem"), "wb").write(sc.public_bytes(serialization.Encoding.PEM))
        open(P("s.key"), "wb").write(sk.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))

        old_env = os.environ.get("SSL_CERT_FILE")
        os.environ["SSL_CERT_FILE"] = P("ca.pem")
        self.addCleanup(lambda: os.environ.pop("SSL_CERT_FILE", None) if old_env is None
                        else os.environ.__setitem__("SSL_CERT_FILE", old_env))

        sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        sctx.load_cert_chain(P("s.pem"), P("s.key"))
        ls = socket.socket()
        ls.bind(("127.0.0.1", 0))
        ls.listen(5)
        port = ls.getsockname()[1]
        self.addCleanup(ls.close)

        def serve():
            while True:
                try:
                    c, _ = ls.accept()
                except OSError:
                    return
                try:
                    s = sctx.wrap_socket(c, server_side=True)
                    s.recv(4096)
                    s.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
                    s.close()
                except Exception:
                    c.close()
        threading.Thread(target=serve, daemon=True).start()

        real = socket.getaddrinfo
        socket.getaddrinfo = lambda h, *a, **k: real("127.0.0.1", *a, **k) if h == "api.example.test" else real(h, *a, **k)
        self.addCleanup(setattr, socket, "getaddrinfo", real)

        from superior_sync import integrations as I
        status, body = I._http_once("GET", f"https://api.example.test:{port}/", None, None, 5, True)
        self.assertEqual((status, body), (200, b"OK"))


class CloudBackupTests(unittest.TestCase):
    def test_failed_uploads_are_retried_not_recorded_as_done(self):
        from superior_sync.integrations import CloudError, CloudIntegration
        td = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, td, True)
        src = os.path.join(td, "docs")
        os.makedirs(src)
        for n in ("a.txt", "b.txt"):
            open(os.path.join(src, n), "w").write(n)
        ci = CloudIntegration(td)

        class Flaky:
            fail = True
            calls = 0

            def upload(self, local, remote):
                Flaky.calls += 1
                if Flaky.fail:
                    raise CloudError("down", retryable=True)
        ci.active_connections["dropbox"] = Flaky()
        ci.schedule_backup("dropbox", src, "backup", "hourly")
        job = ci.cloud_config["backup_jobs"][0]
        job["next_run"] = 0
        ci.run_due_backups()
        self.assertEqual(sorted(job["file_state"]), [])         # لا شيء مسجَّل كمنسوخ
        self.assertEqual(job["failed_files"], 2)
        Flaky.fail, Flaky.calls = False, 0
        job["next_run"] = 0
        ci.run_due_backups()
        self.assertEqual(Flaky.calls, 2)                         # أُعيدت المحاولة
        self.assertEqual(sorted(job["file_state"]), ["a.txt", "b.txt"])


# ----------------------------------------------------------------------
class SyncCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cfg, self.eng, self.root, self.share = _make_engine(
            self.tmp, self.addCleanup
        )
        self.addCleanup(self.eng.close)

    def live(self):
        return sorted(r["path"] for r in self.eng.db.query(
            "SELECT path FROM files WHERE share=? AND deleted=0", (self.share,)))

    def test_restore_oldest_version_at_cap(self):
        from superior_sync.sync_core import ConflictResolver
        cfg = types.SimpleNamespace(max_versions_per_file=3, version_retention_days=30,
                                    trash_retention_days=30)
        cr = ConflictResolver(self.eng.db, self.tmp, cfg)
        f = os.path.join(self.tmp, "report.txt")
        ids = []
        for i in range(1, 4):
            open(f, "w").write(f"content-v{i}")
            ids.append(cr.create_version(f, f"v{i}")["id"])
            time.sleep(0.02)
        open(f, "w").write("CURRENT")
        self.assertTrue(cr.restore_version(ids[0]))
        self.assertEqual(open(f).read(), "content-v1")

    def test_old_remote_mtime_is_clamped(self):
        remote_mtime_ns, clamped = self.eng._sanitize_remote_mtime_ns(1)
        self.assertTrue(clamped)
        self.assertGreater(remote_mtime_ns, 1)
        sanitized = self.eng._sanitize_remote_manifest(
            {"old.txt": {"mtime_ns": 1}}
        )["old.txt"]
        self.assertTrue(sanitized["_clamped"])
        self.assertGreater(sanitized["mtime_ns"], 1)

    def test_conflict_copy_handles_missing_local_hash(self):
        self.cfg.conflict_resolution = "ask"
        source = _write(self.root, "conflict.txt")
        captured = {}

        def record_conflict(*args):
            captured["copy_path"] = args[8]
            return "conflict-id"

        self.eng.conflict_resolver.record_conflict = record_conflict
        self.eng.notify = lambda *args, **kwargs: None
        self.eng._handle_conflict_loss(
            self.share,
            "conflict.txt",
            "peer",
            {"hash": None, "mtime_ns": 1},
            {"hash": "remote", "mtime_ns": 2},
        )
        self.assertTrue(os.path.isfile(source))
        self.assertIn("unknow", captured["copy_path"])
        self.assertTrue(os.path.isfile(os.path.join(self.root, captured["copy_path"])))

    def test_remote_delete_counter_ignores_missing_local_file(self):
        before = self.eng.counters["files_deleted"]
        self.eng._schedule_notify = lambda share: None
        self.eng._apply_remote_delete(
            self.share,
            "missing.txt",
            "peer",
            {"deleted": True, "size": 0, "mtime_ns": 0},
        )
        self.assertEqual(self.eng.counters["files_deleted"], before)

    def test_stop_attempts_all_components_after_failure(self):
        calls = []

        def failing_stop():
            calls.append("watcher")
            raise RuntimeError("watcher stop failed")

        self.eng.running = True
        self.eng.file_watcher = types.SimpleNamespace(stop=failing_stop)
        self.eng.p2p_protocol = types.SimpleNamespace(
            stop=lambda: calls.append("p2p")
        )
        self.eng.task_queue = types.SimpleNamespace(
            stop=lambda: calls.append("queue")
        )
        with self.assertRaisesRegex(RuntimeError, "watcher stop failed"):
            self.eng.stop()
        self.assertEqual(calls, ["watcher", "p2p", "queue"])

    def test_deleting_dir_does_not_touch_lookalike_siblings(self):
        _write(self.root, "my_docs/a.txt")
        _write(self.root, "myXdocs/keep.txt")
        _write(self.root, "Reports/q1.txt")
        _write(self.root, "reports2/other.txt")
        self.eng.scan_share(self.share)
        shutil.rmtree(os.path.join(self.root, "my_docs"))
        self.eng.index_path(self.share, "my_docs")
        shutil.rmtree(os.path.join(self.root, "Reports"))
        self.eng.index_path(self.share, "Reports")
        self.assertEqual(self.live(), ["myXdocs/keep.txt", "reports2/other.txt"])

    def test_inflight_temp_file_not_advertised(self):
        tmp = _write(self.root, f"video.mp4.sync-tmp-{uuid.uuid4().hex}", "partial", age=86400)
        self.eng.scan_share(self.share)
        self.assertEqual([p for p in self.eng.manifest(self.share) if "sync-tmp" in p], [])
        self.assertTrue(os.path.exists(tmp))

    def test_oversized_scan_entry_is_marked_without_hashing_or_deletion(self):
        from superior_sync.utils import MAX_HASH_SIZE_BYTES
        path = os.path.join(self.root, "large.bin")
        stat = types.SimpleNamespace(
            st_size=MAX_HASH_SIZE_BYTES + 1,
            st_mtime_ns=time.time_ns() - 10_000_000_000,
        )
        with patch.object(
            self.eng, "_walk",
            side_effect=lambda *args: iter([(path, stat)]),
        ):
            with patch.object(
                self.eng, "_hash_candidate",
                side_effect=AssertionError("oversized file must not be hashed"),
            ):
                self.eng.scan_share(self.share)
                manifest = self.eng.manifest(self.share)
        row = self.eng.db.one(
            "SELECT size,hash,deleted,oversized FROM files WHERE share=? AND path=?",
            (self.share, "large.bin"),
        )
        self.assertEqual(row["size"], MAX_HASH_SIZE_BYTES + 1)
        self.assertIsNone(row["hash"])
        self.assertFalse(row["deleted"])
        self.assertTrue(row["oversized"])
        self.assertTrue(manifest["large.bin"]["oversized"])

    def test_oversized_delta_signature_is_rejected_before_open(self):
        from superior_sync.sync_core import DeltaSync
        from superior_sync.utils import MAX_HASH_SIZE_BYTES
        delta = DeltaSync()
        with self.assertRaisesRegex(ValueError, "signature limit"):
            delta._signature_uncached(
                os.path.join(self.tmp, "does-not-exist"),
                MAX_HASH_SIZE_BYTES + 1,
                delta.MIN_BLOCK,
            )

    def test_remote_manifest_marks_large_files_as_unsupported(self):
        from superior_sync.utils import MAX_HASH_SIZE_BYTES
        manifest = self.eng._sanitize_remote_manifest(
            {"large.bin": {"size": MAX_HASH_SIZE_BYTES + 1, "mtime_ns": time.time_ns()}}
        )
        self.assertTrue(manifest["large.bin"]["oversized"])

    def test_unreadable_directory_does_not_mass_delete(self):
        _write(self.root, "photos/a.jpg")
        _write(self.root, "photos/b.jpg")
        _write(self.root, "top.txt")
        self.eng.scan_share(self.share)
        self.assertEqual(len(self.live()), 3)
        real = os.scandir
        photos = os.path.join(self.root, "photos")

        def flaky(path=".", *a, **k):
            if os.fspath(path) == photos:
                raise PermissionError("transient")
            return real(path, *a, **k)
        os.scandir = flaky
        try:
            self.eng.scan_share(self.share)
        finally:
            os.scandir = real
        self.assertEqual(self.live(), ["photos/a.jpg", "photos/b.jpg", "top.txt"])

    def test_add_sync_folder_rejects_system_and_data_dir_parent(self):
        ok, _ = self.eng.add_sync_folder("/etc")
        self.assertFalse(ok)
        ok, _ = self.eng.add_sync_folder(self.tmp)       # يحتوي data_dir
        self.assertFalse(ok)

    def test_delta_roundtrip_is_byte_exact(self):
        import random
        from superior_sync.sync_core import DeltaSync
        d = DeltaSync()
        rnd = random.Random(7)
        for size in (0, 1, 100, 16 * 1024 + 1, 300_000):
            old = bytes(rnd.getrandbits(8) for _ in range(size))
            for kind in ("append", "insert", "truncate", "rewrite"):
                if kind == "append":
                    new = old + b"tail-data"
                elif kind == "insert":
                    i = len(old) // 2
                    new = old[:i] + b"INS" + old[i:]
                elif kind == "truncate":
                    new = old[: len(old) // 2]
                else:
                    new = bytes(rnd.getrandbits(8) for _ in range(size))
                po, pn, pout = (os.path.join(self.tmp, n) for n in ("o", "n", "out"))
                open(po, "wb").write(old)
                open(pn, "wb").write(new)
                sig = d.signature(po) if old else None
                ops = [DeltaSync.decode_op(DeltaSync.encode_op(o)) for o in d.iter_delta(pn, sig)]
                DeltaSync.apply(ops, pout, po if old else None, sig)
                self.assertEqual(open(pout, "rb").read(), new, (size, kind))

    def test_delta_gives_up_rolling_on_unrelated_content(self):
        from superior_sync.sync_core import DeltaSync
        d = DeltaSync()
        d.ROLL_PROBE_BYTES = 64 * 1024
        a, b = os.urandom(600_000), os.urandom(600_000)
        po, pn, pout = (os.path.join(self.tmp, n) for n in ("o", "n", "out"))
        open(po, "wb").write(a)
        open(pn, "wb").write(b)
        sig = d.signature(po)
        ops = list(d.iter_delta(pn, sig))
        DeltaSync.apply(ops, pout, po, sig)
        self.assertEqual(open(pout, "rb").read(), b)


# ----------------------------------------------------------------------
class UiAndSchemaTests(unittest.TestCase):
    @unittest.skipUnless(HAS_NODE, "node missing")
    def test_ui_source_parses_and_i18n_keys_match(self):
        js = (PKG / "ui_src" / "app.js").read_text(encoding="utf-8")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "ui.js")
        open(path, "w", encoding="utf-8").write(js)
        r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        start = js.index("const I18N = {")
        end = js.index("\n};", start) + 3
        used = sorted(set(re.findall(r'\bt\(\s*"([\w.]+)"', js)))
        check = js[start:end] + f"""
const used = {used!r};
const langs = Object.keys(I18N);
const bad = [];
for (const l of langs) for (const k of used) if (!k.endsWith('.') && !(k in I18N[l])) bad.push(l+':'+k);
const ref = Object.keys(I18N[langs[0]]).sort().join();
for (const l of langs) if (Object.keys(I18N[l]).sort().join() !== ref) bad.push('parity:'+l);
console.log(JSON.stringify(bad));
"""
        p2 = os.path.join(tmp, "check.js")
        open(p2, "w", encoding="utf-8").write(check)
        r = subprocess.run(["node", p2], capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "[]", r.stdout + r.stderr)

    def test_receive_folder_schema_accepts_absolute_paths(self):
        from superior_sync.schemas import _is_safe_absolute_path
        self.assertTrue(_is_safe_absolute_path("/home/u/recv"))
        self.assertTrue(_is_safe_absolute_path("C:\\Users\\me\\recv"))
        self.assertFalse(_is_safe_absolute_path("../x"))
        self.assertFalse(_is_safe_absolute_path("relative/path"))

    @unittest.skipUnless(os.name == "nt", "Windows-only path expansion")
    def test_folder_payload_expands_windows_userprofile_tilde(self):
        from superior_sync.routers.sync import FolderPayload
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        with patch.dict(os.environ, {"USERPROFILE": home, "HOME": ""}):
            payload = FolderPayload(folder_path="~\\shared")
        self.assertEqual(
            os.path.normcase(payload.folder_path),
            os.path.normcase(os.path.join(home, "shared")),
        )


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TwoNodeSyncTests(unittest.TestCase):
    def test_two_local_nodes_sync_a_file_over_real_http(self):
        import uvicorn
        from superior_sync.app import SuperiorSyncApp
        from superior_sync.config import Config

        temp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp, True)

        def close_app(app):
            app.shutdown()

        def close_server(server, thread, listener):
            server.should_exit = True
            thread.join(timeout=5)
            listener.close()

        def make_node(name):
            root = os.path.join(temp, name, "shared")
            os.makedirs(root)
            config = Config(
                data_dir=os.path.join(temp, name, "data"),
                master_password="pw-for-two-node-test",
            )
            config.sync_folders = [root]
            config.invalidate_shares()
            ok, error, _ = config.update({"group_key": "g" * 32})
            if not ok:
                raise AssertionError(error)
            app = SuperiorSyncApp(config)
            self.addCleanup(close_app, app)
            return app, root

        def serve(app):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            app.config.active_port = port
            server = uvicorn.Server(uvicorn.Config(
                app.api,
                host="127.0.0.1",
                port=port,
                log_level="error",
                access_log=False,
                lifespan="off",
            ))
            server_errors = []

            def run_server():
                try:
                    server.run(sockets=[listener])
                except BaseException as exc:
                    server_errors.append(exc)

            thread = threading.Thread(
                target=run_server,
                daemon=True,
            )
            thread.start()
            self.addCleanup(close_server, server, thread, listener)
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not server.started:
                detail = str(server_errors[0]) if server_errors else "startup timed out"
                raise RuntimeError(f"local test server did not start: {detail}")
            return port

        node_a, root_a = make_node("a")
        node_b, root_b = make_node("b")
        _write(root_a, "from-a.txt", "two-node payload", age=10)
        share = next(key for key, path in node_a.config.shares().items() if path == root_a)
        node_a.engine.scan_share(share)
        port_a = serve(node_a)
        serve(node_b)

        ok, peer_id = node_b.engine.p2p_protocol.add_manual_peer(
            f"127.0.0.1:{port_a}", persist=False
        )
        self.assertTrue(ok, peer_id)
        result = node_b.engine.sync_share_with_peer(share, peer_id)

        self.assertTrue(result["success"], result)
        self.assertEqual(result["pulled"], 1)
        with open(os.path.join(root_b, "from-a.txt"), encoding="utf-8") as synced:
            self.assertEqual(synced.read(), "two-node payload")


if __name__ == "__main__":
    unittest.main()
