"""
Centralized logging configuration for the Semantic Scholar server.
"""

import logging
import os

DEBUG_REQUESTS = os.getenv("SEMANTIC_SCHOLAR_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")

logging.basicConfig(level=logging.DEBUG if DEBUG_REQUESTS else logging.INFO)
logger = logging.getLogger("semantic_scholar")
