"""
Main server module for the Semantic Scholar API Server.
"""

import asyncio
import os
import signal
import uvicorn

# Import mcp from centralized location
from .mcp import mcp
from .utils.http import initialize_client, cleanup_client
from .utils.logger import logger

# Configure logging

# Event to keep process alive when FastMCP detaches
stop_event = None
# ASGI HTTP server instance and task (for the bridge)
http_server = None
http_server_task = None

# Import API modules to register tools
# Note: This must come AFTER mcp is initialized
from .api import papers, authors, recommendations

async def handle_exception(loop, context):
    """Global exception handler for the event loop."""
    msg = context.get("exception", context["message"])
    logger.error(f"Caught exception: {msg}")
    asyncio.create_task(shutdown())

async def shutdown():
    """Gracefully shut down the server."""
    logger.info("Initiating graceful shutdown...")
    
    # Cancel all tasks
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    # Cleanup resources
    await cleanup_client()
    try:
        cleanup_fn = getattr(mcp, "cleanup", None)
        if cleanup_fn:
            if asyncio.iscoroutinefunction(cleanup_fn):
                await cleanup_fn()
            else:
                cleanup_fn()
        else:
            # Try common alternative names on FastMCP implementations
            for name in ("shutdown", "stop", "close"):
                fn = getattr(mcp, name, None)
                if fn:
                    if asyncio.iscoroutinefunction(fn):
                        await fn()
                    else:
                        fn()
                    break
    except Exception as e:
        logger.error(f"Error during mcp cleanup: {e}")
    # Signal run_server to stop waiting
    try:
        global stop_event
        if stop_event is not None and not stop_event.is_set():
            stop_event.set()
    except Exception:
        pass

    # Stop the HTTP bridge if running
    try:
        global http_server, http_server_task
        if http_server is not None:
            http_server.should_exit = True
        if http_server_task is not None and not http_server_task.done():
            http_server_task.cancel()
            try:
                await http_server_task
            except asyncio.CancelledError:
                pass
    except Exception as e:
        logger.error(f"Error stopping HTTP bridge: {e}")
    
    logger.info(f"Cancelled {len(tasks)} tasks")
    logger.info("Shutdown complete")

def init_signal_handlers(loop):
    """Initialize signal handlers for graceful shutdown."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))
    logger.info("Signal handlers initialized")

async def run_server():
    """Run the server with proper async context management."""
    try:
        # Initialize HTTP client
        await initialize_client()

        # Start the server
        logger.info("Starting Semantic Scholar Server")
        task = asyncio.create_task(mcp.run_async())

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
                ws="none"  # Disable WebSocket support to avoid deprecation warnings
            )
            server = uvicorn.Server(config=config)
            global http_server, http_server_task
            http_server = server
            http_server_task = asyncio.create_task(server.serve())
            logger.info("HTTP bridge enabled on %s:%s", bridge_host, bridge_port)
        else:
            logger.info("HTTP bridge disabled (SEMANTIC_SCHOLAR_ENABLE_HTTP_BRIDGE=0)")

        # Create a stop event to keep the main coroutine alive if FastMCP detaches
        global stop_event
        if stop_event is None:
            stop_event = asyncio.Event()

        # Wait until shutdown() sets the event
        await stop_event.wait()
        # Ensure server task is cancelled/awaited on shutdown
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
    finally:
        await shutdown()

def main():
    """Main entry point for the server."""
    try:
        # Set up event loop with exception handler
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.set_exception_handler(handle_exception)
        
        # Initialize signal handlers
        init_signal_handlers(loop)
        
        # Run the server
        loop.run_until_complete(run_server())
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
    finally:
        try:
            loop.run_until_complete(asyncio.sleep(0))  # Let pending tasks complete
            loop.close()
        except Exception as e:
            logger.error(f"Error during final cleanup: {str(e)}")
        logger.info("Server stopped")

if __name__ == "__main__":
    main() 
