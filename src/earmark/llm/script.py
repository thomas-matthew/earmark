"""The script format the writer produces, and checks that need no model."""
import re
from dataclasses import dataclass


@dataclass
class Line:
    voice: str  # "N" narrator or "Q" quoted comment
    text: str


@dataclass
class Script:
    title: str | None
    lines: list[Line]

    def text(self) -> str:
        head = [f"T: {self.title}"] if self.title else []
        return "\n".join(head + [f"{l.voice}: {l.text}" for l in self.lines])


def parse(raw: str) -> Script:
    title, lines = None, []
    for row in raw.strip().splitlines():
        row = row.strip()
        if not row:
            continue
        match = re.match(r"^([TNQ]):\s*(.*)$", row)
        if not match:
            # Untagged text is narration; never drop words the writer produced.
            lines.append(Line("N", row))
            continue
        tag, text = match.groups()
        if tag == "T":
            title = title or text.strip()[:120]
        elif text.strip():
            lines.append(Line(tag, text.strip()))
    return Script(title, lines)


def normalize(text: str) -> str:
    return re.sub(r"\W+", " ", text).lower().strip()


def check(raw: str, sources: str) -> list[dict]:
    """Findings code can prove: untagged lines and quotes that are not word for word in the sources."""
    findings = []
    source = normalize(sources)
    for row in filter(str.strip, raw.strip().splitlines()):
        if not re.match(r"^[TNQ]:", row.strip()):
            findings.append({"severity": "low", "kind": "format", "script_text": row[:200],
                             "explanation": "Every line must start with T:, N: or Q:."})
    for line in parse(raw).lines:
        if line.voice == "Q" and normalize(line.text) not in source:
            findings.append({"severity": "high", "kind": "misquoted", "script_text": line.text[:300],
                             "explanation": "This Q: line is not found word for word in the sources. Quote exactly or narrate it instead."})
    return findings
