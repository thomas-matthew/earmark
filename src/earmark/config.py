"""Paths, settings and secrets. Secrets come from `.env` in the project folder and are never logged."""
import os
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT / ".env"

# Models are shared across projects. launchd does not read shell profiles, so set it here too.
os.environ.setdefault("HF_HOME", str(Path.home() / "Dev" / "labs" / "huggingface"))


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if match and not line.lstrip().startswith("#"):
                values[match.group(1)] = match.group(2).strip("\"'")
    return values


@dataclass(frozen=True)
class Settings:
    data: Path
    base_url: str
    bind_host: str
    port: int
    secrets: dict[str, str]
    ntfy_topic: str | None
    ntfy_server: str
    x_cost_per_read: float
    x_monthly_alert: float
    retention_days: int

    @property
    def feed_dir(self) -> Path:
        return self.data / "feed"

    @property
    def db_path(self) -> Path:
        return self.data / "earmark.db"

    @property
    def x_token_path(self) -> Path:
        return self.data / "x_token.json"

    @property
    def voices_dir(self) -> Path:
        return self.data / "voices"

    @property
    def work_dir(self) -> Path:
        return self.data / "work"

    def secret(self, name: str) -> str | None:
        return self.secrets.get(name) or os.environ.get(name)


def load(env_file: Path = ENV_FILE) -> Settings:
    env = {**load_env(env_file), **{k: v for k, v in os.environ.items() if k.startswith("EARMARK_")}}
    if env.get("EARMARK_USE_API_KEY") == "1":
        # Fallback (L4): hand the API key to the Claude CLI, which reads it from the environment.
        os.environ["EARMARK_USE_API_KEY"] = "1"
        if env.get("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = env["ANTHROPIC_API_KEY"]
    port = int(env.get("EARMARK_PORT", "8765"))
    host = env.get("EARMARK_HOST", "127.0.0.1")
    return Settings(
        data=Path(env.get("EARMARK_DATA", PROJECT / "data")),
        base_url=env.get("EARMARK_BASE_URL", f"http://{host}:{port}").rstrip("/"),
        bind_host=host,
        port=port,
        secrets=env,
        ntfy_topic=env.get("NTFY_TOPIC") or None,
        ntfy_server=env.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
        # X pay-per-use bills per post read. Earmark counts reads and estimates spend from this rate.
        x_cost_per_read=float(env.get("X_COST_PER_READ", "0.005")),
        x_monthly_alert=float(env.get("X_MONTHLY_ALERT", "5")),
        retention_days=int(env.get("EARMARK_RETENTION_DAYS", "30")),
    )
