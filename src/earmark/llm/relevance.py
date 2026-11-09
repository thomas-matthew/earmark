"""The relevance check for Reddit and X items (D5): Sonnet judges one item on its full thread.
A skip that Sonnet is unsure about counts as include, enforced here rather than trusted to the prompt."""
import json
from dataclasses import dataclass

from . import prompts
from .claude import ClaudeError, ask_once

MODEL = "sonnet"


@dataclass
class Decision:
    include: bool
    confidence: str
    reason: str
    model_said: str


def parse(raw: str) -> Decision:
    try:
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError as exc:
        raise ClaudeError("relevance reply was not JSON") from exc
    said = str(data.get("decision", "include")).lower()
    confidence = str(data.get("confidence", "low")).lower()
    reason = str(data.get("reason", ""))[:200]
    include = said != "skip" or confidence != "high"
    if said == "skip" and include:
        reason = f"Included because the skip was low confidence: {reason}"
    return Decision(include, confidence, reason, said)


async def judge(title: str, source: str, material: str) -> Decision:
    reply = await ask_once(prompts.RELEVANCE, f"Source: {source}\nTitle: {title}\n\n{material}", model=MODEL)
    return parse(reply.text)
