"""Listing submit / publish / browse helpers."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlmodel import Session, select

from app.database import engine
from app.models.listing import Listing
from app.models.notification import Notification
from app.models.subscription import Subscription
from app.models.user import User
from app.services.board_auth import get_user

ELIGIBLE_PROGRAMMES = {"DCIT"}
APPLY_MODES = {"collect", "external"}


def is_eligible_graduate(user: dict[str, Any] | None) -> bool:
    """Only graduates of an eligible programme may subscribe or apply."""
    return bool(
        user
        and user.get("role") == "graduate"
        and user.get("programme") in ELIGIBLE_PROGRAMMES
    )


def parse_deadline(deadline: str) -> date | None:
    try:
        return date.fromisoformat(deadline)
    except (TypeError, ValueError):
        return None


def is_open_to_graduates(listing: Listing, today: date | None = None) -> bool:
    """Published and not past its deadline (the deadline day itself is open)."""
    if listing.status != "published":
        return False
    deadline = parse_deadline(listing.deadline)
    if deadline is None:
        return False
    return deadline >= (today or date.today())


def subscribe(graduate_id: int) -> dict[str, Any]:
    user = get_user(graduate_id)
    if not user or user["role"] != "graduate":
        return {"ok": False, "error": "graduates only", "code": 403}
    if not is_eligible_graduate(user):
        return {
            "ok": False,
            "error": "only eligible programme graduates may subscribe",
            "code": 403,
        }
    with Session(engine) as session:
        existing = session.exec(
            select(Subscription).where(Subscription.graduate_id == graduate_id)
        ).one_or_none()
        if existing is None:
            session.add(Subscription(graduate_id=graduate_id))
            session.commit()
    return {"ok": True}


def list_jobs_for_graduates(today: date | None = None) -> list[dict[str, Any]]:
    with Session(engine) as session:
        rows = session.exec(
            select(Listing).where(Listing.status == "published").order_by(Listing.id)
        ).all()
        return [r.model_dump() for r in rows if is_open_to_graduates(r, today)]


def list_pending_for_admin() -> list[dict[str, Any]]:
    with Session(engine) as session:
        rows = session.exec(
            select(Listing).where(Listing.status == "pending").order_by(Listing.id)
        ).all()
        return [r.model_dump() for r in rows]


def submit_listing(
    employer_id: int,
    title: str,
    company: str,
    description: str,
    apply_mode: str,
    deadline: str,
    external_url: str | None = None,
) -> dict[str, Any]:
    user = get_user(employer_id)
    if not user or user["role"] != "employer":
        return {"ok": False, "error": "employers only", "code": 403}
    if apply_mode not in APPLY_MODES:
        return {"ok": False, "error": "apply_mode must be collect|external"}
    if apply_mode == "external" and not external_url:
        return {"ok": False, "error": "external_url required"}
    if parse_deadline(deadline) is None:
        return {"ok": False, "error": "deadline must be an ISO date YYYY-MM-DD"}

    # Employer submissions wait for an administrator to publish them.
    status = "pending"
    with Session(engine) as session:
        listing = Listing(
            employer_id=employer_id,
            title=title,
            company=company,
            description=description,
            apply_mode=apply_mode,
            external_url=external_url if apply_mode == "external" else None,
            deadline=deadline,
            status=status,
        )
        session.add(listing)
        session.commit()
        session.refresh(listing)
        return {"ok": True, "listing_id": listing.id, "status": status}


def _notify_subscribers(session: Session, listing: Listing) -> int:
    """Create a notification for each eligible subscriber; return the count."""
    subscribers = session.exec(
        select(User).join(Subscription, Subscription.graduate_id == User.id)
    ).all()
    count = 0
    for user in subscribers:
        if not is_eligible_graduate(user.model_dump()):
            continue
        session.add(
            Notification(
                user_id=user.id,
                message=f"New job published: {listing.title} at {listing.company}",
            )
        )
        count += 1
    return count


def publish_listing(admin_id: int, listing_id: int) -> dict[str, Any]:
    admin = get_user(admin_id)
    if not admin or admin["role"] != "admin":
        return {"ok": False, "error": "admin only", "code": 403}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found", "code": 404}
        if listing.status != "pending":
            return {
                "ok": False,
                "error": f"only pending listings can be published (is {listing.status})",
                "code": 409,
            }
        listing.status = "published"
        session.add(listing)
        # Publishing notifies subscribers automatically (no manual step).
        count = _notify_subscribers(session, listing)
        session.commit()
    return {"ok": True, "status": "published", "notified": True, "count": count}


def notify_subscribers(admin_id: int, listing_id: int) -> dict[str, Any]:
    """Manual re-send, e.g. after a subscriber joins. Publish already notifies."""
    admin = get_user(admin_id)
    if not admin or admin["role"] != "admin":
        return {"ok": False, "error": "admin only", "code": 403}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found", "code": 404}
        if listing.status != "published":
            return {
                "ok": False,
                "error": "cannot notify about an unpublished listing",
                "code": 409,
            }
        count = _notify_subscribers(session, listing)
        session.commit()
        return {"ok": True, "count": count}
