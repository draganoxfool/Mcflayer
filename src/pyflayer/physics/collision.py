"""Swept AABB movement against block collision shapes (M4)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from pyflayer.models.aabb import AABB
from pyflayer.models.vec3 import BlockPos, Vec3

__all__ = ["STEP_HEIGHT", "MoveResult", "move_box"]

_EPS = 1e-7
STEP_HEIGHT = 0.6


class _WorldReader(Protocol):
    def collision_boxes(self, pos: BlockPos) -> tuple[AABB, ...]: ...


@dataclass(frozen=True, slots=True)
class MoveResult:
    """Outcome of one swept move."""

    box: AABB
    delta: Vec3
    hit_x: bool = False
    hit_y: bool = False
    hit_z: bool = False
    on_ground: bool = False


def move_box(
    box: AABB,
    delta: Vec3,
    world: _WorldReader,
    *,
    step_height: float = STEP_HEIGHT,
    can_step: bool = True,
) -> MoveResult:
    """Move ``box`` by ``delta``, resolving collisions axis by axis.

    Y is resolved first, then X and Z, matching vanilla's movement order. When horizontal movement
    is blocked and ``can_step`` is true, a step of at most ``step_height`` is attempted.
    """
    y_box, y_delta, hit_y = _clip_axis(box, 1, delta.y, world)
    x_box, x_delta, hit_x = _clip_axis(y_box, 0, delta.x, world)
    z_box, z_delta, hit_z = _clip_axis(x_box, 2, delta.z, world)
    on_ground = hit_y and delta.y < 0

    if (
        can_step
        and step_height > 0
        and (hit_x or hit_z)
        and (abs(x_delta) + abs(z_delta) + _EPS < abs(delta.x) + abs(delta.z))
    ):
        stepped = _try_step(y_box, delta, world, step_height)
        if stepped is not None:
            return stepped

    return MoveResult(
        z_box,
        Vec3(x_delta, y_delta, z_delta),
        hit_x=hit_x,
        hit_y=hit_y,
        hit_z=hit_z,
        on_ground=on_ground,
    )


def _clip_sneak_displacement(box: AABB, delta: Vec3, world: _WorldReader) -> Vec3:
    x, z = delta.x, delta.z
    while x != 0.0 and not _collides(box.translated(Vec3(x, -1.0, 0.0)), world):
        x = _toward_zero(x, 0.05)
    while z != 0.0 and not _collides(box.translated(Vec3(0.0, -1.0, z)), world):
        z = _toward_zero(z, 0.05)
    while x != 0.0 and z != 0.0 and not _collides(box.translated(Vec3(x, -1.0, z)), world):
        x = _toward_zero(x, 0.05)
        z = _toward_zero(z, 0.05)
    return Vec3(x, delta.y, z)


def _toward_zero(value: float, amount: float) -> float:
    if value > 0.0:
        return max(0.0, value - amount)
    return min(0.0, value + amount)


def _try_step(box: AABB, delta: Vec3, world: _WorldReader, step_height: float) -> MoveResult | None:
    raised = box.translated(Vec3(0.0, step_height, 0.0))
    if _collides(raised, world):
        return None

    x_box, x_delta, hit_x = _clip_axis(raised, 0, delta.x, world)
    z_box, z_delta, hit_z = _clip_axis(x_box, 2, delta.z, world)
    if abs(x_delta) + abs(z_delta) + _EPS < abs(delta.x) + abs(delta.z):
        return None

    down_box, down_delta, hit_down = _clip_axis(z_box, 1, -step_height, world)
    if not hit_down or down_delta > -_EPS:
        return None
    if _collides(down_box, world):
        return None

    return MoveResult(
        down_box,
        Vec3(x_delta, step_height + down_delta, z_delta),
        hit_x=hit_x,
        hit_y=True,
        hit_z=hit_z,
        on_ground=True,
    )


def _clip_axis(
    box: AABB, axis: int, amount: float, world: _WorldReader
) -> tuple[AABB, float, bool]:
    if amount == 0.0:
        return box, 0.0, False

    translated = _offset(box, axis, amount)
    swept = AABB(
        min(box.min_x, translated.min_x),
        min(box.min_y, translated.min_y),
        min(box.min_z, translated.min_z),
        max(box.max_x, translated.max_x),
        max(box.max_y, translated.max_y),
        max(box.max_z, translated.max_z),
    )
    allowed = amount
    hit = False
    max_axis = _axis_max(box, axis)
    min_axis = _axis_min(box, axis)
    for block in _candidate_boxes(world, swept):
        if not swept.intersects(block):
            continue
        if amount > 0:
            clearance = _axis_min(block, axis) - max_axis
            if -_EPS <= clearance <= allowed + _EPS:
                allowed = min(allowed, max(0.0, clearance))
                hit = True
        else:
            clearance = min_axis - _axis_max(block, axis)
            if -_EPS <= clearance <= -allowed + _EPS:
                allowed = max(allowed, -max(0.0, clearance))
                hit = True

    allowed = max(-abs(amount), min(abs(amount), allowed))
    return _offset(box, axis, allowed), allowed, hit


def _offset(box: AABB, axis: int, amount: float) -> AABB:
    if axis == 0:
        return AABB(
            box.min_x + amount, box.min_y, box.min_z, box.max_x + amount, box.max_y, box.max_z
        )
    if axis == 1:
        return AABB(
            box.min_x, box.min_y + amount, box.min_z, box.max_x, box.max_y + amount, box.max_z
        )
    return AABB(box.min_x, box.min_y, box.min_z + amount, box.max_x, box.max_y, box.max_z + amount)


def _axis_min(box: AABB, axis: int) -> float:
    if axis == 0:
        return box.min_x
    if axis == 1:
        return box.min_y
    return box.min_z


def _axis_max(box: AABB, axis: int) -> float:
    if axis == 0:
        return box.max_x
    if axis == 1:
        return box.max_y
    return box.max_z


def _collides(box: AABB, world: _WorldReader) -> bool:
    return any(box.intersects(block) for block in _candidate_boxes(world, box))


def _candidate_boxes(world: _WorldReader, box: AABB) -> list[AABB]:
    min_x = math.floor(box.min_x - _EPS)
    max_x = math.floor(box.max_x + _EPS)
    min_y = math.floor(box.min_y - _EPS)
    max_y = math.floor(box.max_y + _EPS)
    min_z = math.floor(box.min_z - _EPS)
    max_z = math.floor(box.max_z + _EPS)
    boxes: list[AABB] = []
    for bx in range(min_x, max_x + 1):
        for by in range(min_y, max_y + 1):
            for bz in range(min_z, max_z + 1):
                for local in world.collision_boxes(BlockPos(bx, by, bz)):
                    boxes.append(
                        AABB(
                            local.min_x + bx,
                            local.min_y + by,
                            local.min_z + bz,
                            local.max_x + bx,
                            local.max_y + by,
                            local.max_z + bz,
                        )
                    )
    return boxes
