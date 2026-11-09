"""Push alerts through ntfy (O2). Messages stay generic: no secrets and no saved content,
because the public ntfy server is a third party."""
import sys
import urllib.request

from ..config import Settings


def send(settings: Settings, title: str, message: str, priority: str = "default") -> bool:
    print(f"ALERT: {title}: {message}", file=sys.stderr, flush=True)
    if not settings.ntfy_topic:
        return False
    request = urllib.request.Request(
        f"{settings.ntfy_server}/{settings.ntfy_topic}",
        data=message.encode(),
        headers={"Title": title, "Priority": priority, "Tags": "headphones"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15):
            return True
    except OSError as exc:  # an alert failing must never stop a run
        print(f"ntfy failed: {exc}", file=sys.stderr)
        return False
