"""Deterministic 1.8-style player physics (M4).

The engine is a pure function: ``step(state, controls, world)`` returns a new
:class:`~pyflayer.physics.state.PlayerState` and never performs I/O. It consumes the read-only
surface of :class:`~pyflayer.world.world.World` (``block_at`` and ``collision_boxes``).

This is the M4 foundation: ground/air movement, jumping, sprinting, sneaking, water/lava drag,
ladders, cobwebs and block friction. Oracle traces and the remaining media edge cases are tracked
in ``docs/tasks.md``.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Protocol

from pyflayer.models.aabb import AABB
from pyflayer.models.vec3 import BlockPos, Vec3
from pyflayer.physics.collision import STEP_HEIGHT, move_box
from pyflayer.physics.controls import ControlState
from pyflayer.physics.media import sample_medium
from pyflayer.physics.state import PlayerState

__all__ = ["GRAVITY", "JUMP_VELOCITY", "PLAYER_SPEED", "PhysicsEngine"]

PLAYER_SPEED = 0.1
GRAVITY = 0.08
JUMP_VELOCITY = 0.42
AIR_ACCELERATION = 0.02
SPRINT_MULTIPLIER = 1.3
SNEAK_MULTIPLIER = 0.3
_GROUND_ACCELERATION = 0.1627714


class _WorldReader(Protocol):
    def block_at(self, pos: BlockPos) -> object: ...
    def collision_boxes(self, pos: BlockPos) -> tuple[AABB, ...]: ...


class PhysicsEngine:
    """Player physics with version-independent 1.8 constants."""

    __slots__ = ("gravity", "step_height")

    def __init__(self, *, step_height: float = STEP_HEIGHT, gravity: float = GRAVITY) -> None:
        self.step_height = step_height
        self.gravity = gravity

    def step(
        self,
        state: PlayerState,
        controls: ControlState,
        world: _WorldReader,
    ) -> PlayerState:
        """Advance ``state`` by one 20 TPS tick."""
        yaw = float(controls.yaw)
        sprinting = controls.sprint and not controls.sneak
        sneaking = controls.sneak
        input_scale = 0.98 * (SNEAK_MULTIPLIER if sneaking else 1.0)
        forward = _clamp(controls.forward, -1.0, 1.0) * input_scale
        strafe = _clamp(controls.strafe, -1.0, 1.0) * input_scale
        medium = sample_medium(world, state.position, on_ground=state.on_ground)

        velocity = state.velocity
        on_ground = state.on_ground
        if controls.jump:
            if medium.in_water or medium.in_lava:
                velocity = replace(velocity, y=velocity.y + 0.04)
            elif on_ground:
                velocity = replace(velocity, y=JUMP_VELOCITY)
                if sprinting:
                    sin, cos = _sin_cos(yaw)
                    velocity = Vec3(
                        velocity.x - sin * 0.2,
                        velocity.y,
                        velocity.z + cos * 0.2,
                    )
                # Ground friction still applies on the launch tick; the collision result below
                # turns ``on_ground`` off for the following tick.

        if medium.in_water or medium.in_lava:
            acceleration = AIR_ACCELERATION
        elif on_ground:
            friction = medium.slipperiness * 0.91
            speed = PLAYER_SPEED * medium.speed_multiplier
            if sprinting:
                speed *= SPRINT_MULTIPLIER
            acceleration = speed * (_GROUND_ACCELERATION / (friction * friction * friction))
        else:
            # Vanilla gives sprinting players a small airborne acceleration bonus.
            acceleration = AIR_ACCELERATION * (1.3 if sprinting else 1.0)

        velocity = _apply_input(velocity, forward, strafe, yaw, acceleration)
        if medium.on_ladder:
            # 1.8: sneaking holds position on a ladder instead of sliding down.
            ladder_floor = 0.0 if sneaking else -0.15
            velocity = Vec3(
                _clamp(velocity.x, -0.15, 0.15),
                max(velocity.y, ladder_floor),
                _clamp(velocity.z, -0.15, 0.15),
            )

        # Cobwebs scale the movement delta, not the velocity, and zero the velocity after moving.
        in_web = state.in_web
        move_velocity = velocity
        if in_web:
            move_velocity = Vec3(velocity.x * 0.25, velocity.y * 0.05, velocity.z * 0.25)

        result = move_box(
            state.box,
            move_velocity,
            world,
            step_height=self.step_height,
            can_step=on_ground and not sneaking and not medium.in_water and not medium.in_lava,
        )

        if medium.on_ladder and (result.hit_x or result.hit_z):
            # 1.8 climbs while pushing into a ladder. Jump-climbing is a 1.14+ behaviour and is
            # deliberately not used here.
            velocity = replace(velocity, y=0.2)

        vx, vy, vz = velocity.x, velocity.y, velocity.z
        if in_web:
            vx = vy = vz = 0.0
        if result.hit_x:
            vx = 0.0
        if result.hit_z:
            vz = 0.0
        if result.hit_y:
            vy = 0.0

        if medium.in_water:
            vx *= 0.8
            vy = vy * 0.8 - 0.02
            vz *= 0.8
        elif medium.in_lava:
            vx *= 0.5
            vy = vy * 0.5 - 0.02
            vz *= 0.5
        else:
            vy = (vy - self.gravity) * 0.98
            friction = medium.slipperiness * 0.91 if on_ground else 0.91
            vx *= friction
            vz *= friction
            if medium.on_ladder:
                vy = max(vy, 0.0 if sneaking else -0.15)

        box = result.box
        new_position = Vec3(
            (box.min_x + box.max_x) / 2,
            box.min_y,
            (box.min_z + box.max_z) / 2,
        )
        # Flags describe the environment the player is now in; they drive the next tick.
        current = sample_medium(world, new_position, on_ground=result.on_ground)
        return replace(
            state,
            position=new_position,
            velocity=Vec3(vx, vy, vz),
            yaw=yaw,
            pitch=float(controls.pitch),
            on_ground=result.on_ground,
            sprinting=sprinting,
            sneaking=sneaking,
            in_water=current.in_water,
            in_lava=current.in_lava,
            in_web=current.in_web,
            on_ladder=current.on_ladder,
        )


def _apply_input(
    velocity: Vec3, forward: float, strafe: float, yaw: float, acceleration: float
) -> Vec3:
    magnitude = math.sqrt(forward * forward + strafe * strafe)
    if magnitude < 1e-4:
        return velocity
    scale = acceleration / max(magnitude, 1.0)
    sin, cos = _sin_cos(yaw)
    return Vec3(
        velocity.x + (strafe * cos - forward * sin) * scale,
        velocity.y,
        velocity.z + (forward * cos + strafe * sin) * scale,
    )


def _sin_cos(yaw: float) -> tuple[float, float]:
    radians = math.radians(yaw)
    return math.sin(radians), math.cos(radians)


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value
