"""Application create / read / status transitions (State pattern)."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.database import engine
from app.models.application import Application
from app.models.listing import Listing
from app.services.application_states import (
    ACTIONS,
    INITIAL_STATUS,
    InvalidTransitionError,
    next_status,
    state_for,
)
from app.services.board_auth import get_user
from app.services.listings import is_eligible_graduate, is_open_to_graduates


def apply(
    graduate_id: int,
    listing_id: int,
    cover_letter: str,
    resume_text: str | None = None,
) -> dict[str, Any]:
    user = get_user(graduate_id)
    if not user or user["role"] != "graduate":
        return {"ok": False, "error": "graduates only", "code": 403}
    if not is_eligible_graduate(user):
        return {
            "ok": False,
            "error": "only eligible programme graduates may apply",
            "code": 403,
        }

    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None or not is_open_to_graduates(listing):
            # Pending and expired listings are invisible to graduates.
            return {"ok": False, "error": "listing not found", "code": 404}

        if listing.apply_mode == "external":
            # Off-platform: point the graduate at the employer's own form and
            # do NOT record an application we never collected.
            return {
                "ok": True,
                "apply_mode": "external",
                "collected": False,
                "external_url": listing.external_url,
            }

        cover = (cover_letter or "").strip()
        resume = (resume_text or user.get("resume_text") or "").strip()
        if not cover:
            return {"ok": False, "error": "cover letter is required"}
        if not resume:
            return {"ok": False, "error": "resume is required"}

        # One active application per listing; after a terminal decision
        # (rejected/hired) the graduate may apply again instead of "reopen".
        previous = session.exec(
            select(Application).where(
                Application.graduate_id == graduate_id,
                Application.listing_id == listing_id,
            )
        ).all()
        if any(not state_for(p.status).is_terminal for p in previous):
            return {
                "ok": False,
                "error": "you have already applied to this listing",
                "code": 409,
            }

        application = Application(
            listing_id=listing_id,
            graduate_id=graduate_id,
            cover_letter=cover,
            resume_text=resume,
            status=INITIAL_STATUS,
        )
        session.add(application)
        session.commit()
        session.refresh(application)
        return {
            "ok": True,
            "apply_mode": "collect",
            "collected": True,
            "application_id": application.id,
            "status": application.status,
        }


def my_applications(graduate_id: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        rows = session.exec(
            select(Application)
            .where(Application.graduate_id == graduate_id)
            .order_by(Application.id)
        ).all()
        return [row.model_dump() for row in rows]


def _can_view_applicants(viewer: dict[str, Any], listing: Listing) -> bool:
    if viewer["role"] == "admin":
        return True  # admins export applicant packages for forwarding
    return viewer["role"] == "employer" and listing.employer_id == viewer["id"]


def listing_applicants(viewer_id: int, listing_id: int) -> dict[str, Any]:
    viewer = get_user(viewer_id)
    if not viewer:
        return {"ok": False, "error": "unknown user", "code": 403}
    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found", "code": 404}
        if not _can_view_applicants(viewer, listing):
            return {"ok": False, "error": "forbidden", "code": 403}
        rows = session.exec(
            select(Application)
            .where(Application.listing_id == listing_id)
            .order_by(Application.id)
        ).all()
        return {"ok": True, "applicants": [r.model_dump() for r in rows]}


def export_applicants(admin_id: int, listing_id: int) -> dict[str, Any]:
    admin = get_user(admin_id)
    if not admin or admin["role"] != "admin":
        return {"ok": False, "error": "admin only", "code": 403}
    result = listing_applicants(admin_id, listing_id)
    if not result.get("ok"):
        return result
    return {"ok": True, "format": "json", "package": result["applicants"]}


def transition_application(
    actor_id: int, application_id: int, action: str
) -> dict[str, Any]:
    """Advance an application. Only the employer who owns the listing may."""
    actor = get_user(actor_id)
    if not actor:
        return {"ok": False, "error": "unknown user", "code": 403}
    if actor["role"] != "employer":
        return {
            "ok": False,
            "error": "only the listing employer may change application status",
            "code": 403,
        }
    if action not in ACTIONS:
        return {"ok": False, "error": f"action must be one of {ACTIONS}"}

    with Session(engine) as session:
        row = session.get(Application, application_id)
        if row is None:
            return {"ok": False, "error": "application not found", "code": 404}
        listing = session.get(Listing, row.listing_id)
        if listing is None or listing.employer_id != actor["id"]:
            return {
                "ok": False,
                "error": "only the listing employer may change application status",
                "code": 403,
            }

        try:
            row.status = next_status(row.status, action, row)
        except InvalidTransitionError as exc:
            return {"ok": False, "error": str(exc), "code": 409}

        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "application": row.model_dump(), "changed": True}
