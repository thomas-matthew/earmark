"""The writer agent (L2) with one review-and-fix round (L3).

The writer gathers sources with read-only tools and writes the script. A separate reviewer reports
issues; code adds the ones it can prove (such as misquotes). The writer then fixes them in the same
session, so it keeps its context. Anything still found after the fix is returned for logging."""
import json
from dataclasses import dataclass

from . import prompts, reviewer, script, tools
from .claude import ClaudeError, Session

EXTRA_PAGES = 3
MAX_TURNS = 30


@dataclass
class Result:
    script: script.Script
    remaining: list[dict]
    sources: str


def system_prompt(source_label: str, media: dict | None) -> str:
    media_rule = ""
    if media:
        minutes = round((media.get("seconds") or 0) / 60) or "an unknown number of"
        media_rule = prompts.MEDIA_RULE.format(media_title=media.get("title") or "a recording", media_minutes=minutes)
    return prompts.WRITER.format(extra_pages=EXTRA_PAGES, source=source_label, media_rule=media_rule)


def brief(row, source_label: str, media: dict | None) -> str:
    lines = [f"Create the script for this item saved from {source_label}.", f"Title: {row['title']}",
             f"Item address: {row['url']}"]
    if row["link"]:
        lines.append(f"Linked page: {row['link']}")
    if media:
        lines.append(f"The linked recording: {json.dumps({k: media.get(k) for k in ('title', 'channel', 'description')})}")
    return "\n".join(lines)


async def write(row, material: str, source_label: str, media: dict | None = None, log=print) -> Result:
    sources = tools.Sources()
    servers, allowed = tools.build(material, tools.Budget(pages=1 + EXTRA_PAGES + (1 if row["link"] else 0)), sources)

    async with Session(system_prompt(source_label, media), mcp_servers=servers, allowed_tools=allowed,
                       max_turns=MAX_TURNS) as writer:
        draft = (await writer.ask(brief(row, source_label, media))).text
        if not sources.parts:
            raise ClaudeError("the writer never read the saved item")
        log(f"  draft: {len(draft)} characters from {len(sources.parts)} sources, {len(sources.images_viewed)} images viewed")

        findings = script.check(draft, sources.text()) + await reviewer.review(draft, sources.text())
        to_fix = reviewer.worth_fixing(findings)
        log(f"  review: {len(findings)} issues, {len(to_fix)} to fix")
        final = draft
        if to_fix:
            final = (await writer.ask(prompts.FIX.format(issues=json.dumps(to_fix, indent=1, ensure_ascii=False)))).text

    remaining = []
    if to_fix:
        remaining = reviewer.worth_fixing(script.check(final, sources.text()) + await reviewer.review(final, sources.text()))
        log(f"  after fixing: {len(remaining)} issues remain")
    parsed = script.parse(final)
    if not parsed.lines:
        raise ClaudeError("the script was empty")
    return Result(parsed, remaining, sources.text())
