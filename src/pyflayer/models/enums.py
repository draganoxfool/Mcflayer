"""Enums with a fixed Minecraft meaning. Version-specific values live in ``data``."""

from __future__ import annotations

from enum import IntEnum, StrEnum

__all__ = ["Dimension", "GameMode", "Face", "Hand", "Difficulty", "Pose", "ConnectionState"]


class Dimension(StrEnum):
    """Logical dimension identifiers used by the play protocol."""

    OVERWORLD = "overworld"
    NETHER = "the_nether"
    END = "the_end"


class GameMode(IntEnum):
    """Vanilla game modes (wire values)."""

    SURVIVAL = 0
    CREATIVE = 1
    ADVENTURE = 2
    SPECTATOR = 3


class Face(IntEnum):
    """Block face ordering, matching vanilla's direction enum for placement."""

    DOWN = 0
    UP = 1
    NORTH = 2
    SOUTH = 3
    WEST = 4
    EAST = 5

    @property
    def offset(self) -> tuple[int, int, int]:
        """Unit offset of the adjacent block for this face."""
        return {
            Face.DOWN: (0, -1, 0),
            Face.UP: (0, 1, 0),
            Face.NORTH: (0, 0, -1),
            Face.SOUTH: (0, 0, 1),
            Face.WEST: (-1, 0, 0),
            Face.EAST: (1, 0, 0),
        }[self]


class Hand(IntEnum):
    """Interaction hand."""

    MAIN = 0
    OFF = 1


class Difficulty(IntEnum):
    """World difficulty."""

    PEACEFUL = 0
    EASY = 1
    NORMAL = 2
    HARD = 3


class Pose(IntEnum):
    """Player pose, used by physics metadata."""

    STANDING = 0
    SLEEPING = 1
    FALL_FLYING = 2
    SWIMMING = 3
    SPIN_ATTACK = 4
    SNEAKING = 5
    LONG_JUMPING = 6
    DYING = 7
    CROAKING = 8
    USING_TONGUE = 9
    SITTING = 10
    ROARING = 11
    SNIFFING = 12
    EMERGING = 13
    DIGGING = 14


class ConnectionState(StrEnum):
    """Protocol state names, matching the keys in ``minecraft-data`` protocol.json.

    ``configuration`` exists only for 1.20.2+; 1.8.9 goes from ``login`` straight to ``play``.
    ``closed`` is terminal.
    """

    HANDSHAKING = "handshaking"
    STATUS = "status"
    LOGIN = "login"
    CONFIGURATION = "configuration"
    PLAY = "play"
    CLOSED = "closed"
