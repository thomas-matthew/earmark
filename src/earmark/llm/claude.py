"""Running Claude through the Agent SDK on my subscription (L4).

Every session runs with no built-in tools, no shell or file access, no project settings and an empty
working folder; the only tools are the read-only ones Earmark passes in."""
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import claude_agent_sdk
from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, TextBlock

CLI = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
API_KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
# Tool results (long pages, images) travel through the SDK as single JSON messages; its 1 MB default is too small.
MAX_MESSAGE_BYTES = 32 * 1024 * 1024


class ClaudeError(Exception):
    pass


@dataclass
class Reply:
    text: str
    turns: int
    seconds: float
    cost_usd: float | None


def _env() -> dict[str, str]:
    """Use the subscription login unless EARMARK_USE_API_KEY=1 asks for the API-key fallback.
    The CLI inherits this process's environment, so stray API keys are removed from it."""
    if os.environ.get("EARMARK_USE_API_KEY") != "1":
        for name in API_KEY_VARS:
            os.environ.pop(name, None)
    return {}


def options(system: str, cwd: str, model: str | None = None, mcp_servers: dict | None = None,
            allowed_tools: list[str] | None = None, max_turns: int = 1) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=system, model=model, tools=[], allowed_tools=allowed_tools or [], mcp_servers=mcp_servers or {},
        strict_mcp_config=True, setting_sources=[], permission_mode="dontAsk", max_turns=max_turns,
        cwd=cwd, cli_path=str(CLI), env=_env(),
        max_buffer_size=MAX_MESSAGE_BYTES,
    )


class Session:
    """A multi-turn conversation, so the writer can fix its own script after review (L3)."""

    def __init__(self, system: str, model: str | None = None, mcp_servers: dict | None = None,
                 allowed_tools: list[str] | None = None, max_turns: int = 1, on_tool=None):
        self._tmp = tempfile.TemporaryDirectory(prefix="earmark-")
        self._client = ClaudeSDKClient(options(system, self._tmp.name, model, mcp_servers, allowed_tools, max_turns))
        self._on_tool = on_tool

    async def __aenter__(self):
        await self._client.connect()
        return self

    async def __aexit__(self, *exc):
        try:
            await self._client.disconnect()
        finally:
            self._tmp.cleanup()

    async def ask(self, prompt: str) -> Reply:
        await self._client.query(prompt)
        texts, result = [], None
        async for message in self._client.receive_response():
            if isinstance(message, AssistantMessage):
                texts = [b.text for b in message.content if isinstance(b, TextBlock)] or texts
            elif isinstance(message, ResultMessage):
                result = message
        if result is None or result.is_error:
            raise ClaudeError(f"Claude session failed: {getattr(result, 'subtype', 'no result')}")
        text = (result.result or "\n".join(texts)).strip()
        if not text:
            raise ClaudeError("Claude returned an empty reply")
        return Reply(text, result.num_turns, result.duration_ms / 1000, result.total_cost_usd)


async def ask_once(system: str, prompt: str, model: str | None = None) -> Reply:
    async with Session(system, model=model) as session:
        return await session.ask(prompt)
