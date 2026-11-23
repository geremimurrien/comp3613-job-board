import pytest

from app.models.application import Application
from app.models.status_change import StatusChange
from app.services.application_states import InvalidTransitionError, state_for


def test_application_state_uses_status():
    app = Application(
        listing_id=1,
        graduate_id=2,
        cover_letter="letter",
        resume_text="resume",
        status="shortlisted",
    )

    assert app.state() is state_for("shortlisted")
    assert app.state().name == "shortlisted"
    assert app.state().is_terminal is False


def test_perform_legal_move_and_status_change_fields():
    app = Application(
        id=10,
        listing_id=1,
        graduate_id=2,
        cover_letter="letter",
        resume_text="resume",
        status="submitted",
    )

    change = app.perform("mark_reviewed", actor_id=3)

    assert app.status == "reviewed"
    assert isinstance(change, StatusChange)
    assert change.application_id == 10
    assert change.actor_id == 3
    assert change.from_status == "submitted"
    assert change.to_status == "reviewed"
    assert change.changed_at is not None


def test_perform_illegal_move_leaves_status_unchanged():
    app = Application(
        listing_id=1,
        graduate_id=2,
        cover_letter="letter",
        resume_text="resume",
        status="reviewed",
    )

    with pytest.raises(InvalidTransitionError) as exc:
        app.perform("reject", actor_id=3)

    assert exc.value.from_status == "reviewed"
    assert exc.value.action == "reject"
    assert app.status == "reviewed"


def test_rejected_and_hired_are_terminal():
    rejected = Application(
        listing_id=1,
        graduate_id=2,
        cover_letter="letter",
        resume_text="resume",
        status="rejected",
    )
    hired = Application(
        listing_id=1,
        graduate_id=2,
        cover_letter="letter",
        resume_text="resume",
        status="hired",
    )

    assert rejected.state().is_terminal is True
    assert hired.state().is_terminal is True
