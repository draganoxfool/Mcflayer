"""Block position packing.

1.8-1.13: ``x`` (26 bits) ``<< 38 | y`` (12) ``<< 26 | z`` (26). 1.14+: ``x << 38 | z`` (26) ``<< 12
| y`` (12). Y is signed 12-bit, X/Z signed 26-bit.
"""

from __future__ import annotations

from pyflayer.errors import MalformedPacket
from pyflayer.models.vec3 import BlockPos

__all__ = ["pack_position", "unpack_position", "packed_range_ok"]


def pack_position(pos: BlockPos, *, packed_xzy: bool = True) -> int:
    """Pack a block position into the 64-bit wire value.

    Raises:
        MalformedPacket: If a coordinate does not fit the wire bit widths.
    """
    x, y, z = pos.x, pos.y, pos.z
    if not -(2**25) <= x < 2**25 or not -(2**25) <= z < 2**25:
        raise MalformedPacket("position x/z outside 26-bit range", pos=pos)
    if not -(2**11) <= y < 2**11:
        raise MalformedPacket("position y outside 12-bit range", pos=pos)
    xm = x & 0x3FFFFFF
    ym = y & 0xFFF
    zm = z & 0x3FFFFFF
    if packed_xzy:
        return (xm << 38) | (zm << 12) | ym
    return (xm << 38) | (ym << 26) | zm


def unpack_position(value: int, *, packed_xzy: bool = True) -> BlockPos:
    """Unpack a 64-bit wire value into a :class:`BlockPos`."""
    x = _signed((value >> 38) & 0x3FFFFFF, 26)
    if packed_xzy:
        z = _signed((value >> 12) & 0x3FFFFFF, 26)
        y = _signed(value & 0xFFF, 12)
    else:
        y = _signed((value >> 26) & 0xFFF, 12)
        z = _signed(value & 0x3FFFFFF, 26)
    return BlockPos(x, y, z)


def packed_range_ok(pos: BlockPos) -> bool:
    """True when the position fits the 26/12/26-bit wire format."""
    return (
        -(2**25) <= pos.x < 2**25
        and -(2**11) <= pos.y < 2**11
        and -(2**25) <= pos.z < 2**25
    )


def _signed(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)
