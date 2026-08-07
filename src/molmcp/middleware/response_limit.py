"""Cap the size of tool responses to protect LLM context windows."""

from __future__ import annotations

import json

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import TextContent

DEFAULT_MAX_BYTES = 256 * 1024  # 256 KB


class ResponseLimitMiddleware(Middleware):
    """Truncate tool result payloads larger than ``max_bytes``.

    Operates on text content blocks only — binary content is passed through
    unchanged (truncating an image would corrupt it).
    """

    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES):
        self.max_bytes = max_bytes

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result = await call_next(context)
        new_blocks = []
        truncated = False
        for block in result.content:
            if not isinstance(block, TextContent):
                new_blocks.append(block)
                continue
            # Encode once: this used to run three times per block, which on a
            # multi-megabyte response is three full UTF-8 copies.
            encoded = block.text.encode()
            if len(encoded) <= self.max_bytes:
                new_blocks.append(block)
                continue
            clipped = encoded[: self.max_bytes].decode(errors="ignore")
            marker = (
                f"\n\n[molmcp: response truncated at {self.max_bytes} bytes; "
                f"original was {len(encoded)} bytes — "
                f"call again with narrower arguments]"
            )
            new_blocks.append(TextContent(type="text", text=clipped + marker))
            truncated = True

        # Checked unconditionally. This used to run only when a text block had
        # already been truncated, so a tool returning a short message beside a
        # huge structured payload passed the cap untouched — and structured
        # content is the field most MCP clients read first.
        structured, dropped = self._cap_structured(result.structured_content)
        if not truncated and not dropped:
            return result
        return ToolResult(
            content=new_blocks,
            structured_content=structured,
            meta=result.meta,
        )

    def _cap_structured(self, structured: object) -> tuple[object, bool]:
        """Replace an oversized structured payload; report whether it went."""
        if not isinstance(structured, dict):
            return structured, False
        try:
            size = len(json.dumps(structured, default=str).encode())
        except (TypeError, ValueError):
            return structured, False
        if size <= self.max_bytes:
            return structured, False
        return {
            "result": (
                f"[molmcp: structured content omitted; it was {size} bytes "
                f"against a {self.max_bytes} byte cap — call again with "
                f"narrower arguments]"
            )
        }, True
