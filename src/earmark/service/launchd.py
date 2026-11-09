"""Background service (O1) as two macOS LaunchAgents in ~/Library/LaunchAgents:

    dev.earmark.serve   the feed server, started at login and restarted if it stops
    dev.earmark.run     the daily run; launchd runs a missed time as soon as the Mac wakes
"""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from ..config import PROJECT, Settings

AGENTS = Path.home() / "Library" / "LaunchAgents"
SERVE, RUN = "dev.earmark.serve", "dev.earmark.run"


def _plist(label: str, args: list[str], logs: Path, extra: dict) -> dict:
    return {
        "Label": label,
        "ProgramArguments": [sys.executable, "-m", "earmark", *args],
        "WorkingDirectory": str(PROJECT),
        "EnvironmentVariables": {"HF_HOME": os.environ["HF_HOME"], "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                                 "PYTHONUNBUFFERED": "1"},
        "StandardOutPath": str(logs / f"{args[0]}.log"),
        "StandardErrorPath": str(logs / f"{args[0]}.log"),
        "ProcessType": "Background" if args[0] == "run" else "Standard",
        **extra,
    }


def install(settings: Settings, hour: int, minute: int) -> list[Path]:
    logs = settings.data / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    AGENTS.mkdir(parents=True, exist_ok=True)
    plists = {
        SERVE: _plist(SERVE, ["serve"], logs, {"RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 30}),
        RUN: _plist(RUN, ["run"], logs, {"StartCalendarInterval": {"Hour": hour, "Minute": minute}}),
    }
    domain = f"gui/{os.getuid()}"
    written = []
    for label, content in plists.items():
        path = AGENTS / f"{label}.plist"
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
        path.write_bytes(plistlib.dumps(content))
        subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
        written.append(path)
    return written


def uninstall() -> None:
    domain = f"gui/{os.getuid()}"
    for label in (SERVE, RUN):
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
        (AGENTS / f"{label}.plist").unlink(missing_ok=True)


def start_run_now() -> None:
    subprocess.run(["launchctl", "kickstart", f"gui/{os.getuid()}/{RUN}"], check=True)
