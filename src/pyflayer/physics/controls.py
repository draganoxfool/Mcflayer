"""Movement input for one physics tick (M4)."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ControlState"]


@dataclass(frozen=True, slots=True)
class ControlState:
    """Player input sampled at a physics tick.

    ``forward`` is positive towards the facing direction, ``strafe`` is positive to the player's
    left. Both are clamped to ``-1..1`` by the engine. Yaw follows Minecraft's convention:
    ``0`` faces south (+Z), ``90`` faces west (-X).
    """

    forward: float = 0.0
    strafe: float = 0.0
    jump: bool = False
    sneak: bool = False
    sprint: bool = False
    yaw: float = 0.0
    pitch: float = 0.0
