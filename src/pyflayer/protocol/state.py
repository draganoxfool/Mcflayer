"""Connection-state machine.

Minecraft's protocol is stateful: a connection lives in exactly one state and every packet id is
interpreted relative to that state. Transitions happen at frame boundaries and are listed in
:data:`LEGAL_TRANSITIONS`; anything else raises :class:`~pyflayer.errors.StateError`.

The configuration state is declared for 1.20.2+ servers but is only reachable when the loaded data
advertises it. 1.8.9 goes ``handshaking -> login -> play`` directly.

Examples:
    >>> sm = StateMachine()
    >>> sm.transition(ConnectionState.LOGIN).value
    'login'
    >>> sm.transition(ConnectionState.STATUS)
    Traceback (most recent call last):
    ...
    pyflayer.errors.StateError: illegal connection state transition
        (current='login', target='status')
"""

from __future__ import annotations

from typing import Final

from pyflayer.errors import StateError
from pyflayer.models.enums import ConnectionState

__all__ = ["LEGAL_TRANSITIONS", "ConnectionState", "StateMachine"]

#: ``state -> states it may move to``. ``closed`` is terminal.
LEGAL_TRANSITIONS: Final[dict[ConnectionState, frozenset[ConnectionState]]] = {
    ConnectionState.HANDSHAKING: frozenset(
        {ConnectionState.STATUS, ConnectionState.LOGIN, ConnectionState.CLOSED}
    ),
    ConnectionState.STATUS: frozenset({ConnectionState.CLOSED}),
    ConnectionState.LOGIN: frozenset(
        {ConnectionState.CONFIGURATION, ConnectionState.PLAY, ConnectionState.CLOSED}
    ),
    # Servers may re-enter configuration from play (1.20.2+) and go back again.
    ConnectionState.CONFIGURATION: frozenset({ConnectionState.PLAY, ConnectionState.CLOSED}),
    ConnectionState.PLAY: frozenset({ConnectionState.CONFIGURATION, ConnectionState.CLOSED}),
    ConnectionState.CLOSED: frozenset(),
}


class StateMachine:
    """Tracks and validates the state of one connection.

    Args:
        initial: Starting state (``handshaking`` after the TCP connect).

    Raises:
        StateError: On an illegal transition, including any transition after ``closed``.
    """

    __slots__ = ("_history", "_state")

    def __init__(self, initial: ConnectionState = ConnectionState.HANDSHAKING) -> None:
        self._state = initial
        self._history: list[ConnectionState] = [initial]

    @property
    def state(self) -> ConnectionState:
        """Current state."""
        return self._state

    @property
    def history(self) -> tuple[ConnectionState, ...]:
        """States visited, oldest first."""
        return tuple(self._history)

    @property
    def closed(self) -> bool:
        """True once the connection reached ``closed``."""
        return self._state is ConnectionState.CLOSED

    def can(self, target: ConnectionState) -> bool:
        """Return whether ``target`` is reachable from the current state."""
        return target in LEGAL_TRANSITIONS[self._state]

    def transition(self, target: ConnectionState) -> ConnectionState:
        """Move to ``target`` and return the new state.

        Raises:
            StateError: When the transition is not in :data:`LEGAL_TRANSITIONS`.
        """
        if target is self._state:
            return self._state
        if not self.can(target):
            raise StateError(
                "illegal connection state transition",
                current=str(self._state),
                target=str(target),
            )
        self._state = target
        self._history.append(target)
        return target

    def close(self) -> None:
        """Move to ``closed`` (idempotent)."""
        if self._state is not ConnectionState.CLOSED:
            self._state = ConnectionState.CLOSED
            self._history.append(ConnectionState.CLOSED)

    def __repr__(self) -> str:
        return f"StateMachine(state={self._state.value!r})"
