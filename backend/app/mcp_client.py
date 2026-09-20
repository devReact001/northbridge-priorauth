"""A small synchronous MCP client, so the (synchronous) workflow can call MCP tools.

McpToolbox starts an MCP server as a child process (stdio transport) and keeps one session open on a
background event loop, so every tool call is a plain blocking function call. InProcessToolbox offers the same
interface over plain Python functions, for tests that do not need a subprocess.
"""

import asyncio
import json
import logging
import threading
from typing import Any, Callable, Optional, Protocol

log = logging.getLogger("priorauth.mcp")


def leaf_errors(exc: BaseException) -> str:
    """The real errors inside nested ExceptionGroups (anyio wraps them), one line each."""
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(leaf_errors(e) for e in exc.exceptions)
    return f"{type(exc).__name__}: {exc}"


class ToolError(Exception):
    """The MCP server reported an error for a tool call."""


class Toolbox(Protocol):
    name: str

    def list_tools(self) -> list[dict]: ...

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]: ...

    def close(self) -> None: ...


class InProcessToolbox:
    """Same interface as McpToolbox, backed by a function. Used by tests and by simple embeddings."""

    def __init__(self, name: str, specs: list[dict], handler: Callable[[str, dict], dict]):
        self.name, self._specs, self._handler = name, specs, handler

    def list_tools(self) -> list[dict]:
        return list(self._specs)

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return self._handler(tool, args)

    def close(self) -> None:
        pass


def _attr(obj, *names, default=None):
    """First attribute that exists. The MCP SDK renamed camelCase fields to snake_case in 2.x."""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def _parse(result) -> dict[str, Any]:
    text = " ".join(getattr(c, "text", "") for c in result.content if getattr(c, "type", "") == "text")
    if _attr(result, "isError", "is_error", default=False):
        raise ToolError(text or "tool call failed")
    structured = _attr(result, "structuredContent", "structured_content")
    if isinstance(structured, dict):
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    return json.loads(text)


class McpToolbox:
    def __init__(self, name: str, command: str, args: list[str], env: Optional[dict] = None,
                 cwd: Optional[str] = None, call_timeout: float = 30.0):
        from mcp import StdioServerParameters

        self.name = name
        self._params = StdioServerParameters(command=command, args=args, env=env, cwd=cwd)
        self._timeout = call_timeout
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._session = None
        self._stop: Optional[asyncio.Event] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None
        self._tools: Optional[list[dict]] = None

    # ---- lifecycle: one background thread owns the event loop and the child process ----

    def start(self, timeout: float = 30.0) -> "McpToolbox":
        self._thread = threading.Thread(target=self._run, name=f"mcp-{self.name}", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise TimeoutError(f"MCP server '{self.name}' did not start within {timeout}s")
        if self._error is not None:
            raise RuntimeError(f"MCP server '{self.name}' failed to start: {leaf_errors(self._error)}") from self._error
        return self

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except BaseException as e:  # noqa: BLE001
            self._error = e
            log.exception("MCP server '%s' stopped", self.name)
        finally:
            self._ready.set()
            self._loop.close()

    async def _serve(self) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        self._stop = asyncio.Event()
        async with stdio_client(self._params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self._session = session
                self._ready.set()
                await self._stop.wait()

    def close(self) -> None:
        if self._loop is not None and self._stop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout=5)

    # ---- the blocking API ----

    def _submit(self, coro):
        if self._session is None or self._loop is None:
            raise RuntimeError(f"MCP server '{self.name}' is not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=self._timeout)

    def list_tools(self) -> list[dict]:
        if self._tools is None:
            listing = self._submit(self._session.list_tools())
            self._tools = [
                {"name": t.name, "description": t.description or "",
                 "input_schema": _attr(t, "inputSchema", "input_schema")}
                for t in listing.tools
            ]
        return list(self._tools)

    def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return _parse(self._submit(self._session.call_tool(tool, args)))
