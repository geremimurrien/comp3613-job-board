from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import engine
from app.main import app
from app.models.application import Application
from app.models.notification import Notification
from app.seed import seed


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_demo_data():
    seed(reset=True)
    yield


def login(email: str, password: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return response.json()["user"]


def submit_collect_listing(employer_id: int, title: str = "UAT Engineer") -> dict:
    response = client.post(
        "/api/employer/listings",
        json={
            "title": title,
            "company": "UAT Co",
            "description": "A listing created for UAT.",
            "apply_mode": "collect",
            "deadline": (TODAY + timedelta(days=30)).isoformat(),
            "actor_id": employer_id,
        },
    )
    assert response.status_code == 200
    return response.json()


TODAY = datetime.now(timezone.utc).date()


def test_uat_login_shows_account_without_password():
    user = login("grad.dcit@example.com", "grad-dev")

    assert user["role"] == "graduate"
    assert user["programme"] == "DCIT"
    assert "password" not in user


def test_uat_employer_submits_listing_stays_pending():
    employer = login("employer@example.com", "employer-dev")

    result = submit_collect_listing(employer["id"])

    assert result["status"] == "pending"
    with Session(engine) as session:
        pending = session.exec(select(Application)).all()
        assert pending == []

    graduate_jobs = client.get("/api/jobs").json()["jobs"]
    assert all(job["id"] != result["listing_id"] for job in graduate_jobs)


def test_uat_admin_publishes_listing_and_notifies_subscriber():
    employer = login("employer@example.com", "employer-dev")
    admin = login("admin@example.com", "admin-dev")
    graduate = login("grad.dcit@example.com", "grad-dev")

    subscribe = client.post(
        "/api/graduates/subscribe",
        json={"actor_id": graduate["id"]},
    )
    assert subscribe.status_code == 200

    listing = submit_collect_listing(employer["id"], "UAT Published Engineer")
    response = client.post(
        f"/api/admin/listings/{listing['listing_id']}/publish",
        json={"actor_id": admin["id"]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "published"
    assert response.json()["notification_count"] >= 1
    jobs = client.get("/api/jobs").json()["jobs"]
    assert any(job["id"] == listing["listing_id"] for job in jobs)

    with Session(engine) as session:
        notifications = session.exec(
            select(Notification).where(Notification.user_id == graduate["id"])
        ).all()
        assert notifications


def test_uat_application_complete_lifecycle():
    employer = login("employer@example.com", "employer-dev")
    graduate = login("grad.dcit@example.com", "grad-dev")
    admin = login("admin@example.com", "admin-dev")
    listing = submit_collect_listing(employer["id"], "UAT Lifecycle Engineer")

    published = client.post(
        f"/api/admin/listings/{listing['listing_id']}/publish",
        json={"actor_id": admin["id"]},
    )
    assert published.status_code == 200

    applied = client.post(
        "/api/graduates/applications",
        json={
            "listing_id": listing["listing_id"],
            "cover_letter": "I am qualified for this role.",
            "resume_text": "Python, APIs, testing",
            "actor_id": graduate["id"],
        },
    )
    assert applied.status_code == 200
    application_id = applied.json()["application_id"]
    assert applied.json()["status"] == "submitted"

    for action, expected_status in (
        ("mark_reviewed", "reviewed"),
        ("shortlist", "shortlisted"),
        ("hire", "hired"),
    ):
        transitioned = client.post(
            f"/api/applications/{application_id}/transition",
            json={"action": action, "actor_id": employer["id"]},
        )
        assert transitioned.status_code == 200
        assert transitioned.json()["application"]["status"] == expected_status

    my_applications = client.get(
        "/api/graduates/applications",
        params={"actor_id": graduate["id"]},
    )
    assert my_applications.status_code == 200
    assert my_applications.json()["applications"][0]["status"] == "hired"


def test_uat_application_illegal_and_terminal_transitions_are_rejected():
    employer = login("employer@example.com", "employer-dev")
    graduate = login("grad.dcit@example.com", "grad-dev")
    admin = login("admin@example.com", "admin-dev")
    listing = submit_collect_listing(employer["id"], "UAT Illegal Transition")
    assert client.post(
        f"/api/admin/listings/{listing['listing_id']}/publish",
        json={"actor_id": admin["id"]},
    ).status_code == 200
    applied = client.post(
        "/api/graduates/applications",
        json={
            "listing_id": listing["listing_id"],
            "cover_letter": "Please consider my application.",
            "resume_text": "Resume",
            "actor_id": graduate["id"],
        },
    )
    application_id = applied.json()["application_id"]

    illegal = client.post(
        f"/api/applications/{application_id}/transition",
        json={"action": "hire", "actor_id": employer["id"]},
    )
    assert illegal.status_code == 400

    for action in ("mark_reviewed", "shortlist", "reject"):
        legal_rejection = client.post(
            f"/api/applications/{application_id}/transition",
            json={"action": action, "actor_id": employer["id"]},
        )
        if action == "mark_reviewed":
            assert legal_rejection.status_code == 200

    terminal = client.post(
        f"/api/applications/{application_id}/transition",
        json={"action": "hire", "actor_id": employer["id"]},
    )
    assert terminal.status_code == 400


def test_uat_only_listing_employer_can_view_and_transition_applications():
    owner = login("employer@example.com", "employer-dev")
    other = login("employer2@example.com", "employer-dev")
    graduate = login("grad.dcit@example.com", "grad-dev")
    admin = login("admin@example.com", "admin-dev")
    listing = submit_collect_listing(owner["id"], "UAT Restricted Listing")
    assert client.post(
        f"/api/admin/listings/{listing['listing_id']}/publish",
        json={"actor_id": admin["id"]},
    ).status_code == 200
    applied = client.post(
        "/api/graduates/applications",
        json={
            "listing_id": listing["listing_id"],
            "cover_letter": "Applicant cover letter",
            "resume_text": "Applicant resume",
            "actor_id": graduate["id"],
        },
    )
    application_id = applied.json()["application_id"]

    denied_view = client.get(
        f"/api/listings/{listing['listing_id']}/applicants",
        params={"actor_id": other["id"]},
    )
    denied_transition = client.post(
        f"/api/applications/{application_id}/transition",
        json={"action": "mark_reviewed", "actor_id": other["id"]},
    )
    admin_transition = client.post(
        f"/api/applications/{application_id}/transition",
        json={"action": "mark_reviewed", "actor_id": admin["id"]},
    )

    assert denied_view.status_code == 403
    assert denied_transition.status_code == 400
    assert admin_transition.status_code == 400


def test_uat_expired_and_pending_listings_are_hidden_from_graduates():
    jobs = client.get("/api/jobs").json()["jobs"]
    titles = {job["title"] for job in jobs}

    assert "Expired Analyst Role" not in titles
    assert "QA Intern" not in titles
    assert "Junior Software Engineer" in titles


def test_uat_external_listing_does_not_collect_in_platform_application():
    graduate = login("grad.dcit@example.com", "grad-dev")
    admin = login("admin@example.com", "admin-dev")
    pending_external = next(
        listing
        for listing in client.get(
            "/api/admin/listings/pending",
            params={"actor_id": admin["id"]},
        ).json()["listings"]
        if listing["apply_mode"] == "external"
    )
    assert client.post(
        f"/api/admin/listings/{pending_external['id']}/publish",
        json={"actor_id": admin["id"]},
    ).status_code == 200

    applied = client.post(
        "/api/graduates/applications",
        json={
            "listing_id": pending_external["id"],
            "cover_letter": "This should not be collected.",
            "resume_text": "Resume",
            "actor_id": graduate["id"],
        },
    )

    assert applied.status_code == 400
    assert "external" in applied.json()["detail"].lower()
    with Session(engine) as session:
        assert session.exec(
            select(Application).where(
                Application.listing_id == pending_external["id"]
            )
        ).all() == []


def test_uat_non_dcit_graduate_cannot_subscribe_or_apply():
    graduate = login("grad.other@example.com", "grad-dev")

    subscription = client.post(
        "/api/graduates/subscribe",
        json={"actor_id": graduate["id"]},
    )
    application = client.post(
        "/api/graduates/applications",
        json={
            "listing_id": 1,
            "cover_letter": "Not eligible",
            "resume_text": "Resume",
            "actor_id": graduate["id"],
        },
    )

    assert subscription.status_code == 400
    assert application.status_code == 400
