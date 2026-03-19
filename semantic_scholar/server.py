"""
Main server module for the Semantic Scholar API Server.
"""

import asyncio
import os
import uvicorn

# Import mcp from centralized location
from .mcp import mcp
from .utils.http import initialize_client, cleanup_client
from .utils.logger import logger

# Import API modules to register tools
# Note: This must come AFTER mcp is initialized
from .api import papers, authors, recommendations

_TASK_CANCEL_TIMEOUT = 5  # seconds to wait for tasks to finish on shutdown


async def run_server():
    """Run the server with proper async context management."""
    tasks: list[asyncio.Task] = []
    try:
        # Initialize HTTP client
        await initialize_client()

        # Start the server
        transport = os.getenv("SEMANTIC_SCHOLAR_MCP_TRANSPORT", "stdio").strip().lower()
        mcp_host = os.getenv("SEMANTIC_SCHOLAR_MCP_HOST", "0.0.0.0").strip()
        mcp_port = int(os.getenv("SEMANTIC_SCHOLAR_MCP_PORT", "8080"))
        logger.info("Starting Semantic Scholar Server (transport=%s)", transport)

        if transport in ("sse", "streamable-http"):
            mcp_task = asyncio.create_task(
                mcp.run_async(transport=transport, host=mcp_host, port=mcp_port)
            )
        else:
            mcp_task = asyncio.create_task(mcp.run_async())
        tasks.append(mcp_task)

        # Start the HTTP bridge (ASGI) in the same process so the service
        # exposes REST endpoints on a local port. The `bridge.app` is a thin
        # FastAPI application that reuses the package HTTP utilities.
        enable_bridge = os.getenv("SEMANTIC_SCHOLAR_ENABLE_HTTP_BRIDGE", "1").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if enable_bridge:
            bridge_host = os.getenv("SEMANTIC_SCHOLAR_HTTP_BRIDGE_HOST", "0.0.0.0").strip()
            bridge_port = int(os.getenv("SEMANTIC_SCHOLAR_HTTP_BRIDGE_PORT", "8000"))
            from .bridge import app as bridge_app
            config = uvicorn.Config(
                app=bridge_app,
                host=bridge_host,
                port=bridge_port,
                log_level="info",
                log_config=None,
                ws="none",  # Disable WebSocket support to avoid deprecation warnings
            )
            bridge_server = uvicorn.Server(config=config)
            tasks.append(asyncio.create_task(bridge_server.serve()))
            logger.info("HTTP bridge enabled on %s:%s", bridge_host, bridge_port)
        else:
            logger.info("HTTP bridge disabled (SEMANTIC_SCHOLAR_ENABLE_HTTP_BRIDGE=0)")

        # Wait for any task to finish (e.g. uvicorn exits on Ctrl+C).
        # When one exits, cancel the rest.
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        # Log errors from finished tasks
        for t in done:
            if t.exception():
                logger.error("Task failed: %s", t.exception())

        # Cancel remaining tasks and give them time to finish
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.wait(pending, timeout=_TASK_CANCEL_TIMEOUT)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        # Cancel any still-alive tasks (belt-and-suspenders)
        for t in tasks:
            if not t.done():
                t.cancel()
        if any(not t.done() for t in tasks):
            await asyncio.wait(tasks, timeout=_TASK_CANCEL_TIMEOUT)

        await cleanup_client()
        logger.info("Shutdown complete")


def main():
    """Main entry point for the server."""
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
    finally:
        logger.info("Server stopped")

if __name__ == "__main__":
    main()
