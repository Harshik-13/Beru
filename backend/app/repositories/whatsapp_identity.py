from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.whatsapp_identity import (
    WhatsAppIdentity,
    WhatsAppIdentityStatus,
)


class WhatsAppIdentityRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        *,
        student_id: UUID,
        provider: str,
        provider_user_id: str,
        normalized_identifier: str | None = None,
        status: str = "active",
    ) -> WhatsAppIdentity:
        identity = WhatsAppIdentity(
            student_id=student_id,
            provider=provider,
            provider_user_id=provider_user_id,
            normalized_identifier=normalized_identifier,
            status=status,
        )
        self._session.add(identity)
        await self._session.flush()
        return identity

    async def get_by_provider_identity(
        self, provider: str, provider_user_id: str
    ) -> WhatsAppIdentity | None:
        result = await self._session.execute(
            select(WhatsAppIdentity).where(
                WhatsAppIdentity.provider == provider,
                WhatsAppIdentity.provider_user_id == provider_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_for_student(self, student_id: UUID) -> list[WhatsAppIdentity]:
        result = await self._session.execute(
            select(WhatsAppIdentity).where(WhatsAppIdentity.student_id == student_id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, identity_id: UUID) -> WhatsAppIdentity | None:
        result = await self._session.execute(
            select(WhatsAppIdentity).where(WhatsAppIdentity.id == identity_id)
        )
        return result.scalar_one_or_none()

    async def get_active_for_student(self, student_id: UUID) -> list[WhatsAppIdentity]:
        result = await self._session.execute(
            select(WhatsAppIdentity).where(
                WhatsAppIdentity.student_id == student_id,
                WhatsAppIdentity.status == WhatsAppIdentityStatus.ACTIVE,
            )
        )
        return list(result.scalars().all())
