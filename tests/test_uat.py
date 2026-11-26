from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models
from app.main import app
from app.models.listing import Listing
from app.models.notification import Notification
from app.models.user import User
from app.services import applications, board_auth, listings
from app.utilities.security import encrypt_password


@pytest.fixture
def uat_context(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(applications, "engine", test_engine)
    monkeypatch.setattr(listings, "engine", test_engine)
    monkeypatch.setattr(board_auth, "engine", test_engine)

    users = [
        User(
            username="uat-admin",
            email="uat-admin@example.com",
            password=encrypt_password("uat-admin-password"),
            role="admin",
        ),
        User(
            username="uat-employer",
            email="uat-employer@example.com",
            password=encrypt_password("uat-employer-password"),
            role="employer",
        ),
        User(
            username="uat-graduate",
            email="uat-graduate@example.com",
            password=encrypt_password("uat-graduate-password"),
            role="graduate",
            programme="DCIT",
            resume_text="UAT resume",
        ),
    ]
    with Session(test_engine) as session:
        session.add_all(users)
        session.commit()
        for user in users:
            session.refresh(user)
        user_ids = {
            "admin": users[0].id,
            "employer": users[1].id,
            "graduate": users[2].id,
        }

    yield TestClient(app), user_ids, test_engine

    SQLModel.metadata.drop_all(test_engine)
    test_engine.dispose()


def api_login(client: TestClient, email: str, password: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    return response.json()["user"]


def test_uat_listing_submission_to_publication_workflow(uat_context):
    client, _, test_engine = uat_context
    employer = api_login(
        client, "uat-employer@example.com", "uat-employer-password"
    )
    admin = api_login(client, "uat-admin@example.com", "uat-admin-password")
    graduate = api_login(
        client, "uat-graduate@example.com", "uat-graduate-password"
    )

    subscription = client.post(
        "/api/graduates/subscribe",
        json={"actor_id": graduate["id"]},
    )
    assert subscription.status_code == 200

    submitted = client.post(
        "/api/employer/listings",
        json={
            "title": "UAT Workflow Engineer",
            "company": "UAT Company",
            "description": "A listing used to verify the approval workflow.",
            "apply_mode": "collect",
            "deadline": (date.today() + timedelta(days=30)).isoformat(),
            "actor_id": employer["id"],
        },
    )
    assert submitted.status_code == 200
    listing_id = submitted.json()["listing_id"]
    assert submitted.json()["status"] == "pending"

    pending = client.get(
        "/api/admin/listings/pending",
        params={"actor_id": admin["id"]},
    )
    assert pending.status_code == 200
    pending_listing = next(
        item for item in pending.json()["listings"] if item["id"] == listing_id
    )
    assert pending_listing["status"] == "pending"
    assert all(
        item["id"] != listing_id
        for item in client.get("/api/jobs").json()["jobs"]
    )

    published = client.post(
        f"/api/admin/listings/{listing_id}/publish",
        json={"actor_id": admin["id"]},
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["notification_count"] == 1

    jobs = client.get("/api/jobs")
    assert jobs.status_code == 200
    published_listing = next(
        item for item in jobs.json()["jobs"] if item["id"] == listing_id
    )
    assert published_listing["status"] == "published"

    with Session(test_engine) as session:
        notifications = session.exec(
            select(Notification).where(
                Notification.user_id == graduate["id"]
            )
        ).all()
    assert len(notifications) == 1
    assert "UAT Workflow Engineer" in notifications[0].message


def test_uat_application_successful_lifecycle_through_api(uat_context):
    client, user_ids, test_engine = uat_context
    with Session(test_engine) as session:
        listing = Listing(
            employer_id=user_ids["employer"],
            title="UAT Lifecycle Engineer",
            company="UAT Company",
            description="A published listing for application lifecycle testing.",
            apply_mode="collect",
            deadline=(date.today() + timedelta(days=30)).isoformat(),
            status="published",
        )
        session.add(listing)
        session.commit()
        session.refresh(listing)
        listing_id = listing.id

    applied = client.post(
        "/api/graduates/applications",
        json={
            "listing_id": listing_id,
            "cover_letter": "I am interested in this role.",
            "resume_text": "UAT resume",
            "actor_id": user_ids["graduate"],
        },
    )
    assert applied.status_code == 200
    application_id = applied.json()["application_id"]
    assert applied.json()["status"] == "submitted"

    from_status = "submitted"
    for action, expected_status in (
        ("mark_reviewed", "reviewed"),
        ("shortlist", "shortlisted"),
        ("hire", "hired"),
    ):
        response = client.post(
            f"/api/applications/{application_id}/transition",
            json={"action": action, "actor_id": user_ids["employer"]},
        )
        assert response.status_code == 200
        assert response.json()["application_id"] == application_id
        assert response.json()["from_status"] == from_status
        assert response.json()["to_status"] == expected_status
        assert response.json()["action"] == action
        from_status = expected_status

    applications_response = client.get(
        "/api/graduates/applications",
        params={"actor_id": user_ids["graduate"]},
    )
    assert applications_response.status_code == 200
    created_application = next(
        item
        for item in applications_response.json()["applications"]
        if item["id"] == application_id
    )
    assert created_application["status"] == "hired"


def test_uat_login_response_does_not_expose_password_information(uat_context):
    client, _, _ = uat_context

    response = client.post(
        "/api/auth/login",
        json={
            "email": "uat-graduate@example.com",
            "password": "uat-graduate-password",
        },
    )

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["role"] == "graduate"
    assert all("password" not in key.lower() for key in user)
    assert "uat-graduate-password" not in response.text
