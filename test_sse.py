import asyncio
import httpx
from httpx_sse import aconnect_sse
import os

async def main():
    async with httpx.AsyncClient() as client:
        try:
            async with aconnect_sse(client, "GET", "http://127.0.0.1:7860/mcp/sse") as event_source:
                print("Connected successfully using 'aconnect_sse'")
                async for sse in event_source.aiter_sse():
                    print(f"Got event: {sse.event}")
                    break
        except Exception as e:
            print(f"Failed with 'aconnect_sse': {e}")

if __name__ == "__main__":
    asyncio.run(main())
