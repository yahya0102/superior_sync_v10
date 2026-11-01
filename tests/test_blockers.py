"""Regression tests for the start-up blockers fixed in v4.1.1.

Run:  python -m unittest discover -s tests -v
(FastAPI-dependent tests are skipped automatically when fastapi is not installed.)
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "superior_sync"
sys.path.insert(0, str(ROOT))

HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None
try:
    from fastapi.testclient import TestClient  # noqa: F401
    HAS_TESTCLIENT = True
except Exception:  # pragma: no cover
    HAS_TESTCLIENT = False


def _py_files():
    return sorted(PKG.rglob("*.py"))


class StaticChecks(unittest.TestCase):
    def test_all_files_compile(self):
        for p in _py_files():
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))

    def test_require_permission_takes_exactly_one_argument(self):
        """Regression: 53 call sites passed 1 arg to a 2-arg function (TypeError at import)."""
        bad = []
        for p in _py_files():
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "require_permission":
                    if len(n.args) != 1 or n.keywords:
                        bad.append(f"{p.name}:{n.lineno}")
        self.assertEqual(bad, [])

    def test_cli_module_exists_for_main(self):
        self.assertTrue((PKG / "cli.py").exists())
        self.assertIn("from .cli import CommandLineInterface", (PKG / "main.py").read_text(encoding="utf-8"))

    def test_single_version_source(self):
        """The version is defined once in ``superior_sync/__init__.py``.

        * No other ``.py`` file may contain a hard-coded ``"X.Y.Z"`` literal.
        * ``APP_VERSION`` must equal ``__version__``.
        * ``pyproject.toml`` must not carry a static ``version = ...`` line;
          instead it declares ``dynamic = ["version"]`` and reads
          ``superior_sync.__version__``.
        """
        import superior_sync

        # 1. Only __init__.py may contain a version literal.
        for p in _py_files():
            if p.name == "__init__.py":
                continue
            self.assertNotRegex(
                p.read_text(encoding="utf-8"),
                r'"\d+\.\d+\.\d+"',
                f"hard-coded version in {p.name}",
            )

        # 2. The two public aliases must agree.
        self.assertEqual(superior_sync.APP_VERSION, superior_sync.__version__)
        self.assertRegex(superior_sync.__version__, r"^\d+\.\d+\.\d+$")

        # 3. pyproject.toml must defer to the package attribute.
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotRegex(
            pyproject,
            r'(?m)^\s*version\s*=\s*"\d+\.\d+\.\d+"',
            "pyproject.toml still contains a static version — remove it "
            "and rely on [tool.setuptools.dynamic].",
        )
        self.assertRegex(pyproject, r'dynamic\s*=\s*\[\s*"version"\s*\]')
        self.assertRegex(
            pyproject,
            r'version\s*=\s*\{\s*attr\s*=\s*"superior_sync\.__version__"\s*\}',
        )


class I18nChecks(unittest.TestCase):
    def setUp(self):
        from superior_sync import i18n
        self.i18n = i18n

    def test_every_key_used_in_code_is_defined(self):
        used = set()
        for p in _py_files():
            if p.name == "ui.py":
                # t(...) داخل ui.py هي دالة JavaScript لها جدول I18N خاص بها
                # (يُفحص في tests/test_fixes.py)، لا جدول بايثون.
                continue
            used |= set(re.findall(r'\bt\(\s*"([\w.]+)"', p.read_text(encoding="utf-8")))
        for lang, table in self.i18n._TRANSLATIONS.items():
            self.assertEqual(sorted(k for k in used if k not in table), [], f"missing in {lang}")

    def test_all_languages_have_same_keys(self):
        tr = self.i18n._TRANSLATIONS
        ref = set(tr["ar"])
        for lang, table in tr.items():
            self.assertEqual(ref ^ set(table), set(), f"key mismatch in {lang}")

    def test_format_placeholders_match_across_languages(self):
        tr = self.i18n._TRANSLATIONS
        fmt = lambda s: sorted(re.findall(r"{(\w+)}", s))
        for key, ar_text in tr["ar"].items():
            for lang, table in tr.items():
                self.assertEqual(fmt(table[key]), fmt(ar_text), f"{lang}:{key}")

    def test_language_switch(self):
        self.i18n.set_language("en")
        self.assertEqual(self.i18n.t("sync.folder_exists"), "Folder already added")
        self.i18n.set_language("ar")
        self.assertIn("مضاف", self.i18n.t("sync.folder_exists"))


class UiChecks(unittest.TestCase):
    def setUp(self):
        from superior_sync import ui
        self.ui = ui

    def test_token_is_injected_as_js_string_literal(self):
        for tok in ("", "abc-123_XYZ", '5x"</script>'):
            html = self.ui.render_html(tok)
            line = next(l for l in html.splitlines() if l.startswith("const LOCAL_TOKEN"))
            self.assertEqual(
                json.loads(
                    line.split("=", 1)[1].strip().rstrip(";").replace("\\u003c", "<")
                ),
                tok,
            )
            self.assertNotIn(self.ui.TOKEN_PLACEHOLDER, html)
            self.assertNotIn("</script>" + "x", html)

    def test_no_innerhtml_and_no_token_name_clobbering(self):
        """``LOCAL_TOKEN`` must be a single ``const`` declaration whose
        value is a JSON string literal — never a bare identifier splice
        like ``const tok-1`` that would break the surrounding script.
        """
        html = self.ui.render_html("tok-1")

        # No DOM-clobbering API usage anywhere in the UI.
        self.assertNotIn("innerHTML", html)

        # The auth header name must be sent, not silently renamed.
        self.assertIn("X-SS-Local-Token", html)

        # Exactly one ``const LOCAL_TOKEN`` declaration.
        self.assertEqual(html.count("const LOCAL_TOKEN"), 1)

        # The injected value must be a valid JS string literal, not a
        # raw identifier splice.
        self.assertIn('const LOCAL_TOKEN = "tok-1";', html)
        self.assertNotIn("const tok-1", html)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_embedded_javascript_parses(self):
        js = PKG / "ui_src" / "app.js"
        r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_ui_bundle_matches_sources(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_ui.py"), "--check"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class CliChecks(unittest.TestCase):
    def test_cli_commands_run_against_a_fake_app(self):
        """The CLI must be usable with a hand-rolled fake app.

        The fake supplies ``data_dir`` explicitly (the real interface used
        by :class:`CommandLineInterface.__init__`), and the test pins the
        language to ``en`` so the assertions do not depend on the ambient
        ``i18n`` default.
        """
        from superior_sync import i18n
        from superior_sync.cli import CommandLineInterface
        from io import StringIO
        from contextlib import redirect_stdout

        # Pin the language explicitly instead of relying on the default.
        previous_lang = i18n.get_language()
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, previous_lang)

        # Supply ``data_dir`` explicitly — the CLI stores its history
        # file there and would otherwise silently fall back to ``.``.
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        engine = types.SimpleNamespace(
            running=False,
            get_stats=lambda: {
                "node": {"name": "n", "id": "i"},
                "watcher_backend": "polling",
                "p2p_protocol": {"peers_online": 0},
                "sync_records_count": 3,
                "transfer": {"bytes_sent": 0, "bytes_received": 2048, "conflicts": 1},
                "sync_state": {},
            },
            p2p_protocol=types.SimpleNamespace(all_peers=lambda: []),
            conflict_resolver=types.SimpleNamespace(
                list_conflicts=lambda only_open=False: [],
            ),
        )
        config = types.SimpleNamespace(
            shares=lambda: {"received": "/x"},
            data_dir=tmpdir,
        )
        app = types.SimpleNamespace(engine=engine, config=config)

        cli = CommandLineInterface(app)
        buf = StringIO()
        with redirect_stdout(buf):
            cli.onecmd("status")
            cli.onecmd("peers")
            cli.onecmd("folders")
            cli.onecmd("conflicts")
            cli.onecmd("bogus")
            self.assertTrue(cli.onecmd("quit"))

        out = buf.getvalue()
        self.assertIn("2.00 KB", out)
        self.assertIn("(no peers)", out)
        self.assertIn("Unknown command", out)


@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class AuthWiring(unittest.TestCase):
    """Builds the real app object and exercises the dependency chain directly."""

    @classmethod
    def setUpClass(cls):
        from superior_sync.config import Config
        from superior_sync.app import SuperiorSyncApp
        cls.tmp = tempfile.mkdtemp()
        cfg = Config(cls.tmp)
        cfg.receive_folder = os.path.join(cls.tmp, "recv")
        os.makedirs(cfg.receive_folder, exist_ok=True)
        cls.app = SuperiorSyncApp(cfg)
        cls.app.security.ensure_admin()
        cls.app.security.create_user("bob", "bobpassword1", "user")
        cls.admin_tok = cls.app.security.generate_session_token("admin")
        cls.bob_tok = cls.app.security.generate_session_token("bob")

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _req(self, ip="10.0.0.5", headers=None):
        return types.SimpleNamespace(client=types.SimpleNamespace(host=ip), headers=headers or {})

    def _principal(self, ip="10.0.0.5", headers=None, **kw):
        from superior_sync import dependencies as dep
        kw.setdefault("authorization", None); kw.setdefault("ss_session", None); kw.setdefault("x_ss_local_token", None)
        return asyncio.run(dep.get_principal(self._req(ip, headers), **kw))

    def _check(self, perm, principal):
        from superior_sync import dependencies as dep
        from fastapi import HTTPException
        try:
            return asyncio.run(dep.require_permission(perm)(principal)).name
        except HTTPException as exc:
            return exc.status_code

    def test_dependencies_are_wired(self):
        from superior_sync import dependencies as dep
        self.assertIs(dep._registry["limiter"], self.app.rate_limiter)
        self.assertIs(dep.get_sync_engine(), self.app.engine)

    def test_hub_owns_subsystems(self):
        """``app.analytics`` / ``app.notifier`` / ``app.cloud`` must be the
        hub's instances, not separate copies — otherwise the ErrorLog,
        circuit breakers and threshold alerts stay disconnected."""
        self.assertIs(self.app.analytics, self.app.hub.analytics)
        self.assertIs(self.app.notifier, self.app.hub.notifier)
        self.assertIs(self.app.cloud, self.app.hub.cloud)
        self.assertIs(self.app.errors, self.app.hub.errors)

    def test_trusted_hosts_have_loopback_fallback_without_network(self):
        with patch("superior_sync.app.get_local_ips", side_effect=OSError("no route")):
            hosts = self.app._trusted_hosts()
        self.assertIn("localhost", hosts)
        self.assertIn("127.0.0.1", hosts)

    def test_anonymous_is_401(self):
        self.assertEqual(self._check("read", self._principal()), 401)

    def test_roles_and_permissions(self):
        adm = self._principal(authorization="Bearer " + self.admin_tok)
        bob = self._principal(ss_session=self.bob_tok)
        self.assertEqual(adm.role, "admin")
        self.assertEqual(self._check("manage_users", adm), "admin")
        self.assertEqual(self._check("read", bob), "bob")
        self.assertEqual(self._check("delete", bob), 403)
        self.assertEqual(self._check("manage_users", bob), 403)

    def test_local_token_only_from_direct_loopback(self):
        tok = self.app.local_admin_token
        self.assertEqual(self._principal("127.0.0.1", x_ss_local_token=tok).name, "local")
        self.assertFalse(self._principal("10.0.0.5", x_ss_local_token=tok).authenticated)
        self.assertFalse(self._principal("127.0.0.1", {"x-forwarded-for": "1.2.3.4"}, x_ss_local_token=tok).authenticated)
        self.assertFalse(self._principal("127.0.0.1", x_ss_local_token="wrong").authenticated)

    def test_forwarded_client_ip_requires_a_trusted_proxy(self):
        from superior_sync import dependencies as dep
        old = dep._registry["trusted_proxies"]
        dep._registry["trusted_proxies"] = ["10.0.0.0/8"]
        try:
            proxied = self._req(
                "10.0.0.2",
                {"x-forwarded-for": "198.51.100.20, 10.0.0.3"},
            )
            direct = self._req(
                "192.0.2.4", {"x-forwarded-for": "127.0.0.1"}
            )
            self.assertEqual(dep._client_ip(proxied), "198.51.100.20")
            self.assertEqual(dep._client_ip(direct), "192.0.2.4")
        finally:
            dep._registry["trusted_proxies"] = old

    def test_origin_check_uses_forwarded_scheme_only_from_trusted_proxy(self):
        from superior_sync import dependencies as dep
        old = dep._registry["trusted_proxies"]
        dep._registry["trusted_proxies"] = ["10.0.0.0/8"]
        try:
            request = types.SimpleNamespace(
                client=types.SimpleNamespace(host="10.0.0.2"),
                headers={
                    "origin": "https://sync.example.test",
                    "x-forwarded-proto": "https",
                },
                url="http://sync.example.test/api/config",
            )
            self.assertTrue(dep._origin_matches_request(request))
            request.headers["origin"] = "https://attacker.example"
            self.assertFalse(dep._origin_matches_request(request))
            request.client.host = "192.0.2.4"
            request.headers["origin"] = "https://sync.example.test"
            self.assertFalse(dep._origin_matches_request(request))
        finally:
            dep._registry["trusted_proxies"] = old

    def test_local_token_through_proxy_requires_loopback_forwarded_client(self):
        from superior_sync import dependencies as dep
        old = dep._registry["trusted_proxies"]
        dep._registry["trusted_proxies"] = ["10.0.0.0/8"]
        try:
            self.assertEqual(
                self._principal(
                    "10.0.0.2",
                    {"x-forwarded-for": "127.0.0.1"},
                    x_ss_local_token=self.app.local_admin_token,
                ).name,
                "local",
            )
            self.assertFalse(
                self._principal(
                    "10.0.0.2",
                    {"x-forwarded-for": "198.51.100.20"},
                    x_ss_local_token=self.app.local_admin_token,
                ).authenticated
            )
        finally:
            dep._registry["trusted_proxies"] = old

    def test_fire_webhook_pushes_to_sse_clients(self):
        import queue
        q = queue.Queue()
        self.app._sse_clients.append(q)
        try:
            self.app.fire_webhook("file_uploaded", {"path": "a.txt"})
            self.assertIn(b"event: file_uploaded", q.get_nowait())
        finally:
            self.app._sse_clients.remove(q)

    def test_hub_events_reach_sse_clients(self):
        """Errors routed through the hub must be broadcast over SSE."""
        import queue
        q = queue.Queue()
        self.app._sse_clients.append(q)
        try:
            self.app.hub.emit("error_logged", {"id": "x", "message": "boom"})
            payload = q.get_nowait()
            self.assertIn(b"event: error_logged", payload)
            self.assertIn(b'"id": "x"', payload)
        finally:
            self.app._sse_clients.remove(q)

    def test_admin_users_router_is_mounted(self):
        from superior_sync.routers import auth
        included = getattr(self.app.api, "included", None)
        if included is not None:  # fastapi stub used in offline verification
            self.assertIn(auth.admin_router, included)
        else:
            paths = {getattr(r, "path", "") for r in self.app.api.routes}
            self.assertIn("/api/admin/users", paths)


@unittest.skipUnless(HAS_TESTCLIENT, "fastapi.testclient/httpx not installed")
class HttpEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from superior_sync.config import Config
        from superior_sync.app import SuperiorSyncApp
        cls.tmp = tempfile.mkdtemp()
        cfg = Config(cls.tmp)
        cfg.receive_folder = os.path.join(cls.tmp, "recv")
        os.makedirs(cfg.receive_folder, exist_ok=True)
        cls.app = SuperiorSyncApp(cfg)
        cls.admin_pw = cls.app.security.ensure_admin()
        cls.client = TestClient(
            cls.app.api,
            base_url="http://localhost",
            headers={"X-Requested-With": "SuperiorSync"},
        )

    @classmethod
    def tearDownClass(cls):
        cls.app.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_routes_require_login(self):
        self.assertEqual(self.client.get("/api/files").status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").json(), {"login_required": True})

    def test_login_me_files_and_admin_users(self):
        r = self.client.post("/api/auth/login", json={"username": "admin", "password": self.admin_pw})
        self.assertEqual(r.status_code, 200, r.text)
        tok = r.json()["token"]
        h = {"Authorization": "Bearer " + tok}
        self.assertEqual(self.client.get("/api/auth/me", headers=h).json()["role"], "admin")
        self.assertEqual(self.client.get("/api/files", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/admin/users", headers=h).status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/api/files", headers=h).status_code, 401)

    def test_config_endpoint_accepts_browser_and_trusted_host_fields(self):
        token = self.app.security.generate_session_token("admin")
        client = TestClient(
            self.app.api,
            base_url="http://localhost",
            client=("127.0.0.7", 50000),
            headers={"X-Requested-With": "SuperiorSync"},
        )
        self.addCleanup(client.close)
        response = client.post(
            "/api/config",
            json={
                "auto_open_browser": False,
                "trusted_hosts": [" example.test ", "", "*"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(self.app.config.auto_open_browser)
        self.assertEqual(self.app.config.trusted_hosts, ["example.test"])

    def test_rate_limit_message_uses_requested_language(self):
        # The login bucket holds 30 tokens/min. Send 35 requests to exhaust it.
        client = TestClient(
            self.app.api,
            base_url="http://localhost",
            client=("127.0.0.5", 50000),
            headers={"X-Requested-With": "SuperiorSync"},
        )
        r = None
        for _ in range(35):
            r = client.post(
                "/api/auth/login",
                json={"username": "x", "password": "y"},
                headers={"Accept-Language": "en"},
            )
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["error"], "Rate limit exceeded, try again later")

    def test_csrf_rejects_post_without_requested_with_header(self):
        client = TestClient(
            self.app.api,
            base_url="http://localhost",
            client=("127.0.0.6", 50000),
        )
        response = client.post(
            "/api/auth/login",
            json={"username": "x", "password": "y"},
            headers={"Accept-Language": "en"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Insufficient permissions")

    def test_csrf_rejects_cross_origin_state_change(self):
        response = self.client.post(
            "/api/auth/login",
            json={"username": "x", "password": "not-a-real-password"},
            headers={
                "X-Requested-With": "SuperiorSync",
                "Origin": "http://attacker.example",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_cloud_route_keeps_event_loop_responsive(self):
        from superior_sync.routers.cloud import list_cloud

        started = threading.Event()
        release = threading.Event()
        heartbeat = threading.Event()

        class BlockingCloud:
            def list_cloud_files(self, service, path):
                started.set()
                release.wait(1.5)
                return {"success": True, "files": [], "yielded": heartbeat.is_set()}

        request = types.SimpleNamespace(
            app=types.SimpleNamespace(
                state=types.SimpleNamespace(
                    superior=types.SimpleNamespace(cloud=BlockingCloud())
                )
            )
        )

        async def exercise_route():
            async def keep_loop_alive():
                await asyncio.to_thread(started.wait, 1)
                heartbeat.set()
                release.set()

            watchdog = threading.Timer(1.5, release.set)
            watchdog.start()
            task = asyncio.create_task(keep_loop_alive())
            try:
                result = await list_cloud(request, "dropbox", "/")
                await task
                return result
            finally:
                watchdog.cancel()

        result = asyncio.run(exercise_route())
        self.assertTrue(result["yielded"])

    def test_ui_served_with_valid_token_literal(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertRegex(r.text, r'const LOCAL_TOKEN = "[^"]*";')

    def test_health(self):
        self.assertEqual(self.client.get("/health").json()["status"], "healthy")


if __name__ == "__main__":
    unittest.main()