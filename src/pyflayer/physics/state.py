"""Player pose and velocity (M4)."""

from __future__ import annotations

from dataclasses import dataclass

from pyflayer.models.aabb import AABB
from pyflayer.models.vec3 import Vec3

__all__ = [
    "PlayerState",
    "PLAYER_WIDTH",
    "PLAYER_HEIGHT",
    "PLAYER_EYE_HEIGHT",
]

PLAYER_WIDTH = 0.6
PLAYER_HEIGHT = 1.8
PLAYER_EYE_HEIGHT = 1.62


@dataclass(frozen=True, slots=True)
class PlayerState:
    """Simulation state for one player.

    ``position`` is the feet position (the bottom centre of the hitbox), matching the protocol's
    position packet. The hitbox is ``0.6 x 1.8 x 0.6`` centred on X/Z.
    """

    position: Vec3
    velocity: Vec3 = Vec3(0.0, 0.0, 0.0)
    yaw: float = 0.0
    pitch: float = 0.0
    on_ground: bool = False
    sprinting: bool = False
    sneaking: bool = False
    in_water: bool = False
    in_lava: bool = False
    in_web: bool = False
    on_ladder: bool = False

    @property
    def box(self) -> AABB:
        """Player hitbox at the current position."""
        return AABB.from_center(self.position, PLAYER_WIDTH / 2, PLAYER_HEIGHT)

    @property
    def eye_position(self) -> Vec3:
        """Eye position (used by raycasts and look packets)."""
        return self.position + Vec3(0.0, PLAYER_EYE_HEIGHT, 0.0)
