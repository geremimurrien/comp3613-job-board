from typing import Optional

from sqlmodel import Field, SQLModel

from app.models.status_change import StatusChange
from app.services.application_states import InvalidTransitionError, state_for


class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    listing_id: int = Field(index=True)
    graduate_id: int = Field(index=True)
    cover_letter: str
    resume_text: str
    status: str

    def state(self):
        return state_for(self.status)

    def perform(self, action: str, actor_id: int) -> StatusChange:
        from_status = self.status
        state = state_for(from_status)
        action_method = getattr(state, action, None)
        if action_method is None:
            raise InvalidTransitionError(from_status, action)

        next_status = action_method(self)
        self.status = next_status
        return StatusChange(
            application_id=self.id,
            actor_id=actor_id,
            from_status=from_status,
            to_status=next_status,
        )
