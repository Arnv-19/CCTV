"""Compatibility ASGI entrypoint for debug and uvicorn commands.

This allows running either:
- uvicorn main:app
- uvicorn app.main:app
"""

from app.main import app
