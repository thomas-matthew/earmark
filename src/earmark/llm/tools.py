"""The writer's read-only tools (L2). Each tool call is recorded, so the reviewer sees exactly the
sources the writer saw."""
import base64
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..content.extract import fetch_bytes, read_page

SERVER = "earmark"
# The CLI refuses tool results over about 25,000 tokens. Longer text is saved as a file in the writer's
# folder and the tool returns its start plus directions, so the writer reads the rest in parts.
INLINE_CHARS = 40_000
MAX_PAGE_CHARS = 400_000
WRAP_CHARS = 1_000  # Read cuts lines longer than 2,000 characters, so long comments are wrapped
READ_LINES = 300
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024
MAX_IMAGE_BYTES = 3 * 1024 * 1024  # after shrinking; keeps tool messages well inside limits
MAX_IMAGE_SIDE = 1568  # Claude scales larger images down to about this anyway
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def shrink(data: bytes, content_type: str) -> tuple[bytes, str]:
    """Scale an image to at most MAX_IMAGE_SIDE pixels with macOS's built-in sips. Photos stay JPEG;
    everything else becomes PNG, which keeps chart text sharp."""
    kind = "jpeg" if content_type == "image/jpeg" else "png"
    with tempfile.TemporaryDirectory() as tmp:
        source, target = Path(tmp) / "in", Path(tmp) / f"out.{kind}"
        source.write_bytes(data)
        subprocess.run(["/usr/bin/sips", "-s", "format", kind, "-Z", str(MAX_IMAGE_SIDE), str(source), "--out", str(target)],
                       check=True, capture_output=True, timeout=60)
        return target.read_bytes(), f"image/{kind}"


@dataclass
class Budget:
    pages: int
    images: int = 8


@dataclass
class Sources:
    """Everything the writer read, in order."""
    parts: list[str] = field(default_factory=list)
    images_viewed: list[str] = field(default_factory=list)

    def text(self) -> str:
        viewed = "".join(f"\n[The writer viewed an image at {url}; claims about it cannot be checked here.]"
                         for url in self.images_viewed)
        return "\n\n".join(self.parts) + viewed


def _text(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def wrap(text: str) -> str:
    """Split long lines at word boundaries, keeping each line's indent, so no line is cut on reading."""
    out = []
    for line in text.splitlines():
        if len(line) <= WRAP_CHARS:
            out.append(line)
            continue
        indent = line[:len(line) - len(line.lstrip())]
        out += textwrap.wrap(line, WRAP_CHARS, subsequent_indent=indent + "  ", break_long_words=True)
    return "\n".join(out) + "\n"


def inline_or_file(text: str, folder: Path, name: str, what: str) -> str:
    """Return short text as is. Save long text to folder/name and return its start with directions."""
    if len(text) <= INLINE_CHARS:
        return text
    path = folder / name
    content = wrap(text)
    path.write_text(content, encoding="utf-8")
    lines = content.count("\n")
    head = text[:text.rfind("\n", 0, INLINE_CHARS // 2) + 1 or INLINE_CHARS // 2]
    return (f"{head}\n[{what} is too long to return at once: {len(text):,} characters. The complete text, "
            f"including the part above, is saved in the file {path} ({lines:,} lines). Read all of it with "
            f"the Read tool in parts of about {READ_LINES} lines (using offset and limit) before writing. "
            f"Use Grep on that file to find comments on a topic or by a person.]")


def build(material: str, budget: Budget, sources: Sources, folder: Path):
    """Return (mcp server config, allowed tool names) for one item. Long text goes into folder."""

    @tool("get_saved_item", "Get the saved item: its post, details and full discussion thread.", {})
    async def get_saved_item(args):
        if material not in sources.parts:
            sources.parts.insert(0, material)
        return _text(inline_or_file(material, folder, "saved_item.txt", "The saved item"))

    @tool("fetch_page", "Fetch a public web page and return its main text and a numbered list of its images.", {"url": str})
    async def fetch_page(args):
        if budget.pages <= 0:
            return _text("Page limit reached. Write the script with what you have.")
        budget.pages -= 1
        page = read_page(args["url"])
        if page is None:
            return _text("The page could not be read. It may need a browser, be paywalled or not exist.")
        text = page.text
        cut = len(text) > MAX_PAGE_CHARS
        body = f"<page url={page.url!r} title={page.title!r}>\n{text[:MAX_PAGE_CHARS]}\n</page>"
        if cut:
            body += f"\n[Page text was cut after {MAX_PAGE_CHARS} characters.]"
        sources.parts.append(body)
        reply = inline_or_file(body, folder, f"page_{len(sources.parts)}.txt", "This page")
        if page.images:
            reply += "\n\nImages on the page:\n" + "\n".join(
                f"{i + 1}. {url}" + (f" (alt: {alt})" if alt else "") for i, (url, alt) in enumerate(page.images))
        return _text(reply)

    @tool("view_image", "Look at an image from a page, to describe a chart, diagram or table.", {"url": str})
    async def view_image(args):
        if budget.images <= 0:
            return _text("Image limit reached.")
        budget.images -= 1
        try:
            data, content_type, _ = fetch_bytes(args["url"], "image/*", MAX_DOWNLOAD_BYTES)
        except (OSError, ValueError):
            return _text("The image could not be loaded.")
        if content_type not in IMAGE_TYPES:
            return _text(f"Unsupported image type {content_type}.")
        try:
            data, content_type = shrink(data, content_type)
        except (OSError, subprocess.SubprocessError):
            return _text("The image could not be processed.")
        if len(data) > MAX_IMAGE_BYTES:
            return _text("The image is too large to view.")
        sources.images_viewed.append(args["url"])
        return {"content": [{"type": "image", "data": base64.b64encode(data).decode(), "mimeType": content_type}]}

    tools = [get_saved_item, fetch_page, view_image]
    server = create_sdk_mcp_server(SERVER, tools=tools)
    return {SERVER: server}, [f"mcp__{SERVER}__{t.name}" for t in tools]
