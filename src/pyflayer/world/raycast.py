"""Voxel raycast over collision shapes (Amanatides & Woo DDA).

Examples:
    >>> world = World(McData.load("1.8.9"))   # doctest: +SKIP
    >>> world.raycast(Vec3(0.5, 70.5, 0.5), Vec3(0, -1, 0), 8)
    RayHit(...)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pyflayer.models.enums import Face
from pyflayer.models.vec3 import BlockPos, Vec3

__all__ = ["RayHit", "raycast"]

_EPS = 1e-12


@dataclass(frozen=True, slots=True)
class RayHit:
    """First block hit by a ray."""

    pos: BlockPos
    state_id: int
    distance: float
    face: Face | None = None


def raycast(
    world: object,
    origin: Vec3,
    direction: Vec3,
    max_dist: float,
    *,
    include_fluids: bool = False,
) -> RayHit | None:
    """March a ray through the world and return the first collision.

    Args:
        world: Any object with ``block_state_id_or``, ``collision_boxes`` and ``block_at``.
        origin: Ray origin in world coordinates.
        direction: Ray direction (normalized internally).
        max_dist: Maximum distance to travel.
        include_fluids: Treat water/lava as solid hit boxes.
    """
    ray = direction.normalize()
    if max_dist <= 0 or ray.length_squared() < _EPS:
        return None
    current = origin.floored()
    step_x, step_y, step_z = (
        1 if ray.x > 0 else -1,
        1 if ray.y > 0 else -1,
        1 if ray.z > 0 else -1,
    )
    delta_x = abs(1.0 / ray.x) if abs(ray.x) > _EPS else math.inf
    delta_y = abs(1.0 / ray.y) if abs(ray.y) > _EPS else math.inf
    delta_z = abs(1.0 / ray.z) if abs(ray.z) > _EPS else math.inf
    max_x = _first_boundary(origin.x, current.x, ray.x, step_x)
    max_y = _first_boundary(origin.y, current.y, ray.y, step_y)
    max_z = _first_boundary(origin.z, current.z, ray.z, step_z)

    distance = 0.0
    while distance <= max_dist:
        state_id = _state(world, current)
        boxes = _boxes(world, current)
        if include_fluids and state_id and not boxes:
            block = _block(world, current)
            if block is not None and block.name.removeprefix("minecraft:") in {
                "water",
                "flowing_water",
                "lava",
                "flowing_lava",
            }:
                boxes = (_UNIT_BOX,)
        for box in boxes:
            hit = _intersect(origin, ray, current, box, max_dist)
            if hit is not None:
                return RayHit(current, state_id, hit[0], hit[1])
        if max_x <= max_y and max_x <= max_z:
            distance = max_x
            current = current.offset(step_x, 0, 0)
            max_x += delta_x
        elif max_y <= max_z:
            distance = max_y
            current = current.offset(0, step_y, 0)
            max_y += delta_y
        else:
            distance = max_z
            current = current.offset(0, 0, step_z)
            max_z += delta_z
    return None


class _UnitBox:
    __slots__ = ("max_x", "max_y", "max_z", "min_x", "min_y", "min_z")

    def __init__(self) -> None:
        self.min_x = self.min_y = self.min_z = 0.0
        self.max_x = self.max_y = self.max_z = 1.0


_UNIT_BOX = _UnitBox()


def _first_boundary(origin: float, cell: int, direction: float, step: int) -> float:
    if abs(direction) < _EPS:
        return math.inf
    boundary = cell + 1 if step > 0 else cell
    return abs((boundary - origin) / direction)


def _state(world: object, pos: BlockPos) -> int:
    getter = world.block_state_id_or
    return int(getter(pos, 0))


def _boxes(world: object, pos: BlockPos) -> tuple[object, ...]:
    getter = getattr(world, "collision_boxes", None)
    return tuple(getter(pos)) if getter is not None else ()


def _block(world: object, pos: BlockPos) -> object | None:
    try:
        return world.block_at(pos)  # type: ignore[attr-defined]
    except Exception:
        return None


def _intersect(
    origin: Vec3, direction: Vec3, cell: BlockPos, box: object, max_dist: float
) -> tuple[float, Face | None] | None:
    t_min = 0.0
    t_max = max_dist
    face: Face | None = None
    for axis, (start, low, high) in enumerate(
        (
            (origin.x, cell.x + box.min_x, cell.x + box.max_x),  # type: ignore[attr-defined]
            (origin.y, cell.y + box.min_y, cell.y + box.max_y),  # type: ignore[attr-defined]
            (origin.z, cell.z + box.min_z, cell.z + box.max_z),  # type: ignore[attr-defined]
        )
    ):
        d = direction.x if axis == 0 else direction.y if axis == 1 else direction.z
        if abs(d) < _EPS:
            if not (low - _EPS <= start <= high + _EPS):
                return None
            continue
        t1 = (low - start) / d
        t2 = (high - start) / d
        if t1 > t2:
            t1, t2 = t2, t1
        if t1 > t_min:
            t_min = t1
            face = _face_for(axis, d)
        if t2 < t_max:
            t_max = t2
        if t_min > t_max:
            return None
    if t_min > max_dist:
        return None
    return t_min, face


def _face_for(axis: int, direction: float) -> Face:
    if axis == 0:
        return Face.WEST if direction > 0 else Face.EAST
    if axis == 1:
        return Face.DOWN if direction > 0 else Face.UP
    return Face.NORTH if direction > 0 else Face.SOUTH
