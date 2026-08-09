"""The response cap has to cover the field clients actually read.

``structured_content`` was only inspected when a *text* block had already
been truncated, so a tool returning a small text block beside a huge
structured payload sailed past the limit — and structured content is what
most MCP clients prefer. The cap existed to protect a context window; this
was the hole in it.
"""

from __future__ import annotations

import mcp.types as mt
import pytest
from fastmcp.tools import ToolResult
from mcp.types import TextContent

from molmcp.middleware.response_limit import ResponseLimitMiddleware


class _Context:
    def __init__(self) -> None:
        self.message = mt.CallToolRequestParams(name="t", arguments={})


def _run(middleware: ResponseLimitMiddleware, result: ToolResult) -> ToolResult:
    import asyncio

    async def call_next(_ctx):
        return result

    return asyncio.run(middleware.on_call_tool(_Context(), call_next))


class TestStructuredContentIsCapped:
    def test_a_huge_structured_payload_is_replaced(self):
        middleware = ResponseLimitMiddleware(max_bytes=1024)
        result = ToolResult(
            content=[TextContent(type="text", text="ok")],
            structured_content={"rows": ["x" * 100 for _ in range(200)]},
        )

        capped = _run(middleware, result)

        message = str(capped.structured_content)
        assert len(message) < 1024
        # Says what happened and how to recover, not just that it is gone.
        assert "omitted" in message
        assert "narrower arguments" in message

    def test_a_small_structured_payload_passes_through_untouched(self):
        middleware = ResponseLimitMiddleware(max_bytes=1024)
        payload = {"rows": [1, 2, 3]}
        result = ToolResult(
            content=[TextContent(type="text", text="ok")],
            structured_content=payload,
        )

        capped = _run(middleware, result)

        assert capped.structured_content == payload

    def test_text_and_structured_content_are_capped_together(self):
        middleware = ResponseLimitMiddleware(max_bytes=512)
        result = ToolResult(
            content=[TextContent(type="text", text="y" * 5000)],
            structured_content={"rows": ["x" * 100 for _ in range(200)]},
        )

        capped = _run(middleware, result)

        assert len(capped.content[0].text.encode()) < 5000
        assert len(str(capped.structured_content)) < 5000

    @pytest.mark.parametrize("payload", [None, {"ok": True}])
    def test_non_dict_structured_content_is_not_mangled(self, payload):
        middleware = ResponseLimitMiddleware(max_bytes=1024)
        result = ToolResult(
            content=[TextContent(type="text", text="ok")],
            structured_content=payload,
        )

        assert _run(middleware, result).structured_content == payload
