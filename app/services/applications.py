"""Application create / read / status transitions via lifecycle tracker."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.database import engine
from app.models.application import Application
from app.models.listing import Listing
from app.models.notification import Notification
from app.services import listings as listing_service
from app.services.application_states import InvalidTransitionError
from app.services.board_auth import get_user


def apply(
    graduate_id: int,
    listing_id: int,
    cover_letter: str,
    resume_text: str | None = None,
) -> dict[str, Any]:
    user = get_user(graduate_id)
    if not user or user["role"] != "graduate":
        return {"ok": False, "error": "graduates only", "status_code": 403}
    if user.get("programme") != "DCIT":
        return {"ok": False, "error": "DCIT graduates only", "status_code": 403}

    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found", "status_code": 404}

        if hasattr(listing_service, "is_open"):
            is_open = listing_service.is_open(listing)
        else:
            from datetime import date

            try:
                is_open = (
                    listing.status == "published"
                    and date.fromisoformat(listing.deadline) >= date.today()
                )
            except (TypeError, ValueError):
                is_open = False
        if not is_open:
            return {"ok": False, "error": "listing is closed", "status_code": 400}

        if listing.apply_mode == "external":
            return {
                "ok": True,
                "external": True,
                "external_url": listing.external_url,
                "message": f"Apply externally: {listing.external_url}",
            }

        existing = session.exec(
            select(Application).where(
                Application.listing_id == listing_id,
                Application.graduate_id == graduate_id,
            )
        ).all()
        if any(application.status != "rejected" for application in existing):
            return {
                "ok": False,
                "error": "active application already exists",
                "status_code": 409,
            }

        if not (cover_letter or "").strip():
            return {
                "ok": False,
                "error": "cover letter is required",
                "status_code": 400,
            }
        resume = resume_text or user.get("resume_text") or ""
        application = Application(
            listing_id=listing_id,
            graduate_id=graduate_id,
            cover_letter=cover_letter,
            resume_text=resume,
            status="submitted",
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
            view = row.model_dump()
            listing = session.get(Listing, row.listing_id)
            if listing is None:
                is_open = False
            elif hasattr(listing_service, "is_open"):
                is_open = listing_service.is_open(listing)
            else:
                from datetime import date

                try:
                    is_open = (
                        listing.status == "published"
                        and date.fromisoformat(listing.deadline) >= date.today()
                    )
                except (TypeError, ValueError):
                    is_open = False

            view["display_status"] = (
                "closed"
                if not is_open and row.status in {"submitted", "reviewed"}
                else row.status
            )
            results.append(view)
        return results


def listing_applicants(viewer_id: int, listing_id: int) -> dict[str, Any]:
    viewer = get_user(viewer_id)
    if not viewer:
        return {"ok": False, "error": "unknown user", "status_code": 404}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found", "status_code": 404}
        if viewer["role"] == "employer" and listing.employer_id != viewer_id:
            return {"ok": False, "error": "forbidden", "status_code": 403}
        if viewer["role"] not in {"employer", "admin"}:
            return {"ok": False, "error": "forbidden", "status_code": 403}
        rows = session.exec(
            select(Application)
            .where(Application.listing_id == listing_id)
            .order_by(Application.id)
        ).all()
        return {"ok": True, "applicants": [r.model_dump() for r in rows]}


def export_applicants(admin_id: int, listing_id: int) -> dict[str, Any]:
    admin = get_user(admin_id)
    if not admin or admin["role"] != "admin":
        return {"ok": False, "error": "admin only", "status_code": 403}
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
            not listing_service.is_open(listing)
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
