"""
Portal credential repository for database operations.
"""

from datetime import datetime
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

    async def update_status(
        self,
        student_id: UUID,
        portal: str,
        status: str,
        last_auth_failure_at: datetime | None = None,
    ) -> bool:
        """Update status and optionally failure timestamp."""
        cred = await self.get_by_student_and_portal(student_id, portal)
        if not cred:
            return False
        cred.status = status
        if last_auth_failure_at:
            cred.last_auth_failure_at = last_auth_failure_at
        await self.session.flush()
        return True

    async def update_sync_timestamp(
        self, student_id: UUID, portal: str, sync_time: datetime
    ) -> bool:
        """Update last_sync_at timestamp."""
        cred = await self.get_by_student_and_portal(student_id, portal)
        if not cred:
            return False
        cred.last_sync_at = sync_time
        await self.session.flush()
        return True

    async def delete(self, student_id: UUID, portal: str) -> None:
        await self.session.execute(
            delete(PortalCredential).where(
                PortalCredential.student_id == student_id,
                PortalCredential.portal == portal,
            )
        )
