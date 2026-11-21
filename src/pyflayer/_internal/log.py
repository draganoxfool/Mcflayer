"""Logging setup. Library code uses ``logging.getLogger("pyflayer.<module>")``."""

from __future__ import annotations

import logging

__all__ = ["get_logger", "configure"]


def get_logger(module: str) -> logging.Logger:
    """Return ``pyflayer.<module>``, never the root logger."""
    return logging.getLogger(f"pyflayer.{module}")


def configure(level: int = logging.INFO) -> None:
    """Attach a stderr handler to the ``pyflayer`` namespace (idempotent)."""
    logger = logging.getLogger("pyflayer")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
