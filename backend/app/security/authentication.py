from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.security.context import (
    AuthenticatedIdentity,
    IdentityResolutionResult,
)


@dataclass(frozen=True, slots=True)
class IncomingIdentity:
    """Raw identity from an external provider before verification."""

    provider: str
    external_identity_id: str
    provider_metadata: dict[str, str] | None = None


class AuthenticationResolver(ABC):
    """Interface for resolving external identities to authenticated students."""

    @abstractmethod
    async def resolve(self, incoming: IncomingIdentity) -> IdentityResolutionResult:
        """Resolve an incoming identity to an auth result."""
        ...

    @abstractmethod
    async def is_identity_active(
        self, provider: str, external_identity_id: str
    ) -> bool:
        """Check if a known identity is currently active."""
        ...


class StudentResolver(ABC):
    """Interface for resolving student from WhatsApp identity."""

    @abstractmethod
    async def get_student_for_identity(
        self, provider: str, external_identity_id: str
    ) -> AuthenticatedIdentity | None:
        """
        Get authenticated student for a provider identity.

        Returns None if identity is unknown, disabled, or revoked.
        """
        ...

    @abstractmethod
    async def get_identity_status(
        self, provider: str, external_identity_id: str
    ) -> str | None:
        """Get the status of a WhatsApp identity (active/disabled/revoked/unknown)."""
        ...
