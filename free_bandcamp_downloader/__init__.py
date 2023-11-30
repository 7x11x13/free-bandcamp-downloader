import importlib.metadata
import logging
import os

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))
logger = logging.getLogger(__name__)

__version__ = importlib.metadata.version("free-bandcamp-downloader")
