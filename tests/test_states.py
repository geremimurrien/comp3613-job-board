from types import SimpleNamespace

import pytest

from app.services.application_states import (
    STATES,
    InvalidTransitionError,
    state_for,
)


ACTIONS = ("mark_reviewed", "shortlist", "reject", "hire")


@pytest.mark.parametrize(
    ("from_status", "action", "to_status"),
    [
        ("submitted", "mark_reviewed", "reviewed"),
        ("reviewed", "shortlist", "shortlisted"),
        ("shortlisted", "reject", "rejected"),
        ("shortlisted", "hire", "hired"),
    ],
)
def test_every_legal_transition(from_status, action, to_status):
    app = SimpleNamespace(status=from_status)

    next_state = getattr(STATES[from_status], action)(app)

    assert next_state is STATES[to_status]
    assert app.status == from_status


@pytest.mark.parametrize(
    ("from_status", "action"),
    [
        (from_status, action)
        for from_status in STATES
        for action in ACTIONS
        if not (
            (from_status == "submitted" and action == "mark_reviewed")
            or (from_status == "reviewed" and action == "shortlist")
            or (
                from_status == "shortlisted"
                and action in {"reject", "hire"}
            )
        )
    ],
)
def test_every_illegal_transition(from_status, action):
    app = SimpleNamespace(status=from_status)

    with pytest.raises(InvalidTransitionError) as exc_info:
        getattr(STATES[from_status], action)(app)

    assert exc_info.value.from_status == from_status
    assert exc_info.value.action == action
    assert app.status == from_status


@pytest.mark.parametrize("action", ACTIONS)
def test_rejected_state_rejects_every_action(action):
    with pytest.raises(InvalidTransitionError) as exc_info:
        getattr(STATES["rejected"], action)(SimpleNamespace(status="rejected"))

    assert exc_info.value.from_status == "rejected"
    assert exc_info.value.action == action


@pytest.mark.parametrize("action", ACTIONS)
def test_hired_state_rejects_every_action(action):
    with pytest.raises(InvalidTransitionError) as exc_info:
        getattr(STATES["hired"], action)(SimpleNamespace(status="hired"))

    assert exc_info.value.from_status == "hired"
    assert exc_info.value.action == action


@pytest.mark.parametrize(
    ("status", "terminal"),
    [
        ("submitted", False),
        ("reviewed", False),
        ("shortlisted", False),
        ("rejected", True),
        ("hired", True),
    ],
)
def test_state_for_all_statuses(status, terminal):
    state = state_for(status)

    assert state is STATES[status]
    assert state.name == status
    assert state.is_terminal is terminal


def test_state_for_unknown_status():
    with pytest.raises(ValueError, match="unknown application status"):
        state_for("cancelled")

