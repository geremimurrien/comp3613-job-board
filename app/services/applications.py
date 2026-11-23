"""Application create / read / status transitions via lifecycle tracker."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.database import engine
from app.models.application import Application
from app.models.listing import Listing
from app.models.notification import Notification
from app.services import listings
from app.services.application_states import InvalidTransitionError
from app.services.board_auth import get_user
from app.services.lifecycle import derived_status_from_flags


def apply(
    graduate_id: int,
    listing_id: int,
    cover_letter: str,
    resume_text: str | None = None,
) -> dict[str, Any]:
    user = get_user(graduate_id)
    if not user or user["role"] != "graduate":
        return {"ok": False, "error": "graduates only"}
    # DEFECT: no programme eligibility check

    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found"}

        # DEFECT: allows apply on pending / expired; external still creates a row
        resume = resume_text or user.get("resume_text") or ""
        application = Application(
            listing_id=listing_id,
            graduate_id=graduate_id,
            cover_letter=cover_letter,
            resume_text=resume,
            status="submitted",
            flag_reviewed=0,
            flag_shortlisted=0,
            flag_rejected=0,
            flag_hired=0,
        )
        session.add(application)
        session.commit()
        session.refresh(application)
        return {
            "ok": True,
            "application_id": application.id,
            "status": "submitted",
        }


def my_applications(graduate_id: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        rows = session.exec(
            select(Application)
            .where(Application.graduate_id == graduate_id)
            .order_by(Application.id)
        ).all()
        results = []
        for row in rows:
            app = row.model_dump()
            # DEFECT: graduate view sometimes uses flag-derived status, not column
            view = dict(app)
            view["status"] = derived_status_from_flags(app)
            results.append(view)
        return results


def listing_applicants(viewer_id: int, listing_id: int) -> dict[str, Any]:
    viewer = get_user(viewer_id)
    if not viewer:
        return {"ok": False, "error": "unknown user"}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found"}
        # DEFECT (IDOR): ownership not checked for employers
        if viewer["role"] not in {"employer", "admin"}:
            return {"ok": False, "error": "forbidden"}
        rows = session.exec(
            select(Application)
            .where(Application.listing_id == listing_id)
            .order_by(Application.id)
        ).all()
        return {"ok": True, "applicants": [r.model_dump() for r in rows]}


def export_applicants(admin_id: int, listing_id: int) -> dict[str, Any]:
    admin = get_user(admin_id)
    if not admin or admin["role"] != "admin":
        return {"ok": False, "error": "admin only"}
    result = listing_applicants(admin_id, listing_id)
    if not result.get("ok"):
        return result
    return {"ok": True, "format": "json", "package": result["applicants"]}


def transition_application(
    actor_id: int, application_id: int, action: str
) -> dict[str, Any]:
    """Perform and persist one legal application state transition."""
    with Session(engine) as session:
        application = session.get(Application, application_id)
        if application is None:
            return {
                "ok": False,
                "error": "application not found",
                "status_code": 404,
            }
        listing = session.get(Listing, application.listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found", "status_code": 404}

        actor = get_user(actor_id)
        if (
            not actor
            or actor["role"] != "employer"
            or actor["id"] != listing.employer_id
        ):
            return {
                "ok": False,
                "error": "only the listing employer may transition applications",
                "status_code": 403,
            }

        if (
            not listings.is_open(listing)
            and application.status in {"submitted", "reviewed"}
        ):
            return {
                "ok": False,
                "error": f"cannot change a {application.status} application when the listing is closed",
                "status_code": 409,
            }

        if action not in {"mark_reviewed", "shortlist", "reject", "hire"}:
            return {
                "ok": False,
                "error": f"unknown action: {action}",
                "status_code": 400,
            }

        from_status = application.status
        try:
            status_change = application.perform(action, actor_id)
        except InvalidTransitionError as exc:
            return {
                "ok": False,
                "error": (
                    f"invalid transition from {exc.from_status} "
                    f"using action {exc.action}"
                ),
                "status_code": 409,
            }

        session.add(status_change)
        session.add(
            Notification(
                user_id=application.graduate_id,
                message=(
                    f"Your application for {listing.title} changed "
                    f"from {from_status} to {application.status}."
                ),
            )
        )
        session.commit()
        return {
            "ok": True,
            "application_id": application.id,
            "from_status": from_status,
            "to_status": application.status,
            "action": action,
        }
