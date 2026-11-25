"""Application transition history and currently available actions."""

from __future__ import annotations

from typing import Any

from app.models.status_change import StatusChange
from sqlmodel import Session, select

from app.database import engine
from app.models.application import Application
from app.services.application_states import (
    InvalidTransitionError,
    state_for,
)

ACTIONS = ("mark_reviewed", "shortlist", "reject", "hire")


def application_history(application_id: int) -> dict[str, Any]:
    with Session(engine) as session:
        application = session.get(Application, application_id)
        if application is None:
            return {
                "ok": False,
                "error": "application not found",
                "status_code": 404,
            }

        state = state_for(application.status)
        allowed_actions = []
        for action in ACTIONS:
            try:
                getattr(state, action)(application)
            except InvalidTransitionError:
                continue
            allowed_actions.append(action)

        history = session.exec(
            select(StatusChange)
            .where(StatusChange.application_id == application_id)
            .order_by(StatusChange.changed_at, StatusChange.id)
        ).all()
        return {
            "ok": True,
            "allowed_actions": allowed_actions,
            "status_history": [change.model_dump() for change in history],
        }
