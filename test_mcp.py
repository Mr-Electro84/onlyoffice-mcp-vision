"""Smoke test from an environment with fastmcp installed: python test_mcp.py https://my-host/mcp"""
import asyncio
import os
import sys
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

async def main(url: str):
    transport = StreamableHttpTransport(url=url, headers={"Authorization": "Bearer " + os.environ["MCP_AUTH_TOKEN"]})
    async with Client(transport) as client:
        tools = await client.list_tools()
        print("Outils MCP disponibles:", [t.name for t in tools])
        print("Test de l'accès en lecture à DocSpace:")
        print(await client.call_tool("lister_images_docspace", {"dossier": "@my"}))

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp"))
