from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEvent, AuditEventType
from app.repositories.audit_event import AuditEventRepository


class AuditService:
    """Service for recording security audit events."""

    def __init__(self, session: AsyncSession):
        self._repo = AuditEventRepository(session)

    async def log_authentication_success(
        self,
        *,
        student_id: UUID,
        provider: str,
        external_identity_id: str,
        event_metadata: dict[str, str] | None = None,
    ) -> AuditEvent:
        return await self._repo.create(
            event_type=AuditEventType.AUTHENTICATION_SUCCESS,
            student_id=student_id,
            provider=provider,
            external_identity_id=external_identity_id,
            success=True,
            metadata=event_metadata,
        )

    async def log_authentication_failure(
        self,
        *,
        provider: str,
        external_identity_id: str,
        reason: str,
        event_metadata: dict[str, str] | None = None,
    ) -> AuditEvent:
        return await self._repo.create(
            event_type=AuditEventType.AUTHENTICATION_FAILURE,
            student_id=None,
            provider=provider,
            external_identity_id=external_identity_id,
            success=False,
            error_message=reason,
            metadata=event_metadata,
        )

    async def log_authorization_failure(
        self,
        *,
        student_id: UUID,
        resource_type: str,
        resource_id: UUID,
        action: str,
        event_metadata: dict[str, str] | None = None,
    ) -> AuditEvent:
        meta = event_metadata or {}
        meta["action"] = action
        return await self._repo.create(
            event_type=AuditEventType.AUTHORIZATION_FAILURE,
            student_id=student_id,
            resource_type=resource_type,
            resource_id=resource_id,
            success=False,
            error_message=f"Unauthorized {action} on {resource_type}",
            metadata=meta,
        )

    async def log_unauthorized_access(
        self,
        *,
        student_id: UUID | None,
        provider: str | None,
        external_identity_id: str | None,
        resource_type: str,
        resource_id: UUID,
        event_metadata: dict[str, str] | None = None,
    ) -> AuditEvent:
        return await self._repo.create(
            event_type=AuditEventType.UNAUTHORIZED_ACCESS,
            student_id=student_id,
            provider=provider,
            external_identity_id=external_identity_id,
            resource_type=resource_type,
            resource_id=resource_id,
            success=False,
            error_message=f"Unauthorized access to {resource_type}",
            metadata=event_metadata,
        )

    async def log_student_created(
        self,
        *,
        student_id: UUID,
        event_metadata: dict[str, str] | None = None,
    ) -> AuditEvent:
        return await self._repo.create(
            event_type=AuditEventType.STUDENT_CREATED,
            student_id=student_id,
            success=True,
            metadata=event_metadata,
        )

    async def log_whatsapp_identity_created(
        self,
        *,
        student_id: UUID,
        provider: str,
        external_identity_id: str,
        event_metadata: dict[str, str] | None = None,
    ) -> AuditEvent:
        return await self._repo.create(
            event_type=AuditEventType.WHATSAPP_IDENTITY_CREATED,
            student_id=student_id,
            provider=provider,
            external_identity_id=external_identity_id,
            success=True,
            metadata=event_metadata,
        )

    async def log_telegram_identity_linked(
        self,
        *,
        student_id: UUID,
        telegram_user_id: str,
        event_metadata: dict[str, str] | None = None,
    ) -> AuditEvent:
        return await self._repo.create(
            event_type=AuditEventType.TELEGRAM_IDENTITY_LINKED,
            student_id=student_id,
            provider="telegram_bot",
            external_identity_id=telegram_user_id,
            success=True,
            metadata=event_metadata,
        )

    async def log_telegram_identity_link_failed(
        self,
        *,
        telegram_user_id: str,
        reason: str,
        event_metadata: dict[str, str] | None = None,
    ) -> AuditEvent:
        return await self._repo.create(
            event_type=AuditEventType.TELEGRAM_IDENTITY_LINK_FAILED,
            student_id=None,
            provider="telegram_bot",
            external_identity_id=telegram_user_id,
            success=False,
            error_message=reason,
            metadata=event_metadata,
        )
