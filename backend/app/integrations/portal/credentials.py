"""
Portal credential abstraction and secure storage.

Provides a replaceable abstraction for storing and retrieving
encrypted portal credentials scoped to authenticated students.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PortalCredential:
    """Encrypted portal credential data."""

    portal: str
    roll_number: str
    encrypted_password: str


class PortalCredentialStore(ABC):
    """
    Abstract interface for portal credential storage.

    Implementations must provide secure, ownership-scoped
    credential storage with encryption at rest.
    """

    @abstractmethod
    async def save_credential(
        self,
        student_id: UUID,
        portal: str,
        roll_number: str,
        password: str,
    ) -> None:
        """
        Store encrypted portal credentials for a student.

        Args:
            student_id: The authenticated student ID
            portal: Portal identifier (e.g., "doctus")
            roll_number: Student's roll number for the portal
            password: Portal password (will be encrypted)
        """
        ...

    @abstractmethod
    async def get_credential(
        self, student_id: UUID, portal: str
    ) -> tuple[str, str] | None:
        """
        Retrieve decrypted portal credentials for a student.

        Args:
            student_id: The authenticated student ID
            portal: Portal identifier

        Returns:
            Tuple of (roll_number, password) or None if not found
        """
        ...

    @abstractmethod
    async def delete_credential(self, student_id: UUID, portal: str) -> None:
        """
        Delete portal credentials for a student.

        Args:
            student_id: The authenticated student ID
            portal: Portal identifier
        """
        ...


@dataclass(frozen=True, slots=True)
class FernetCredentialConfig:
    """Configuration for Fernet-based credential encryption."""

    encryption_key: str  # Base64-encoded 32-byte key

    @classmethod
    def from_settings(cls, encryption_key: str) -> "FernetCredentialConfig":
        """Create config from settings."""
        return cls(encryption_key=encryption_key)
