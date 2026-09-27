from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.security.context import AuthenticatedIdentity, UnauthenticatedIdentity
from app.telegram.models import TelegramContactIdentity

if TYPE_CHECKING:
    from app.security.authentication import IncomingIdentity


@dataclass(frozen=True, slots=True)
class TelegramIncomingIdentity:
    """
    Telegram-specific incoming identity for authentication resolution.

    This bridges the provider-neutral TelegramContactIdentity to the
    security system's IncomingIdentity.
    """

    provider: str  # e.g., "telegram_bot"
    provider_user_id: str  # e.g., "123456789"
    normalized_identifier: str | None = None  # e.g., "@username"
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
        cls, contact: TelegramContactIdentity
    ) -> "TelegramIncomingIdentity":
        """Create from normalized Telegram contact identity."""
        return cls(
            provider=contact.provider,
            provider_user_id=contact.provider_user_id,
            normalized_identifier=contact.normalized_identifier,
            provider_metadata={
                "display_name": contact.display_name,
                "is_bot": contact.is_bot,
                "is_premium": contact.is_premium,
                "language_code": contact.language_code,
            }
            if any(
                [
                    contact.display_name,
                    contact.is_bot,
                    contact.is_premium,
                    contact.language_code,
                ]
            )
            else None,
        )


@dataclass(frozen=True, slots=True)
class TelegramAuthenticatedIdentity:
    """
    Telegram-specific authenticated identity with Student context.

    Extends the security system's AuthenticatedIdentity with Telegram-specific fields.
    """

    authenticated_identity: AuthenticatedIdentity
    telegram_identity: TelegramContactIdentity

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


class TelegramIdentityResolver:
    """
    Resolves Telegram identities to authenticated Students.

    This is the Telegram-specific implementation of StudentResolver.
    It uses the TelegramIdentityRepository to look up the TelegramIdentity
    and returns an AuthenticatedIdentity if the identity is ACTIVE.
    """

    def __init__(self, student_resolver):
        """
        Args:
            student_resolver: DatabaseStudentResolver instance
        """
        self._student_resolver = student_resolver

    async def resolve(
        self, incoming: TelegramIncomingIdentity
    ) -> AuthenticatedIdentity | UnauthenticatedIdentity:
        """
        Resolve a Telegram incoming identity to an authenticated or
        unauthenticated result.

        Flow:
        1. Look up TelegramIdentity by (provider, provider_user_id)
        2. If not found → UnauthenticatedIdentity
        3. If status != ACTIVE → UnauthenticatedIdentity
        3. If found and ACTIVE → AuthenticatedIdentity with Student
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


def create_telegram_incoming_identity(
    provider: str,
    provider_user_id: str,
    normalized_identifier: str | None = None,
    provider_metadata: dict | None = None,
) -> TelegramIncomingIdentity:
    """Factory function to create TelegramIncomingIdentity."""
    return TelegramIncomingIdentity(
        provider=provider,
        provider_user_id=provider_user_id,
        normalized_identifier=normalized_identifier,
        provider_metadata=provider_metadata,
    )
