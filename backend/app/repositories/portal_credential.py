"""
Portal credential repository for database operations.
"""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portal_credential import PortalCredential


class PortalCredentialRepository:
    """Repository for portal credential operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, credential: PortalCredential) -> PortalCredential:
        self.session.add(credential)
        await self.session.flush()
        await self.session.refresh(credential)
        return credential

    async def get_by_student_and_portal(
        self, student_id: UUID, portal: str
    ) -> PortalCredential | None:
        result = await self.session.execute(
            select(PortalCredential).where(
                PortalCredential.student_id == student_id,
                PortalCredential.portal == portal,
            )
        )
        return result.scalar_one_or_none()

    async def delete(self, student_id: UUID, portal: str) -> None:
        await self.session.execute(
            delete(PortalCredential).where(
                PortalCredential.student_id == student_id,
                PortalCredential.portal == portal,
            )
        )
