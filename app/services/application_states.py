from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class InvalidTransitionError(Exception):
    def __init__(self, from_status: str, action: str) -> None:
        self.from_status = from_status
        self.action = action
        super().__init__(
            f"invalid transition from '{from_status}' using action '{action}'"
        )


class ApplicationState(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def is_terminal(self) -> bool:
        pass

    def illegal(self, action: str) -> ApplicationState:
        raise InvalidTransitionError(self.name, action)

    def mark_reviewed(self, app: Any) -> ApplicationState:
        return self.illegal("mark_reviewed")

    def shortlist(self, app: Any) -> ApplicationState:
        return self.illegal("shortlist")

    def reject(self, app: Any) -> ApplicationState:
        return self.illegal("reject")

    def hire(self, app: Any) -> ApplicationState:
        return self.illegal("hire")


class SubmittedState(ApplicationState):
    @property
    def name(self) -> str:
        return "submitted"

    @property
    def is_terminal(self) -> bool:
        return False

    def mark_reviewed(self, app: Any) -> ApplicationState:
        return STATES["reviewed"]


class ReviewedState(ApplicationState):
    @property
    def name(self) -> str:
        return "reviewed"

    @property
    def is_terminal(self) -> bool:
        return False

    def shortlist(self, app: Any) -> ApplicationState:
        return STATES["shortlisted"]


class ShortlistedState(ApplicationState):
    @property
    def name(self) -> str:
        return "shortlisted"

    @property
    def is_terminal(self) -> bool:
        return False

    def reject(self, app: Any) -> ApplicationState:
        return STATES["rejected"]

    def hire(self, app: Any) -> ApplicationState:
        return STATES["hired"]


class RejectedState(ApplicationState):
    @property
    def name(self) -> str:
        return "rejected"

    @property
    def is_terminal(self) -> bool:
        return True


class HiredState(ApplicationState):
    @property
    def name(self) -> str:
        return "hired"

    @property
    def is_terminal(self) -> bool:
        return True


STATES: dict[str, ApplicationState] = {
    "submitted": SubmittedState(),
    "reviewed": ReviewedState(),
    "shortlisted": ShortlistedState(),
    "rejected": RejectedState(),
    "hired": HiredState(),
}


def state_for(status: str) -> ApplicationState:
    try:
        return STATES[status]
    except KeyError:
        raise ValueError(f"unknown application status: {status!r}") from None
