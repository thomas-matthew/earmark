"""The writer's read-only tools (L2). Each tool call is recorded, so the reviewer sees exactly the
sources the writer saw."""
import base64
from dataclasses import dataclass, field

from claude_agent_sdk import create_sdk_mcp_server, tool

from ..content.extract import fetch_bytes, read_page

SERVER = "earmark"
MAX_PAGE_CHARS = 120_000
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


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


def build(material: str, budget: Budget, sources: Sources):
    """Return (mcp server config, allowed tool names) for one item."""

    @tool("get_saved_item", "Get the saved item: its post, details and full discussion thread.", {})
    async def get_saved_item(args):
        if material not in sources.parts:
            sources.parts.insert(0, material)
        return _text(material)

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
        if page.images:
            body += "\n\nImages on the page:\n" + "\n".join(
                f"{i + 1}. {url}" + (f" (alt: {alt})" if alt else "") for i, (url, alt) in enumerate(page.images))
        return _text(body)

    @tool("view_image", "Look at an image from a page, to describe a chart, diagram or table.", {"url": str})
    async def view_image(args):
        if budget.images <= 0:
            return _text("Image limit reached.")
        budget.images -= 1
        try:
            data, content_type, _ = fetch_bytes(args["url"], "image/*", MAX_IMAGE_BYTES)
        except (OSError, ValueError):
            return _text("The image could not be loaded.")
        if content_type not in IMAGE_TYPES:
            return _text(f"Unsupported image type {content_type}.")
        sources.images_viewed.append(args["url"])
        return {"content": [{"type": "image", "data": base64.b64encode(data).decode(), "mimeType": content_type}]}

    tools = [get_saved_item, fetch_page, view_image]
    server = create_sdk_mcp_server(SERVER, tools=tools)
    return {SERVER: server}, [f"mcp__{SERVER}__{t.name}" for t in tools]
