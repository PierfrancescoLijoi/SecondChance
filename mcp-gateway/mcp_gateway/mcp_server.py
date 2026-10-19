"""Official MCP stdio transport for desktop/CLI clients.

Identity is operator-supplied configuration, not model input. AWS agents use the
IAM-authenticated Lambda transport exposed by the same gateway policy core.
"""

import asyncio
import os

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from mcp_gateway.service import handle, policy

server = Server("secondchance-mcp-gateway")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [types.Tool(
        name=item["name"], description=item["description"], inputSchema=item["input_schema"],
        annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    ) for item in policy.catalog()]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    result = handle({
        "name": name,
        "arguments": arguments,
        "context": {
            "tenant_id": os.environ["SECONDCHANCE_MCP_TENANT_ID"],
            "subject": os.environ["SECONDCHANCE_MCP_SUBJECT"],
            "role": os.getenv("SECONDCHANCE_MCP_ROLE", "volunteer"),
            "agent": "mcp_client",
            "correlation_id": os.getenv("SECONDCHANCE_MCP_CORRELATION_ID", "mcp-stdio"),
        },
    })
    if "error" in result:
        raise ValueError(result["error"])
    return [types.TextContent(type="text", text=__import__("json").dumps(result["result"]))]


async def _main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
