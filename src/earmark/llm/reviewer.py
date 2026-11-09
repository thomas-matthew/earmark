"""The reviewer (L3): a separate session with no tools that only reports issues. It never edits."""
import json

from . import prompts
from .claude import ClaudeError, ask_once


async def review(script: str, sources: str) -> list[dict]:
    reply = await ask_once(prompts.REVIEWER, f"<source>\n{sources}\n</source>\n\n<script>\n{script}\n</script>")
    raw = reply.text
    try:
        findings = json.loads(raw[raw.index("["): raw.rindex("]") + 1])
    except ValueError as exc:
        raise ClaudeError("review reply was not a JSON list") from exc
    return [f for f in findings if isinstance(f, dict)]


def worth_fixing(findings: list[dict]) -> list[dict]:
    return [f for f in findings if str(f.get("severity", "")).lower() in ("high", "medium")]
