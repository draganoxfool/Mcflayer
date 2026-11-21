"""Physics: deterministic player simulation and the 20 TPS tick driver (M4)."""

from __future__ import annotations

from pyflayer.physics.collision import STEP_HEIGHT, MoveResult, move_box
from pyflayer.physics.controls import ControlState
from pyflayer.physics.engine import GRAVITY, JUMP_VELOCITY, PLAYER_SPEED, PhysicsEngine
from pyflayer.physics.media import Medium, sample_medium
from pyflayer.physics.state import (
    PLAYER_EYE_HEIGHT,
    PLAYER_HEIGHT,
    PLAYER_WIDTH,
    PlayerState,
)
from pyflayer.physics.tick import TickDriver

__all__ = [
    "GRAVITY",
    "JUMP_VELOCITY",
    "PLAYER_EYE_HEIGHT",
    "PLAYER_HEIGHT",
    "PLAYER_SPEED",
    "PLAYER_WIDTH",
    "STEP_HEIGHT",
    "ControlState",
    "Medium",
    "MoveResult",
    "PhysicsEngine",
    "PlayerState",
    "TickDriver",
    "move_box",
    "sample_medium",
]
