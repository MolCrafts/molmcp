"""Cap the size of tool responses to protect LLM context windows."""

from __future__ import annotations

import json

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.tool import ToolResult
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
            if (
                isinstance(block, TextContent)
                and len(block.text.encode()) > self.max_bytes
            ):
                cutoff = self.max_bytes
                clipped = block.text.encode()[:cutoff].decode(errors="ignore")
                marker = (
                    f"\n\n[molmcp: response truncated at {cutoff} bytes; "
                    f"original was {len(block.text.encode())} bytes — "
                    f"call again with narrower arguments]"
                )
                new_blocks.append(TextContent(type="text", text=clipped + marker))
                truncated = True
            else:
                new_blocks.append(block)
        if truncated:
            sc = result.structured_content
            if isinstance(sc, dict):
                try:
                    sz = len(json.dumps(sc).encode())
                    if sz > self.max_bytes:
                        sc = {
                            "result": "[molmcp: structured content omitted; "
                            "see truncated text above]"
                        }
                except (TypeError, ValueError):
                    pass
            return ToolResult(
                content=new_blocks,
                structured_content=sc,
                meta=result.meta,
            )
        return result
