"""Superior Sync integration subsystem."""

from __future__ import annotations

from ._shared import *


def _launch_argv(extra: list[str]) -> list[str]:
    exe = [sys.executable] if not getattr(sys, "frozen", False) else []
    return exe + [os.path.abspath(sys.argv[0])] + extra


def _autostart_path() -> Path | None:
    system = platform.system()
    if system == "Windows":
        return (Path(os.environ.get("APPDATA", ""))
                / "Microsoft/Windows/Start Menu/Programs/Startup"
                / "SuperiorSync.cmd")
    if system == "Darwin":
        return Path.home() / "Library/LaunchAgents/com.superiorsync.plist"
    return Path.home() / ".config/systemd/user/superior-sync.service"


def autostart_status() -> dict:
    path = _autostart_path()
    if path is None:
        return {"supported": False, "installed": False, "path": None}
    installed = path.exists()
    active = False
    if platform.system() == "Linux" and installed:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-enabled", "superior-sync.service"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            active = result.stdout.strip() == "enabled"
        except (OSError, subprocess.SubprocessError):
            pass
    return {"supported": True, "installed": installed, "active": active,
            "path": str(path)}


def install_autostart(extra_args: tuple[str, ...] = ("--mode", "background")) -> str | None:
    system = platform.system()
    argv = _launch_argv(list(extra_args))

    if system == "Windows":
        path = _autostart_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        pyw = Path(sys.executable).with_name("pythonw.exe")
        launcher = [str(pyw)] if pyw.exists() else [sys.executable]
        cmd = " ".join(f'"{a}"' for a in (launcher + argv[1:]))
        path.write_text(f"@echo off\r\nstart \"\" /min {cmd}\r\n", encoding="utf-8")
        return str(path)

    if system == "Darwin":
        path = _autostart_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        args = "".join(f"<string>{a}</string>" for a in argv)
        path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<plist version="1.0"><dict><key>Label</key>'
            '<string>com.superiorsync</string>'
            f'<key>ProgramArguments</key><array>{args}</array>'
            '<key>RunAtLoad</key><true/>'
            '<key>KeepAlive</key><true/></dict></plist>',
            encoding="utf-8",
        )
        return str(path)

    path = _autostart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Unit]\nDescription=Superior Sync Ultimate\n"
        "After=network-online.target\n\n[Service]\n"
        f"ExecStart={' '.join(shlex.quote(a) for a in argv)}\n"
        "Restart=on-failure\nRestartSec=10\n\n[Install]\n"
        "WantedBy=default.target\n",
        encoding="utf-8",
    )
    for cmd in (["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", "superior-sync.service"]):
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(cmd, timeout=20, check=False)
    return str(path)


def remove_autostart() -> str | None:
    system = platform.system()
    path = _autostart_path()
    if path is None:
        return None
    if system == "Linux":
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "superior-sync.service"],
                timeout=20, check=False,
            )
    if path.exists():
        path.unlink()
        return str(path)
    return None


# ==================================================================
# IntegrationHub — واجهة موحّدة تربط كل الأنظمة
# ==================================================================
