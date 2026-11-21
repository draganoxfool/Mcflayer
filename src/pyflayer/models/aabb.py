"""Axis-aligned bounding box."""

from __future__ import annotations

from dataclasses import dataclass

from pyflayer.models.vec3 import Vec3

__all__ = ["AABB"]


@dataclass(frozen=True, slots=True)
class AABB:
    """An axis-aligned box in world space. ``min`` components must be <= ``max``."""

    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    @classmethod
    def from_center(cls, center: Vec3, half_width: float, height: float) -> AABB:
        """Player-shaped box: centered on X/Z and extending upward from ``center.y``."""
        return cls(
            center.x - half_width,
            center.y,
            center.z - half_width,
            center.x + half_width,
            center.y + height,
            center.z + half_width,
        )

    @property
    def min(self) -> Vec3:
        """Minimum corner."""
        return Vec3(self.min_x, self.min_y, self.min_z)

    @property
    def max(self) -> Vec3:
        """Maximum corner."""
        return Vec3(self.max_x, self.max_y, self.max_z)

    @property
    def center(self) -> Vec3:
        """Box centre."""
        return Vec3(
            (self.min_x + self.max_x) / 2,
            (self.min_y + self.max_y) / 2,
            (self.min_z + self.max_z) / 2,
        )

    def intersects(self, other: AABB) -> bool:
        """Closed-overlap test (touching faces do not intersect)."""
        return (
            self.min_x < other.max_x
            and self.max_x > other.min_x
            and self.min_y < other.max_y
            and self.max_y > other.min_y
            and self.min_z < other.max_z
            and self.max_z > other.min_z
        )

    def translated(self, offset: Vec3) -> AABB:
        """Copy moved by ``offset``."""
        return AABB(
            self.min_x + offset.x,
            self.min_y + offset.y,
            self.min_z + offset.z,
            self.max_x + offset.x,
            self.max_y + offset.y,
            self.max_z + offset.z,
        )

    def expand(self, dx: float, dy: float, dz: float) -> AABB:
        """Grow in every direction."""
        return AABB(
            self.min_x - dx,
            self.min_y - dy,
            self.min_z - dz,
            self.max_x + dx,
            self.max_y + dy,
            self.max_z + dz,
        )

    def contains(self, point: Vec3) -> bool:
        """True when ``point`` is inside (inclusive)."""
        return (
            self.min_x <= point.x <= self.max_x
            and self.min_y <= point.y <= self.max_y
            and self.min_z <= point.z <= self.max_z
        )
