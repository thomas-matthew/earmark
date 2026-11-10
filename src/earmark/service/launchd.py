"""Background service (O1) as two macOS LaunchAgents in ~/Library/LaunchAgents:

    dev.earmark.serve   the feed server, started at login and restarted if it stops
    dev.earmark.run     the daily run; launchd runs a missed time as soon as the Mac wakes
"""
import os
import plistlib
import subprocess
import sys
import time
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
        # Not "Background": macOS throttles those processes, which roughly halved narration speed.
        "ProcessType": "Standard",
        **extra,
    }


def _loaded(domain: str, label: str) -> bool:
    return subprocess.run(["launchctl", "print", f"{domain}/{label}"], capture_output=True).returncode == 0


def _bootout(domain: str, label: str, wait: float = 60) -> None:
    """Unload a job and wait until it is gone. Unloading is asynchronous while the job is still
    exiting, and loading the new version too early fails with an I/O error."""
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
    deadline = time.time() + wait
    while _loaded(domain, label) and time.time() < deadline:
        time.sleep(0.5)


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
        _bootout(domain, label)
        path.write_bytes(plistlib.dumps(content))
        subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
        written.append(path)
    return written


def uninstall() -> None:
    domain = f"gui/{os.getuid()}"
    for label in (SERVE, RUN):
        _bootout(domain, label)
        (AGENTS / f"{label}.plist").unlink(missing_ok=True)


def start_run_now() -> None:
    subprocess.run(["launchctl", "kickstart", f"gui/{os.getuid()}/{RUN}"], check=True)
