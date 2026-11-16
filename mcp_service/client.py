import json
import os
import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def call_mcp_tool(mcp_token: str, tool_name: str, arguments: dict):
    mcp_url = os.getenv("MCP_URL", "http://127.0.0.1:8001/mcp")
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {mcp_token}"},
        timeout=60,
    ) as http_client:
        async with streamable_http_client(mcp_url, http_client=http_client) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)

    if result.is_error:
        raise RuntimeError(f"{tool_name} failed: {result.content}")

    if getattr(result, "structured_content", None):
        data = result.structured_content
        return data.get("result", data) if isinstance(data, dict) else data

    if getattr(result, "content", None):
        parsed = []
        for item in result.content:
            text = getattr(item, "text", str(item))
            try:
                val = json.loads(text)
                if isinstance(val, list):
                    parsed.extend(val)
                else:
                    parsed.append(val)
            except Exception:
                parsed.append(text)

        if not parsed:
            return None
        if len(result.content) == 1 and not isinstance(parsed[0], list):
            if tool_name not in {"search_products", "semantic_search"}:
                return parsed[0]
        return parsed

    return None
