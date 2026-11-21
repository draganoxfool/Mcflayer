"""Coordinate value types: :class:`Vec3`, :class:`BlockPos`, :class:`ChunkPos`, :class:`SectionPos`.

All are frozen, slotted and hashable. ``Vec3`` is floating point; positions are integers.

Examples:
    >>> Vec3(1, 2, 3) + Vec3(0, 0, -3)
    Vec3(1.0, 2.0, 0.0)
    >>> BlockPos(1, 64, -2) // 16
    ChunkPos(0, -1)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Self

__all__ = ["BlockPos", "ChunkPos", "SectionPos", "Vec3"]


@dataclass(frozen=True, slots=True)
class Vec3:
    """A 3D floating-point vector."""

    x: float
    y: float
    z: float

    def __add__(self, other: Vec3) -> Vec3:
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: Vec3) -> Vec3:
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> Vec3:
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    def __rmul__(self, scalar: float) -> Vec3:
        return self * scalar

    def __truediv__(self, scalar: float) -> Vec3:
        return Vec3(self.x / scalar, self.y / scalar, self.z / scalar)

    def dot(self, other: Vec3) -> float:
        """Dot product."""
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: Vec3) -> Vec3:
        """Right-handed cross product."""
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def length(self) -> float:
        """Euclidean length."""
        return math.sqrt(self.dot(self))

    def length_squared(self) -> float:
        """Squared length (cheaper, used for movement thresholds)."""
        return self.dot(self)

    def normalize(self) -> Vec3:
        """Unit vector; zero stays zero."""
        length = self.length()
        return self / length if length else Vec3(0.0, 0.0, 0.0)

    def distance_to(self, other: Vec3) -> float:
        """Euclidean distance to ``other``."""
        return (self - other).length()

    def floored(self) -> BlockPos:
        """Block containing this point."""
        return BlockPos(math.floor(self.x), math.floor(self.y), math.floor(self.z))

    def to_tuple(self) -> tuple[float, float, float]:
        """Plain tuple."""
        return (self.x, self.y, self.z)


@dataclass(frozen=True, slots=True, order=True)
class BlockPos:
    """Integer block coordinates (world space)."""

    x: int
    y: int
    z: int

    def offset(self, dx: int = 0, dy: int = 0, dz: int = 0) -> BlockPos:
        """Return a translated position."""
        return BlockPos(self.x + dx, self.y + dy, self.z + dz)

    def with_y(self, y: int) -> BlockPos:
        """Return a copy at a new Y."""
        return BlockPos(self.x, y, self.z)

    @property
    def chunk(self) -> ChunkPos:
        """Chunk column containing this block (floor division, negatives included)."""
        return ChunkPos(self.x >> 4, self.z >> 4)

    @property
    def section(self) -> SectionPos:
        """Chunk section containing this block."""
        return SectionPos(self.x >> 4, self.y >> 4, self.z >> 4)

    def local_x(self) -> int:
        """X within the chunk column, 0..15."""
        return self.x & 15

    def local_z(self) -> int:
        """Z within the chunk column, 0..15."""
        return self.z & 15

    def local_y(self) -> int:
        """Y within the section, 0..15."""
        return self.y & 15

    def __floordiv__(self, other: int) -> ChunkPos:
        return ChunkPos(self.x // other, self.z // other)

    def to_tuple(self) -> tuple[int, int, int]:
        """Plain tuple."""
        return (self.x, self.y, self.z)

    def to_vec3(self) -> Vec3:
        """Center of the block as a float vector."""
        return Vec3(self.x + 0.5, self.y + 0.5, self.z + 0.5)


@dataclass(frozen=True, slots=True, order=True)
class ChunkPos:
    """Chunk column coordinates (16x16 columns)."""

    x: int
    z: int

    def to_block(self, y: int = 0) -> BlockPos:
        """Corner block ``(x << 4, y, z << 4)``."""
        return BlockPos(self.x << 4, y, self.z << 4)

    def to_tuple(self) -> tuple[int, int]:
        """Plain tuple."""
        return (self.x, self.z)


@dataclass(frozen=True, slots=True, order=True)
class SectionPos:
    """16x16x16 section coordinates."""

    x: int
    y: int
    z: int

    def to_tuple(self) -> tuple[int, int, int]:
        """Plain tuple."""
        return (self.x, self.y, self.z)

    @classmethod
    def from_block(cls, pos: BlockPos) -> Self:
        """Section containing ``pos``."""
        return cls(pos.x >> 4, pos.y >> 4, pos.z >> 4)
