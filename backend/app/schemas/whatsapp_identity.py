from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WhatsAppIdentityBase(BaseModel):
    provider: str
    provider_user_id: str
    normalized_identifier: str | None = None
    status: str = "active"


class WhatsAppIdentityCreate(WhatsAppIdentityBase):
    student_id: UUID


class WhatsAppIdentityRead(WhatsAppIdentityBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    created_at: datetime
    updated_at: datetime
