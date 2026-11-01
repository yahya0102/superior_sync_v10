#!/usr/bin/env python3
"""Superior Sync — entrypoint."""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
import threading
import webbrowser

import uvicorn

from .app import SuperiorSyncApp
from .config import Config, GroupKeyError, validate_sync_folder
from .integrations import install_autostart, remove_autostart
from .utils import (
    APP_NAME, APP_VERSION, HAS_CRYPTO, HAS_PSUTIL, HAS_WATCHFILES,
    atomic_write_bytes, get_local_ip, log, setup_logging,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="superior_sync",
                                description=f"{APP_NAME} v{APP_VERSION}")
    p.add_argument("--mode",
                   choices=["auto", "web", "cli", "all", "background"],
                   default="auto")
    p.add_argument("--port", type=int)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--data-dir")
    p.add_argument("--group-key")
    p.add_argument("--show-group-key", action="store_true",
                   help="print this node's group key (to pair another device "
                        "via --group-key) and exit")
    p.add_argument("--add-folder", action="append", default=[], metavar="PATH")
    p.add_argument("--add-peer", action="append", default=[], metavar="HOST:PORT")
    p.add_argument("--master-password")
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--no-sync", action="store_true")
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--install-autostart", action="store_true")
    p.add_argument("--remove-autostart", action="store_true")
    p.add_argument("--tls-cert")
    p.add_argument("--tls-key")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=APP_VERSION)
    return p


def _dependency_report() -> None:
    missing = []
    if not HAS_WATCHFILES:
        missing.append("watchfiles — native file watching")
    if not HAS_CRYPTO:
        missing.append("cryptography — transport & file encryption")
    if not HAS_PSUTIL:
        missing.append("psutil — full system/network metrics")
    if missing:
        log.info("Optional dependencies not installed:\n   " + "\n   ".join(missing))


def _security_warnings(args, config) -> None:
    warnings = []
    if args.host == "0.0.0.0" and not (args.tls_cert and args.tls_key):
        warnings.append("⚠️  Server exposed without TLS. Pass --tls-cert/--tls-key "
                        "or bind 127.0.0.1.")
    if not config.enable_encryption:
        warnings.append("⚠️  P2P transport encryption disabled — data flows in plaintext.")
    if not HAS_CRYPTO:
        warnings.append("⚠️  cryptography not installed — encryption unavailable.")
    if args.group_key and len(args.group_key) < 24:
        warnings.append("⚠️  Group key shorter than 24 characters — rejected by server.")
    if bool(args.tls_cert) ^ bool(args.tls_key):
        warnings.append("⚠️  Both --tls-cert and --tls-key are required for TLS; "
                        "falling back to plain HTTP.")
    if warnings:
        print()
        for w in warnings:
            print(w)
        print()


def _interactive_mode(args) -> None:
    print("\n🔧 Choose run mode:\n  1. Auto (web + browser)\n  "
          "2. Web + CLI\n  3. CLI only\n  4. Background")
    choice = input("Number (1-4): ").strip()
    args.mode = {"1": "auto", "2": "all", "3": "cli",
                 "4": "background"}.get(choice, "auto")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.install_autostart:
        print("✅ Autostart enabled:", install_autostart())
        return 0
    if args.remove_autostart:
        print("✅ Removed:", remove_autostart() or "nothing to remove")
        return 0

    try:
        master_password = (
            args.master_password or os.environ.get("SS_MASTER_PASSWORD")
        )
        config = Config(args.data_dir, master_password=master_password)
    except GroupKeyError as exc:
        print("❌", exc)
        return 2

    # [FIX] لم تكن هناك أي طريقة لقراءة مفتاح المجموعة (الـ API لا يعرضه و
    # config.json يخزّنه مشفّرًا بسر مرتبط بالجهاز)، فكان ربط جهاز ثانٍ مستحيلًا.
    if args.show_group_key:
        print(config.group_key)
        return 0
    setup_logging(config.data_dir, args.verbose)

    if args.interactive:
        _interactive_mode(args)

    # ---- Validate --port via Config.update() so the 1024–65535 range
    #      enforced by the config layer cannot be bypassed. -------------
    if args.port is not None:
        ok, err, _ = config.update({"server_port": int(args.port)})
        if not ok:
            print("❌", err or "invalid port")
            return 2

    if args.group_key:
        ok, err, _ = config.update({"group_key": args.group_key})
        if not ok:
            print("❌", err)
            return 2

    for folder in args.add_folder:
        try:
            validate_sync_folder(folder, config.data_dir)
        except ValueError:
            print(f"❌ Skipped unsafe sync folder: {folder}")
            continue
        if os.path.isdir(folder) and os.path.abspath(folder) not in config.sync_folders:
            config.sync_folders.append(os.path.abspath(folder))
    if args.add_folder:
        config.save()
    for addr in args.add_peer:
        if addr not in config.manual_peers:
            config.manual_peers.append(addr)
    if args.add_peer:
        config.save()

    # ---- Resolve the advertised LAN address *before* constructing the app,
    #      because TrustedHostMiddleware reads config.server_host at build
    #      time (inside SuperiorSyncApp.__init__ → _build_fastapi). ------
    config.server_host = get_local_ip()

    print("\n" + "=" * 70 + f"\n🚀 {APP_NAME} v{APP_VERSION}\n" + "=" * 70)
    _dependency_report()
    _security_warnings(args, config)

    app = SuperiorSyncApp(
        config,
        master_password,
    )
    first_pw = app.security.ensure_admin()
    pw_file = config.data_dir / "security" / "initial_admin_password.txt"
    if first_pw:
        atomic_write_bytes(pw_file, first_pw.encode("utf-8"), 0o600)

    # Optional subsystems that are not served by FastAPI
    if not args.no_sync:
        app.engine.start()
    app.analytics.start()
    app.start_background()

    # ---- TLS: BOTH cert and key are required for HTTPS. ---------------
    tls_ready = bool(args.tls_cert and args.tls_key)
    scheme = "https" if tls_ready else "http"
    ssl_kwargs: dict = {}
    if tls_ready:
        ssl_kwargs["ssl_certfile"] = args.tls_cert
        ssl_kwargs["ssl_keyfile"] = args.tls_key
        config._tls_active = True

    server = uvicorn.Server(uvicorn.Config(
        app.api,
        host=args.host,
        port=config.server_port,
        log_level="debug" if args.verbose else "info",
        loop="asyncio",
        access_log=False,
        **ssl_kwargs,
    ))
    config.active_port = config.server_port

    print(f"\n🌐 Local UI  : {scheme}://localhost:{config.server_port}")
    if args.host != "127.0.0.1":
        print(f"🌐 Network   : {scheme}://{config.server_host}:{config.server_port}")
    print(f"📁 Receive   : {config.receive_folder}")
    print(f"💾 Data dir  : {config.data_dir}")
    print(f"🆔 Node      : {config.node_id}  ({config.node_name})")
    print(f"🔐 P2P enc   : {'on' if config.enable_encryption and HAS_CRYPTO else 'OFF'}")
    print(f"🔒 TLS       : {'on' if config._tls_active else 'OFF'}")
    if first_pw:
        print(f"\n👤 First admin: admin / {first_pw}")
        print(f"   Saved at  : {pw_file}")
    print("\n🖥️  Ctrl+C to stop\n" + "=" * 70)

    if args.mode in ("auto", "web", "all") and config.auto_open_browser \
            and not args.no_browser:
        with contextlib.suppress(Exception):
            threading.Timer(
                1.0, webbrowser.open,
                args=(f"{scheme}://localhost:{config.server_port}/?lt="
                      f"{app.local_admin_token}",)
            ).start()

    try:
        if args.mode in ("cli", "all"):
            server_thread = threading.Thread(target=server.run, daemon=True)
            server_thread.start()
            from .cli import CommandLineInterface
            CommandLineInterface(app).run_cli()
            server.should_exit = True
        else:
            server.run()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n🧹 Shutting down…")
        with contextlib.suppress(Exception):
            app.shutdown()
        print("👋 Goodbye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())