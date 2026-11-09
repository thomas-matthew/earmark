"""What every source shares. A source module exposes:

    NAME                          short id used in item ids and the database
    LABEL                         how the source is named in episodes
    FILTERED                      whether its items pass the relevance check (D5)
    fetch(ctx, known, first_run)  -> list[Item], newest saved first, strictly read-only (D3)
    material(ctx, row)            -> str, the full post and thread for the relevance check and writer
"""
import html
import re
from dataclasses import dataclass
from sqlite3 import Connection

from ..config import Settings


@dataclass
class Context:
    settings: Settings
    db: Connection


def strip_html(markup: str | None) -> str:
    text = re.sub(r"<p>", "\n\n", markup or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()
