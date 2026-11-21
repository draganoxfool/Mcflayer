"""Client movement packet cadence (1.8).

Vanilla sends a position packet when the squared movement since the last sent position exceeds
``4e-8``, every 20 ticks as a reminder, or when rotation/ground state changes. This class is pure so
the cadence can be tested without a socket.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyflayer.models.vec3 import Vec3

__all__ = ["MovementPacket", "MovementTracker"]

_POSITION_EPSILON_SQ = 4e-8
_ROTATION_EPSILON = 1e-5
_REMINDER_TICKS = 20


@dataclass(frozen=True, slots=True)
class MovementPacket:
    """A toServer movement packet name and its encoded fields."""

    name: str
    fields: dict[str, object]


class MovementTracker:
    """Decide which movement packet to send for the current tick."""

    __slots__ = (
        "last_on_ground",
        "last_pitch",
        "last_position",
        "last_yaw",
        "reminder_ticks",
        "threshold_sq",
        "ticks_since_send",
    )

    def __init__(
        self,
        *,
        reminder_ticks: int = _REMINDER_TICKS,
        threshold_sq: float = _POSITION_EPSILON_SQ,
    ) -> None:
        self.last_position = Vec3(0.0, 0.0, 0.0)
        self.last_yaw = 0.0
        self.last_pitch = 0.0
        self.last_on_ground = False
        self.ticks_since_send = 0
        self.reminder_ticks = reminder_ticks
        self.threshold_sq = threshold_sq

    def reset(
        self,
        position: Vec3,
        yaw: float,
        pitch: float,
        on_ground: bool,
    ) -> None:
        """Treat ``position`` as already acknowledged (for example after a teleport)."""
        self.last_position = position
        self.last_yaw = yaw
        self.last_pitch = pitch
        self.last_on_ground = on_ground
        self.ticks_since_send = 0

    def confirm(
        self,
        position: Vec3,
        yaw: float,
        pitch: float,
        on_ground: bool,
        *,
        teleport_id: int | None = None,
    ) -> MovementPacket:
        """Build the immediate confirmation for a server teleport.

        1.9+ uses ``teleport_confirm`` with the server id. 1.8 has no teleport id, so the client
        confirms by echoing its position with ``position_look``.
        """
        self.reset(position, yaw, pitch, on_ground)
        if teleport_id is not None:
            return MovementPacket("teleport_confirm", {"teleportId": teleport_id})
        return MovementPacket(
            "position_look",
            {
                "x": position.x,
                "y": position.y,
                "z": position.z,
                "yaw": yaw,
                "pitch": pitch,
                "onGround": on_ground,
            },
        )

    def observe(
        self,
        position: Vec3,
        yaw: float,
        pitch: float,
        on_ground: bool,
    ) -> MovementPacket | None:
        """Return the packet for this tick, or ``None`` when the client should stay silent."""
        self.ticks_since_send += 1
        moved = (position - self.last_position).length_squared() > self.threshold_sq
        rotated = (
            abs(yaw - self.last_yaw) > _ROTATION_EPSILON
            or abs(pitch - self.last_pitch) > _ROTATION_EPSILON
        )
        ground_changed = on_ground != self.last_on_ground
        reminder = self.ticks_since_send >= self.reminder_ticks

        if not (moved or rotated or ground_changed or reminder):
            return None

        if moved or reminder:
            name = "position_look" if rotated else "position"
            fields: dict[str, object] = {
                "x": position.x,
                "y": position.y,
                "z": position.z,
                "onGround": on_ground,
            }
            if rotated:
                fields["yaw"] = yaw
                fields["pitch"] = pitch
        elif rotated:
            name = "look"
            fields = {"yaw": yaw, "pitch": pitch, "onGround": on_ground}
        else:
            name = "flying"
            fields = {"onGround": on_ground}

        self.last_position = position
        self.last_yaw = yaw
        self.last_pitch = pitch
        self.last_on_ground = on_ground
        self.ticks_since_send = 0
        return MovementPacket(name, fields)
