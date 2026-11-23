from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class StatusChange(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    application_id: int = Field(index=True)
    actor_id: int = Field(index=True)
    from_status: str
    to_status: str
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
