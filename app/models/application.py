from typing import Optional

from sqlmodel import Field, SQLModel


class Application(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    listing_id: int = Field(index=True)
    graduate_id: int = Field(index=True)
    cover_letter: str
    resume_text: str
    # Single source of truth for the lifecycle. Allowed values and transitions
    # live in app/services/application_states.py (State pattern).
    status: str = "submitted"
