"""Small shared utilities with no project dependencies."""

from __future__ import annotations

import math
from collections.abc import Iterable

__all__ = ["ceil_log2", "iter_bits", "clamp", "signed", "to_bytes", "batched"]


def ceil_log2(value: int) -> int:
    """Smallest ``n`` with ``2**n >= value``; ``ceil_log2(0) == 0``."""
    if value <= 1:
        return 0
    return (value - 1).bit_length()


def iter_bits(value: int, count: int) -> Iterable[int]:
    """Yield ``count`` bits of ``value`` least-significant first."""
    for i in range(count):
        yield (value >> i) & 1


def clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into ``[low, high]``."""
    return max(low, min(high, value))


def signed(value: int, bits: int) -> int:
    """Interpret ``value`` as a two's-complement integer of ``bits`` bits."""
    sign_bit = 1 << (bits - 1)
    return (value & (sign_bit - 1)) - (value & sign_bit)


def to_bytes(value: bytes | bytearray | memoryview) -> bytes:
    """Copy any bytes-like object to ``bytes``."""
    return bytes(value)


def batched(items: Iterable[int], size: int) -> Iterable[tuple[int, ...]]:
    """Chunk an iterable (used by multi-block updates later)."""
    if size <= 0:
        raise ValueError("size must be positive")
    batch: list[int] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield tuple(batch)
            batch.clear()
    if batch:
        yield tuple(batch)


def is_power_of_two(value: int) -> bool:
    """True for 1, 2, 4, ... (0 is not)."""
    return value > 0 and math.log2(value).is_integer()
