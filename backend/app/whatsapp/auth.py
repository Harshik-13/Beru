from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.security.context import AuthenticatedIdentity, UnauthenticatedIdentity
from app.whatsapp.models import WhatsAppContactIdentity

if TYPE_CHECKING:
    from app.security.authentication import IncomingIdentity


@dataclass(frozen=True, slots=True)
class WhatsAppIncomingIdentity:
    """
    WhatsApp-specific incoming identity for authentication resolution.

    This bridges the provider-neutral WhatsAppContactIdentity to the
    security system's IncomingIdentity.
    """

    provider: str  # e.g., "baileys"
    provider_user_id: str  # e.g., "919876543210@s.whatsapp.net"
    normalized_identifier: str | None = None  # e.g., "+919876543210"
    provider_metadata: dict | None = None  # Preserved for audit

    def to_incoming_identity(self) -> "IncomingIdentity":
        """Convert to security system's IncomingIdentity."""
        from app.security.authentication import IncomingIdentity

        return IncomingIdentity(
            provider=self.provider,
            external_identity_id=self.provider_user_id,
            provider_metadata=self.provider_metadata,
        )

    @classmethod
    def from_contact(
        cls, contact: WhatsAppContactIdentity
    ) -> "WhatsAppIncomingIdentity":
        """Create from normalized WhatsApp contact identity."""
        return cls(
            provider=contact.provider,
            provider_user_id=contact.provider_user_id,
            normalized_identifier=contact.normalized_identifier,
            provider_metadata={
                "display_name": contact.display_name,
                "is_business": contact.is_business,
            }
            if contact.display_name or contact.is_business
            else None,
        )


@dataclass(frozen=True, slots=True)
class WhatsAppAuthenticatedIdentity:
    """
    WhatsApp-specific authenticated identity with Student context.

    Extends the security system's AuthenticatedIdentity with WhatsApp-specific fields.
    """

    authenticated_identity: AuthenticatedIdentity
    whatsapp_identity: WhatsAppContactIdentity

    @property
    def student_id(self) -> UUID:
        return self.authenticated_identity.student_id

    @property
    def provider(self) -> str:
        return self.authenticated_identity.provider

    @property
    def external_identity_id(self) -> str:
        return self.authenticated_identity.external_identity_id

    @property
    def authentication_method(self) -> str:
        return self.authenticated_identity.authentication_method.value


class WhatsAppIdentityResolver:
    """
    Resolves WhatsApp identities to authenticated Students.

    This is the WhatsApp-specific implementation of StudentResolver.
    It uses the WhatsAppIdentityRepository to look up the WhatsAppIdentity
    and returns an AuthenticatedIdentity if the identity is ACTIVE.
    """

    def __init__(self, student_resolver):
        """
        Args:
            student_resolver: DatabaseStudentResolver instance
        """
        self._student_resolver = student_resolver

    async def resolve(
        self, incoming: WhatsAppIncomingIdentity
    ) -> AuthenticatedIdentity | UnauthenticatedIdentity:
        """
        Resolve a WhatsApp incoming identity to an authenticated or
        unauthenticated result.

        Flow:
        1. Look up WhatsAppIdentity by (provider, provider_user_id)
        2. If not found → UnauthenticatedIdentity
        3. If status != ACTIVE → UnauthenticatedIdentity
        4. If found and ACTIVE → AuthenticatedIdentity with Student
        """
        identity = await self._student_resolver.get_student_for_identity(
            incoming.provider, incoming.provider_user_id
        )

        if identity is None:
            return UnauthenticatedIdentity(
                provider=incoming.provider,
                external_identity_id=incoming.provider_user_id,
                reason="Identity not found or not active",
            )

        return identity


def create_whatsapp_incoming_identity(
    provider: str,
    provider_user_id: str,
    normalized_identifier: str | None = None,
    provider_metadata: dict | None = None,
) -> WhatsAppIncomingIdentity:
    """Factory function to create WhatsAppIncomingIdentity."""
    return WhatsAppIncomingIdentity(
        provider=provider,
        provider_user_id=provider_user_id,
        normalized_identifier=normalized_identifier,
        provider_metadata=provider_metadata,
    )
