#!/usr/bin/env python3
import sys
import json
import asyncio
import os
import httpx
from httpx_sse import aconnect_sse

import uuid

# Default Mnesis URL
MCP_HTTP_URL = os.environ.get("MNESIS_MCP_URL", "http://127.0.0.1:7860")
API_KEY = os.environ.get("MNESIS_API_KEY", "")
SESSION_ID = str(uuid.uuid4())

async def stdin_reader(client, post_url_queue):
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    
    # Wait for the post_url to be available
    post_url = await post_url_queue.get()
    
    while True:
        line = await reader.readline()
        if not line:
            break
        
        try:
            msg = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
            
        try:
            # Forward to HTTP server
            # Use query param sessionId if needed? 
            # FastAPIServer might require sessionId in query?
            # The endpoint URL usually contains it as query param if needed.
            
            await client.post(
                post_url,
                json=msg,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "X-Mnesis-Session-Id": SESSION_ID
                },
                timeout=None
            )
        except Exception as e:
            sys.stderr.write(f"Bridge POST error: {e}\n")
            sys.stderr.flush()

async def sse_reader(client, post_url_queue):
    try:
        async with aconnect_sse(client, "GET", f"{MCP_HTTP_URL}/mcp/sse") as event_source:
            async for sse in event_source.aiter_sse():
                if sse.event == "endpoint":
                    # Server tells us where to send messages. url usually relative or absolute.
                    url = sse.data
                    if url.startswith("/"):
                        url = f"{MCP_HTTP_URL}{url}"
                    
                    # Put it in the queue for the stdin reader to use
                    # We might get it multiple times, but we only need it once to start?
                    # Or we should update it?
                    # For simplicity, just put it if queue is empty.
                    if post_url_queue.empty():
                        await post_url_queue.put(url)
                        
                elif sse.event == "message":
                    # Forward to stdout
                    sys.stdout.write(sse.data + "\n")
                    sys.stdout.flush()
    except Exception as e:
        sys.stderr.write(f"Bridge SSE error: {e}\n")
        sys.stderr.flush()
        # Exit if SSE fails, as bridge is broken
        sys.exit(1)

async def bridge():
    async with httpx.AsyncClient(timeout=None) as client:
        post_url_queue = asyncio.Queue()
        
        # Start both tasks
        # We need to wait for stdin_reader to finish (stdin closed)
        # But sse_reader runs forever until error.
        
        t1 = asyncio.create_task(sse_reader(client, post_url_queue))
        t2 = asyncio.create_task(stdin_reader(client, post_url_queue))
        
        await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)

if __name__ == "__main__":
    try:
        asyncio.run(bridge())
    except KeyboardInterrupt:
        pass
