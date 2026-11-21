from __future__ import annotations

import pytest

from pyflayer.errors import StateError
from pyflayer.protocol.state import ConnectionState, StateMachine


def test_handshake_login_play() -> None:
    sm = StateMachine()
    assert sm.state is ConnectionState.HANDSHAKING
    assert sm.transition(ConnectionState.LOGIN) is ConnectionState.LOGIN
    assert sm.transition(ConnectionState.PLAY) is ConnectionState.PLAY
    assert sm.history == (
        ConnectionState.HANDSHAKING,
        ConnectionState.LOGIN,
        ConnectionState.PLAY,
    )


def test_configuration_roundtrip() -> None:
    sm = StateMachine(ConnectionState.LOGIN)
    sm.transition(ConnectionState.CONFIGURATION)
    sm.transition(ConnectionState.PLAY)
    sm.transition(ConnectionState.CONFIGURATION)
    assert sm.state is ConnectionState.CONFIGURATION


def test_illegal_transition_raises_with_fields() -> None:
    sm = StateMachine()
    sm.transition(ConnectionState.LOGIN)
    with pytest.raises(StateError) as info:
        sm.transition(ConnectionState.STATUS)
    assert info.value.fields["current"] == "login"
    assert info.value.fields["target"] == "status"
    assert not sm.can(ConnectionState.STATUS)
    assert sm.state is ConnectionState.LOGIN


def test_close_is_terminal_and_idempotent() -> None:
    sm = StateMachine()
    sm.close()
    sm.close()
    assert sm.closed
    assert sm.history == (ConnectionState.HANDSHAKING, ConnectionState.CLOSED)
    with pytest.raises(StateError):
        sm.transition(ConnectionState.LOGIN)
