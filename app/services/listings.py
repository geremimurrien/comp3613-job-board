"""Listing submit / publish / browse helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.database import engine
from app.models.listing import Listing
from app.models.notification import Notification
from app.models.subscription import Subscription
from app.services.board_auth import get_user

ELIGIBLE_PROGRAMMES = {"DCIT"}


def subscribe(graduate_id: int) -> dict[str, Any]:
    user = get_user(graduate_id)
    if not user or user["role"] != "graduate":
        return {"ok": False, "error": "graduates only", "status_code": 403}
    if user.get("programme") != "DCIT":
        return {"ok": False, "error": "DCIT graduates only", "status_code": 403}
    with Session(engine) as session:
        existing = session.exec(
            select(Subscription).where(Subscription.graduate_id == graduate_id)
        ).one_or_none()
        if existing is None:
            session.add(Subscription(graduate_id=graduate_id))
            session.commit()
    return {"ok": True}


def list_jobs_for_graduates() -> list[dict[str, Any]]:
    with Session(engine) as session:
        rows = session.exec(
            select(Listing)
            .where(Listing.status == "published")
            .order_by(Listing.id)
        ).all()
        return [row.model_dump() for row in rows if is_open(row)]


def is_open(listing: Listing) -> bool:
    if listing.status != "published":
        return False
    try:
        deadline = date.fromisoformat(listing.deadline)
    except (TypeError, ValueError):
        return False
    return deadline >= datetime.now(timezone.utc).date()


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
        return {
            "ok": False,
            "error": "employers only",
            "status_code": 403,
        }
    if apply_mode not in {"collect", "external"}:
        return {
            "ok": False,
            "error": "apply_mode must be collect|external",
            "status_code": 400,
        }
    if apply_mode == "external" and not external_url:
        return {
            "ok": False,
            "error": "external_url required",
            "status_code": 400,
        }

    try:
        date.fromisoformat(deadline)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": "deadline must be an ISO date YYYY-MM-DD",
            "status_code": 400,
        }

    status = "pending"
    with Session(engine) as session:
        listing = Listing(
            employer_id=employer_id,
            title=title,
            company=company,
            description=description,
            apply_mode=apply_mode,
            external_url=external_url,
            deadline=deadline,
            status=status,
        )
        session.add(listing)
        session.commit()
        session.refresh(listing)
        return {"ok": True, "listing_id": listing.id, "status": status}


def publish_listing(admin_id: int, listing_id: int) -> dict[str, Any]:
    admin = get_user(admin_id)
    if not admin or admin["role"] != "admin":
        return {"ok": False, "error": "admin only", "status_code": 403}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {
                "ok": False,
                "error": "listing not found",
                "status_code": 404,
            }
        if listing.status != "pending":
            return {
                "ok": False,
                "error": "only pending listings can be published",
                "status_code": 409,
            }

        listing.status = "published"
        subscribers = session.exec(select(Subscription)).all()
        notifications = [
            Notification(
                user_id=subscriber.graduate_id,
                message=(
                    f"New job published: {listing.title} at {listing.company}"
                ),
            )
            for subscriber in subscribers
        ]
        session.add(listing)
        session.add_all(notifications)
        session.commit()
    return {
        "ok": True,
        "listing_id": listing_id,
        "status": "published",
        "notified": True,
        "notification_count": len(notifications),
    }


def reject_listing(admin_id: int, listing_id: int) -> dict[str, Any]:
    admin = get_user(admin_id)
    if not admin or admin["role"] != "admin":
        return {"ok": False, "error": "admin only", "status_code": 403}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {
                "ok": False,
                "error": "listing not found",
                "status_code": 404,
            }
        if listing.status != "pending":
            return {
                "ok": False,
                "error": "only pending listings can be rejected",
                "status_code": 409,
            }
        listing.status = "rejected"
        session.add(listing)
        session.commit()
    return {"ok": True, "listing_id": listing_id, "status": "rejected"}


def unpublish_listing(admin_id: int, listing_id: int) -> dict[str, Any]:
    admin = get_user(admin_id)
    if not admin or admin["role"] != "admin":
        return {"ok": False, "error": "admin only", "status_code": 403}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {
                "ok": False,
                "error": "listing not found",
                "status_code": 404,
            }
        if listing.status != "published":
            return {
                "ok": False,
                "error": "only published listings can be unpublished",
                "status_code": 409,
            }
        listing.status = "unpublished"
        session.add(listing)
        session.commit()
    return {"ok": True, "listing_id": listing_id, "status": "unpublished"}


def notify_subscribers(admin_id: int, listing_id: int) -> dict[str, Any]:
    admin = get_user(admin_id)
    if not admin or admin["role"] != "admin":
        return {"ok": False, "error": "admin only", "status_code": 403}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {
                "ok": False,
                "error": "listing not found",
                "status_code": 404,
            }
        if listing.status != "published":
            return {
                "ok": False,
                "error": "cannot notify about an unpublished listing",
                "status_code": 409,
            }
        subs = session.exec(select(Subscription)).all()
        for sub in subs:
            session.add(
                Notification(
                    user_id=sub.graduate_id,
                    message=f"New job published: {listing.title} at {listing.company}",
                )
            )
        session.commit()
        return {"ok": True, "count": len(subs)}
