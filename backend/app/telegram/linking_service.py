"""
Telegram Identity Linking Service — Personal Alpha.

Handles the secure linking of Telegram identities to existing Student accounts.
"""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.models.telegram_identity import TelegramIdentityStatus
from app.models.telegram_linking_challenge import (
    TelegramLinkingChallenge,
    TelegramLinkingChallengeStatus,
)
from app.repositories.student import StudentRepository
from app.repositories.telegram_identity import TelegramIdentityRepository
from app.repositories.telegram_linking_challenge import (
    TelegramLinkingChallengeRepository,
)
from app.security.audit import AuditService
from app.security.context import AuthenticatedIdentity, UnauthenticatedIdentity
from app.telegram.auth import (
    TelegramIncomingIdentity,
)


class TelegramLinkingError(Exception):
    """Base exception for Telegram linking errors."""

    def __init__(self, message: str, reason_code: str):
        super().__init__(message)
        self.reason_code = reason_code


class ChallengeExpiredError(TelegramLinkingError):
    def __init__(self):
        super().__init__("Linking challenge has expired", "challenge_expired")


class ChallengeAlreadyUsedError(TelegramLinkingError):
    def __init__(self):
        super().__init__("Linking challenge has already been used", "challenge_already_used")


class ChallengeInvalidError(TelegramLinkingError):
    def __init__(self):
        super().__init__("Invalid linking challenge", "challenge_invalid")


class TelegramIdentityAlreadyLinkedError(TelegramLinkingError):
    def __init__(self):
        super().__init__("This Telegram identity is already linked to a student", "telegram_identity_already_linked")


class TelegramIdentityLinkedToAnotherStudentError(TelegramLinkingError):
    def __init__(self):
        super().__init__(
            "This Telegram identity is already linked to another student",
            "telegram_identity_linked_to_another_student",
        )


class StudentAlreadyHasTelegramIdentityError(TelegramLinkingError):
    def __init__(self):
        super().__init__(
            "This student already has a Telegram identity linked",
            "student_already_has_telegram_identity",
        )


class StudentNotFoundError(TelegramLinkingError):
    def __init__(self):
        super().__init__("Student not found", "student_not_found")


class TelegramLinkingService:
    """
    Service for managing Telegram identity linking to Student accounts.

    This service handles the secure linking flow:
    1. Generate a short-lived, single-use challenge token
    2. Student provides token via existing Beru authentication flow
    3. On successful verification, create TelegramIdentity linking Telegram user to Student
    """

    CHALLENGE_TTL_MINUTES = 10
    CHALLENGE_TOKEN_BYTES = 32  # 256 bits

    def __init__(
        self,
        challenge_repo: "TelegramLinkingChallengeRepository",
        telegram_identity_repo: TelegramIdentityRepository,
        student_repo: StudentRepository,
        audit_service: AuditService,
    ):
        self._challenge_repo = challenge_repo
        self._telegram_identity_repo = telegram_identity_repo
        self._student_repo = student_repo
        self._audit_service = audit_service

    async def create_linking_challenge(self, telegram_user_id: str) -> str:
        """
        Create a new linking challenge for a Telegram user.

        Returns the challenge token that the user must provide to link their identity.
        """
        # Check for existing pending challenge
        existing = await self._challenge_repo.get_pending_by_telegram_user_id(telegram_user_id)
        if existing:
            # Return existing challenge token (don't create duplicate)
            return existing.challenge_token

        # Generate secure random token
        challenge_token = secrets.token_urlsafe(self.CHALLENGE_TOKEN_BYTES)
        expires_at = datetime.now(UTC) + timedelta(minutes=self.CHALLENGE_TTL_MINUTES)

        await self._challenge_repo.create(
            telegram_user_id=telegram_user_id,
            challenge_token=challenge_token,
            expires_at=expires_at.isoformat(),
        )

        return challenge_token

    async def verify_challenge_and_link(
        self,
        challenge_token: str,
        student_id: UUID,
    ) -> "TelegramLinkingResult":
        """
        Verify a linking challenge and link the Telegram identity to the student.

        This is called after the student has authenticated and provided the challenge token.
        The student_id comes from the authenticated security context (not from Telegram input).
        """
        # 1. Get and validate challenge
        challenge = await self._challenge_repo.get_by_token(challenge_token)
        if challenge is None:
            await self._audit_service.log_telegram_identity_link_failed(
                telegram_user_id="unknown",
                reason="Invalid challenge token",
            )
            raise ChallengeInvalidError()

        if challenge.status != TelegramLinkingChallengeStatus.PENDING:
            if challenge.status == TelegramLinkingChallengeStatus.USED:
                await self._audit_service.log_telegram_identity_link_failed(
                    telegram_user_id=challenge.telegram_user_id,
                    reason="Challenge already used",
                )
                raise ChallengeAlreadyUsedError()
            elif challenge.status == TelegramLinkingChallengeStatus.EXPIRED:
                await self._audit_service.log_telegram_identity_link_failed(
                    telegram_user_id=challenge.telegram_user_id,
                    reason="Challenge expired",
                )
                raise ChallengeExpiredError()
            else:
                raise ChallengeInvalidError()

        if datetime.now(UTC) > challenge.expires_at:
            await self._challenge_repo.mark_expired(challenge)
            await self._audit_service.log_telegram_identity_link_failed(
                telegram_user_id=challenge.telegram_user_id,
                reason="Challenge expired",
            )
            raise ChallengeExpiredError()

        telegram_user_id = challenge.telegram_user_id

        # 2. Check if Telegram identity already exists
        existing_telegram_identity = await self._telegram_identity_repo.get_by_provider_identity(
            "telegram_bot", telegram_user_id
        )

        if existing_telegram_identity:
            if existing_telegram_identity.student_id == student_id:
                # Already linked to this student - mark challenge as used
                await self._challenge_repo.mark_used(
                    challenge, student_id, existing_telegram_identity.id
                )
                return TelegramLinkingResult(
                    success=True,
                    already_linked=True,
                    telegram_identity_id=existing_telegram_identity.id,
                    student_id=student_id,
                )
            else:
                # Linked to another student
                await self._audit_service.log_telegram_identity_link_failed(
                    telegram_user_id=telegram_user_id,
                    reason="Telegram identity already linked to another student",
                )
                raise TelegramIdentityLinkedToAnotherStudentError()

        # 3. Check if student already has a Telegram identity
        existing_for_student = await self._telegram_identity_repo.get_active_for_student(student_id)
        if existing_for_student:
            await self._audit_service.log_telegram_identity_link_failed(
                telegram_user_id=telegram_user_id,
                reason="Student already has a Telegram identity linked",
            )
            raise StudentAlreadyHasTelegramIdentityError()

        # 4. Verify student exists
        student = await self._student_repo.get_by_id(student_id)
        if student is None:
            raise StudentNotFoundError()

        # 5. Create the TelegramIdentity linking
        telegram_identity = await self._telegram_identity_repo.create(
            student_id=student_id,
            provider="telegram_bot",
            provider_user_id=telegram_user_id,
            status="active",
        )

        # 6. Mark challenge as used
        await self._challenge_repo.mark_used(challenge, student_id, telegram_identity.id)

        # 6. Audit success
        await self._audit_service.log_telegram_identity_linked(
            student_id=student_id,
            telegram_user_id=telegram_user_id,
            event_metadata={"telegram_identity_id": str(telegram_identity.id)},
        )

        return TelegramLinkingResult(
            success=True,
            already_linked=False,
            telegram_identity_id=telegram_identity.id,
            student_id=student_id,
        )

    async def get_challenge_status(self, challenge_token: str) -> "TelegramLinkingChallenge | None":
        """Get challenge by token for status checking."""
        return await self._challenge_repo.get_by_token(challenge_token)

    async def get_pending_challenge_for_user(self, telegram_user_id: str) -> "TelegramLinkingChallenge | None":
        """Get pending challenge for a Telegram user."""
        return await self._challenge_repo.get_pending_by_telegram_user_id(telegram_user_id)

    async def resolve_telegram_identity(
        self, incoming: TelegramIncomingIdentity
    ) -> AuthenticatedIdentity | UnauthenticatedIdentity:
        """
        Resolve a Telegram incoming identity to an authenticated or unauthenticated result.

        This is the standard authentication flow (not linking).
        """
        identity = await self._telegram_identity_repo.get_by_provider_identity(
            incoming.provider, incoming.provider_user_id
        )

        if identity is None:
            return UnauthenticatedIdentity(
                provider=incoming.provider,
                external_identity_id=incoming.provider_user_id,
                reason="Identity not found or not active",
            )

        if identity.status != TelegramIdentityStatus.ACTIVE:
            return UnauthenticatedIdentity(
                provider=incoming.provider,
                external_identity_id=incoming.provider_user_id,
                reason="Identity not active",
            )

        return AuthenticatedIdentity(
            provider=identity.provider.value,
            external_identity_id=identity.provider_user_id,
            student_id=identity.student_id,
            # Use BAILEYS as the authentication method for Telegram bot
            authentication_method=__import__("app.security.context", fromlist=["AuthenticationMethod"]).AuthenticationMethod.BAILEYS,
        )


class TelegramLinkingResult:
    """Result of a Telegram identity linking operation."""

    def __init__(
        self,
        success: bool,
        already_linked: bool,
        telegram_identity_id: UUID,
        student_id: UUID,
    ):
        self.success = success
        self.already_linked = already_linked
        self.telegram_identity_id = telegram_identity_id
        self.student_id = student_id

    def __repr__(self) -> str:
        return (
            f"TelegramLinkingResult(success={self.success}, "
            f"already_linked={self.already_linked}, "
            f"telegram_identity_id={self.telegram_identity_id}, "
            f"student_id={self.student_id})"
        )
