"""CPU offload helper (loop budget rule).

Synchronous work that can exceed ~2 ms must not run on the event loop. ``run_cpu`` runs it in a
worker thread (numpy/GIL-releasing work) or, for pure-Python CPU burns, in a process is *not* the
default here: M1 only needs thread offload for zlib and JSON. Callers pass an immutable snapshot.

Examples:
    >>> data = await run_cpu(zlib.decompress, payload)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar

__all__ = ["run_cpu"]

P = ParamSpec("P")
T = TypeVar("T")

_log = logging.getLogger("pyflayer._internal.cpu")


async def run_cpu(
    func: Callable[P, T],
    /,
    *args: P.args,
    budget_ms: float | None = None,
    **kwargs: P.kwargs,
) -> T:
    """Run ``func`` in a worker thread and return its result.

    Args:
        func: Callable to invoke. It must not mutate loop-owned state.
        *args: Positional arguments.
        budget_ms: Optional soft budget; exceeding it logs a warning.
        **kwargs: Keyword arguments.

    Returns:
        Whatever ``func`` returns.
    """
    started = time.perf_counter()
    result = await asyncio.to_thread(func, *args, **kwargs)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if budget_ms is not None and elapsed_ms > budget_ms:
        _log.warning(
            "offloaded call exceeded budget",
            extra={"func": getattr(func, "__name__", repr(func)), "elapsed_ms": elapsed_ms},
        )
    return result
