"""
Fernet-based portal credential store implementation.

Provides secure encrypted credential storage using Fernet symmetric encryption.
Credentials are scoped to student_id and portal.
"""

import base64
import os
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.portal.credentials import (
    FernetCredentialConfig,
    PortalCredentialStore,
)
from app.models.portal_credential import PortalCredential


class FernetCredentialStore(PortalCredentialStore):
    """
    Fernet-encrypted credential store using database persistence.

    Encrypts passwords at rest using Fernet symmetric encryption.
    Each student's credentials are isolated by student_id and portal.
    """

    def __init__(self, session: AsyncSession, config: FernetCredentialConfig):
        self.session = session
        self._fernet = Fernet(config.encryption_key.encode())

    @staticmethod
    def generate_key() -> str:
        """Generate a new Fernet encryption key (base64-encoded)."""
        return base64.urlsafe_b64encode(os.urandom(32)).decode()

    async def save_credential(
        self,
        student_id: UUID,
        portal: str,
        roll_number: str,
        password: str,
    ) -> None:
        """Store encrypted portal credentials for a student."""
        encrypted_password = self._fernet.encrypt(password.encode()).decode()

        # Use upsert pattern - delete existing then insert
        await self.session.execute(
            delete(PortalCredential).where(
                (PortalCredential.student_id == student_id)
                & (PortalCredential.portal == portal)
            )
        )

        credential = PortalCredential(
            student_id=student_id,
            portal=portal,
            roll_number=roll_number,
            encrypted_password=encrypted_password,
        )
        self.session.add(credential)
        await self.session.flush()

    async def get_credential(
        self, student_id: UUID, portal: str
    ) -> tuple[str, str] | None:
        """Retrieve decrypted portal credentials for a student."""
        result = await self.session.execute(
            select(PortalCredential).where(
                (PortalCredential.student_id == student_id)
                & (PortalCredential.portal == portal)
            )
        )
        credential = result.scalar_one_or_none()

        if credential is None:
            return None

        try:
            password = self._fernet.decrypt(
                credential.encrypted_password.encode()
            ).decode()
        except InvalidToken:
            # Encryption key changed or data corrupted
            return None

        return credential.roll_number, password

    async def delete_credential(self, student_id: UUID, portal: str) -> None:
        """Delete portal credentials for a student."""
        await self.session.execute(
            delete(PortalCredential).where(
                (PortalCredential.student_id == student_id)
                & (PortalCredential.portal == portal)
            )
        )
        await self.session.flush()


# Import base64 here to avoid circular import issues
