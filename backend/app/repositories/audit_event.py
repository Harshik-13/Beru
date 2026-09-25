from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent, AuditEventType


class AuditEventRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        event_type: AuditEventType,
        student_id: UUID | None = None,
        provider: str | None = None,
        external_identity_id: str | None = None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        success: bool = True,
        error_message: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AuditEvent:
        import json

        event = AuditEvent(
            event_type=event_type,
            student_id=student_id,
            provider=provider,
            external_identity_id=external_identity_id,
            resource_type=resource_type,
            resource_id=resource_id,
            success=success,
            error_message=error_message,
            event_metadata=json.dumps(metadata) if metadata else None,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def get_for_student(
        self, student_id: UUID, limit: int = 100
    ) -> list[AuditEvent]:
        result = await self._session.execute(
            select(AuditEvent)
            .where(AuditEvent.student_id == student_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_type(
        self, event_type: AuditEventType, limit: int = 100
    ) -> list[AuditEvent]:
        result = await self._session.execute(
            select(AuditEvent)
            .where(AuditEvent.event_type == event_type)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
