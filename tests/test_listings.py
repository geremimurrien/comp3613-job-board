from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.listing import Listing
from app.models.notification import Notification
from app.models.subscription import Subscription
from app.routers import board
from app.services import listings

TODAY = datetime.now(timezone.utc).date()


@pytest.fixture
def listing_db(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(listings, "engine", test_engine)
    users = {
        1: {"id": 1, "role": "admin"},
        2: {"id": 2, "role": "employer"},
        3: {"id": 3, "role": "graduate"},
        4: {"id": 4, "role": "graduate"},
    }
    monkeypatch.setattr(listings, "get_user", lambda user_id: users.get(user_id))
    yield test_engine
    SQLModel.metadata.drop_all(test_engine)
    test_engine.dispose()


def add_listing(
    session: Session,
    *,
    status: str = "pending",
    deadline: str | None = None,
) -> int:
    listing = Listing(
        employer_id=2,
        title="Software Engineer",
        company="Example Co",
        description="Build software",
        apply_mode="collect",
        deadline=deadline or (TODAY + timedelta(days=1)).isoformat(),
        status=status,
    )
    session.add(listing)
    session.commit()
    session.refresh(listing)
    return listing.id


def test_submit_listing_starts_pending(listing_db):
    result = listings.submit_listing(
        2, "Developer", "Example Co", "Build software", "collect",
        (TODAY + timedelta(days=2)).isoformat(),
    )

    assert result["ok"] is True
    assert result["status"] == "pending"
    with Session(listing_db) as session:
        saved = session.get(Listing, result["listing_id"])
        assert saved is not None
        assert saved.status == "pending"


@pytest.mark.parametrize(
    ("status", "deadline", "expected"),
    [
        ("pending", TODAY + timedelta(days=1), False),
        ("published", TODAY - timedelta(days=1), False),
        ("published", TODAY, True),
        ("published", TODAY + timedelta(days=1), True),
    ],
)
def test_is_open_requires_published_and_unexpired(status, deadline, expected):
    listing = Listing(
        employer_id=2,
        title="Developer",
        company="Example Co",
        description="Build software",
        apply_mode="collect",
        deadline=deadline.isoformat(),
        status=status,
    )

    assert listings.is_open(listing) is expected


def test_is_open_returns_false_for_invalid_deadline():
    listing = Listing(
        employer_id=2,
        title="Developer",
        company="Example Co",
        description="Build software",
        apply_mode="collect",
        deadline="not-a-date",
        status="published",
    )

    assert listings.is_open(listing) is False


def test_list_jobs_returns_only_open_listings(listing_db):
    with Session(listing_db) as session:
        open_listing = add_listing(session, status="published")
        add_listing(
            session,
            status="published",
            deadline=(TODAY - timedelta(days=1)).isoformat(),
        )
        add_listing(session, status="pending")

    jobs = listings.list_jobs_for_graduates()

    assert [job["id"] for job in jobs] == [open_listing]


def test_publish_listing_updates_status_and_notifies_all_subscribers(listing_db):
    with Session(listing_db) as session:
        listing_id = add_listing(session)
        session.add_all(
            [Subscription(graduate_id=3), Subscription(graduate_id=4)]
        )
        session.commit()

    commit_count = []

    def count_commit(connection):
        commit_count.append(1)

    event.listen(listing_db, "commit", count_commit)
    try:
        result = listings.publish_listing(1, listing_id)
    finally:
        event.remove(listing_db, "commit", count_commit)

    assert result["ok"] is True
    assert result["status"] == "published"
    assert result["notified"] is True
    assert result["notification_count"] == 2
    assert len(commit_count) == 1
    with Session(listing_db) as session:
        saved = session.get(Listing, listing_id)
        notifications = session.exec(select(Notification)).all()
        assert saved.status == "published"
        assert {notice.user_id for notice in notifications} == {3, 4}


def test_publish_listing_requires_admin(listing_db):
    result = listings.publish_listing(2, 1)

    assert result == {
        "ok": False,
        "error": "admin only",
        "status_code": 403,
    }


def test_publish_listing_only_accepts_pending_status(listing_db):
    with Session(listing_db) as session:
        listing_id = add_listing(session, status="published")

    result = listings.publish_listing(1, listing_id)

    assert result["ok"] is False
    assert result["status_code"] == 409
    with Session(listing_db) as session:
        assert session.get(Listing, listing_id).status == "published"
        assert session.exec(select(Notification)).all() == []


@pytest.mark.parametrize(
    "operation",
    [listings.reject_listing, listings.unpublish_listing],
)
def test_reject_and_unpublish_require_admin(operation, listing_db):
    result = operation(2, 1)

    assert result == {
        "ok": False,
        "error": "admin only",
        "status_code": 403,
    }


@pytest.mark.parametrize(
    ("operation", "initial_status", "expected_status"),
    [
        (listings.reject_listing, "pending", "rejected"),
        (listings.unpublish_listing, "published", "unpublished"),
    ],
)
def test_admin_listing_decisions(operation, initial_status, expected_status, listing_db):
    with Session(listing_db) as session:
        listing_id = add_listing(session, status=initial_status)

    result = operation(1, listing_id)

    assert result == {
        "ok": True,
        "listing_id": listing_id,
        "status": expected_status,
    }
    with Session(listing_db) as session:
        assert session.get(Listing, listing_id).status == expected_status


@pytest.mark.parametrize(
    ("operation", "status"),
    [
        (listings.reject_listing, "published"),
        (listings.unpublish_listing, "pending"),
    ],
)
def test_admin_listing_decisions_reject_wrong_status(operation, status, listing_db):
    with Session(listing_db) as session:
        listing_id = add_listing(session, status=status)

    result = operation(1, listing_id)

    assert result["ok"] is False
    assert result["status_code"] == 409
    with Session(listing_db) as session:
        assert session.get(Listing, listing_id).status == status


@pytest.mark.parametrize(
    ("operation", "listing_id"),
    [
        (listings.publish_listing, 100),
        (listings.reject_listing, 100),
        (listings.unpublish_listing, 100),
    ],
)
def test_admin_listing_operations_return_not_found(operation, listing_id, listing_db):
    result = operation(1, listing_id)

    assert result["ok"] is False
    assert result["status_code"] == 404


@pytest.mark.parametrize(
    ("route", "operation_name"),
    [
        (board.publish, "publish_listing"),
        (board.reject_listing, "reject_listing"),
        (board.unpublish_listing, "unpublish_listing"),
    ],
)
def test_listing_routes_use_service_status_code(
    monkeypatch, route, operation_name
):
    monkeypatch.setattr(
        board.listings,
        operation_name,
        lambda actor_id, listing_id: {
            "ok": False,
            "error": "invalid state",
            "status_code": 409,
        },
    )

    with pytest.raises(board.HTTPException) as exc_info:
        route(7, board.ActorBody(actor_id=1))

    assert exc_info.value.status_code == 409
