"""Application create / read / status transitions via lifecycle tracker."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.database import engine
from app.models.application import Application
from app.models.listing import Listing
from app.services.board_auth import get_user
from app.services.application_states import InvalidTransitionError, state_for
from app.services.listings import is_open

ACTIONS = ("mark_reviewed", "shortlist", "reject", "hire")


def apply(
    graduate_id: int,
    listing_id: int,
    cover_letter: str,
    resume_text: str | None = None,
) -> dict[str, Any]:
    user = get_user(graduate_id)
    if not user or user["role"] != "graduate":
        return {"ok": False, "error": "graduates only"}
    if user.get("programme") != "DCIT":
        return {"ok": False, "error": "only DCIT graduates may apply"}

    with Session(engine) as session:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return {"ok": False, "error": "listing not found"}
        if not is_open(listing):
            return {"ok": False, "error": "listing is not open"}
        if listing.apply_mode != "collect":
            return {"ok": False, "error": "listing uses external apply"}
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
            view = dict(app)
            view["status"] = state_for(app["status"]).name
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
        if viewer["role"] not in {"employer", "admin"}:
            return {"ok": False, "error": "forbidden"}
        if viewer["role"] == "employer" and listing.employer_id != viewer["id"]:
            return {"ok": False, "error": "you do not own this listing"}
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
    actor = get_user(actor_id)
    if not actor:
        return {"ok": False, "error": "unknown user"}
    if actor["role"] != "employer":
        return {"ok": False, "error": "forbidden"}
    if action not in ACTIONS:
        return {"ok": False, "error": f"action must be one of {ACTIONS}"}

    with Session(engine) as session:
        row = session.get(Application, application_id)
        if row is None:
            return {"ok": False, "error": "application not found"}

        listing = session.get(Listing, row.listing_id)
        if listing is None or listing.employer_id != actor["id"]:
            return {"ok": False, "error": "only the listing employer may transition applications"}

        try:
            state = state_for(row.status)
            next_state = getattr(state, action)(row)
        except (ValueError, InvalidTransitionError) as exc:
            return {"ok": False, "error": str(exc)}

        row.status = next_state.name
        row.flag_reviewed = int(next_state.name in {"reviewed", "shortlisted", "rejected", "hired"})
        row.flag_shortlisted = int(next_state.name in {"shortlisted", "rejected", "hired"})
        row.flag_rejected = int(next_state.name == "rejected")
        row.flag_hired = int(next_state.name == "hired")
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"ok": True, "application": row.model_dump(), "changed": True}
