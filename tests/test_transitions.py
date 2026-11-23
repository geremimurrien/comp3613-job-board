from collections.abc import Iterator

import pytest
from app.models.status_change import StatusChange
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import engine
from app.main import app
from app.models.application import Application
from app.models.listing import Listing
from app.models.notification import Notification
from app.models.user import User
from app.seed import seed

client = TestClient(app)


@pytest.fixture
def scenario() -> Iterator[dict[str, int]]:
    seed(reset=True)
    with Session(engine) as session:
        users = {
            user.email: user.id
            for user in session.exec(select(User)).all()
        }
        listing = session.exec(
            select(Listing)
            .where(Listing.employer_id == users["employer@example.com"])
            .order_by(Listing.id)
        ).first()
        assert listing is not None
        test_scenario = {
            "admin_id": users["admin@example.com"],
            "graduate_id": users["grad.dcit@example.com"],
            "employer_id": users["employer@example.com"],
            "other_employer_id": users["employer2@example.com"],
            "listing_id": listing.id,
        }
    yield test_scenario


def create_application(scenario: dict[str, int], status: str) -> int:
    with Session(engine) as session:
        application = Application(
            listing_id=scenario["listing_id"],
            graduate_id=scenario["graduate_id"],
            cover_letter="Cover letter",
            resume_text="Resume",
            status=status,
        )
        session.add(application)
        session.commit()
        session.refresh(application)
        return application.id


def transition(actor_id: int, application_id: int, action: str):
    return client.post(
        f"/api/applications/{application_id}/transition",
        json={"actor_id": actor_id, "action": action},
    )


def persisted_transition_rows() -> tuple[int, int]:
    with Session(engine) as session:
        changes = len(session.exec(select(StatusChange)).all())
        notifications = len(session.exec(select(Notification)).all())
    return changes, notifications


def test_listing_owner_can_transition_and_persists_change_and_notification(
    scenario: dict[str, int],
) -> None:
    application_id = create_application(scenario, "submitted")

    response = transition(scenario["employer_id"], application_id, "mark_reviewed")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "application_id": application_id,
        "from_status": "submitted",
        "to_status": "reviewed",
        "action": "mark_reviewed",
    }
    assert persisted_transition_rows() == (1, 1)


@pytest.mark.parametrize("role_key", ["admin_id", "other_employer_id"])
def test_non_owner_cannot_transition(
    scenario: dict[str, int], role_key: str
) -> None:
    application_id = create_application(scenario, "submitted")

    response = transition(scenario[role_key], application_id, "mark_reviewed")

    assert response.status_code == 403
    assert persisted_transition_rows() == (0, 0)


def test_every_illegal_transition_is_refused_without_persistence(
    scenario: dict[str, int],
) -> None:
    legal = {
        ("submitted", "mark_reviewed"),
        ("reviewed", "shortlist"),
        ("shortlisted", "reject"),
        ("shortlisted", "hire"),
    }
    for status in ("submitted", "reviewed", "shortlisted", "rejected", "hired"):
        for action in ("mark_reviewed", "shortlist", "reject", "hire"):
            if (status, action) in legal:
                continue
            application_id = create_application(scenario, status)
            response = transition(
                scenario["employer_id"], application_id, action
            )
            assert response.status_code == 409, (status, action)
            detail = response.json()["detail"]
            assert status in detail
            assert action in detail
            assert persisted_transition_rows() == (0, 0)


def test_unknown_action_returns_400_without_persistence(
    scenario: dict[str, int],
) -> None:
    application_id = create_application(scenario, "submitted")

    response = transition(scenario["employer_id"], application_id, "reopen")

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown action: reopen"
    assert persisted_transition_rows() == (0, 0)


def test_closed_listing_blocks_submitted_and_reviewed_but_not_shortlisted(
    scenario: dict[str, int],
) -> None:
    with Session(engine) as session:
        listing = session.get(Listing, scenario["listing_id"])
        assert listing is not None
        listing.status = "unpublished"
        session.add(listing)
        session.commit()

    for status, action in (
        ("submitted", "mark_reviewed"),
        ("reviewed", "shortlist"),
    ):
        application_id = create_application(scenario, status)
        response = transition(scenario["employer_id"], application_id, action)
        assert response.status_code == 409
        assert "closed" in response.json()["detail"]
        assert persisted_transition_rows() == (0, 0)

    shortlisted_id = create_application(scenario, "shortlisted")
    response = transition(scenario["employer_id"], shortlisted_id, "hire")

    assert response.status_code == 200
    assert response.json()["to_status"] == "hired"
    assert persisted_transition_rows() == (1, 1)


def test_applicants_include_state_actions_and_status_history(
    scenario: dict[str, int],
) -> None:
    application_id = create_application(scenario, "submitted")
    transition(scenario["employer_id"], application_id, "mark_reviewed")

    response = client.get(
        f"/api/listings/{scenario['listing_id']}/applicants",
        params={"actor_id": scenario["employer_id"]},
    )

    assert response.status_code == 200
    applicant = response.json()["applicants"][0]
    assert applicant["allowed_actions"] == ["shortlist"]
    assert len(applicant["status_history"]) == 1
    assert applicant["status_history"][0]["from_status"] == "submitted"
    assert applicant["status_history"][0]["to_status"] == "reviewed"


def test_graduate_cannot_access_applicants_route(
    scenario: dict[str, int],
) -> None:
    response = client.get(
        f"/api/listings/{scenario['listing_id']}/applicants",
        params={"actor_id": scenario["graduate_id"]},
    )

    assert response.status_code == 403
