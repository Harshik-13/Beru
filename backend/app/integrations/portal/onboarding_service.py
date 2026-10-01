"""
Portal credential onboarding service.

Implements the dedicated security boundary for collecting, validating,
and storing college portal credentials without exposing plaintext passwords
to LLM conversation contexts, logs, or generic message queues.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
import enum
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.portal.credential_store import (
    FernetCredentialConfig,
    FernetCredentialStore,
)
from app.integrations.portal.doctus import DoctusAdapter, DoctusLoginError
from app.repositories.portal_credential import PortalCredentialRepository

logger = logging.getLogger(__name__)


class OnboardingStep(str, enum.Enum):
    """Steps in the portal credential onboarding flow."""

    IDLE = "IDLE"
    AWAITING_ROLL_NUMBER = "AWAITING_ROLL_NUMBER"
    AWAITING_PASSWORD = "AWAITING_PASSWORD"


@dataclass
class OnboardingFlowState:
    """Transient state for an active credential onboarding flow.

    Plaintext passwords must NEVER be stored in this state object.
    """

    student_id: UUID
    chat_id: int
    step: OnboardingStep
    roll_number: str | None = None
    started_at: datetime = datetime.now(UTC)


class PortalCredentialOnboardingService:
    """Service managing conversational portal credential onboarding."""

    def __init__(self) -> None:
        self._active_flows: dict[UUID, OnboardingFlowState] = {}

    def has_active_flow(self, student_id: UUID) -> bool:
        """Check if student currently has an active onboarding flow."""
        return student_id in self._active_flows

    def get_flow_state(self, student_id: UUID) -> OnboardingFlowState | None:
        """Get the active flow state for a student."""
        return self._active_flows.get(student_id)

    def start_flow(self, student_id: UUID, chat_id: int) -> str:
        """Start the credential onboarding flow.

        Returns:
            Prompt requesting the student's roll number.
        """
        self._active_flows[student_id] = OnboardingFlowState(
            student_id=student_id,
            chat_id=chat_id,
            step=OnboardingStep.AWAITING_ROLL_NUMBER,
        )
        logger.info("Started portal credential onboarding for student %s", student_id)
        return "Sure, Sir. Please send your college roll number."

    def receive_roll_number(
        self,
        student_id: UUID,
        roll_number: str,
        adapter=None,
    ) -> str:
        """Receive and record roll number, then advance flow to password prompt.

        Registers the chat as sensitive in the Telegram adapter so the subsequent
        password message is redacted at the transport boundary.
        """
        flow = self._active_flows.get(student_id)
        if not flow or flow.step != OnboardingStep.AWAITING_ROLL_NUMBER:
            return "Sir, no active portal setup was found. Please ask me to connect your portal first."

        clean_roll = roll_number.strip().upper()
        if len(clean_roll) < 4:
            return "Sir, that roll number appears invalid. Please enter your valid college roll number (e.g. 25MIS0012)."

        flow.roll_number = clean_roll
        flow.step = OnboardingStep.AWAITING_PASSWORD

        # Register chat as sensitive so the next message is redacted from raw logs and raw_provider_data
        if adapter and hasattr(adapter, "register_sensitive_chat"):
            adapter.register_sensitive_chat(flow.chat_id)

        return (
            f"Roll number <code>{clean_roll}</code> recorded, Sir.\n\n"
            "Now please send your Doctus password.\n"
            "<i>(Note: Beru will immediately request deletion of your password message "
            "and never persists or logs plaintext credentials.)</i>"
        )

    async def receive_password(
        self,
        student_id: UUID,
        password: str,
        message_id: int,
        session: AsyncSession,
        adapter=None,
        sync_service=None,
    ) -> tuple[bool, str]:
        """Process received password with immediate deletion, test auth, and transactional persistence.

        Plaintext password is held strictly in local scope for authentication and encryption,
        then dropped immediately from memory.
        """
        flow = self._active_flows.get(student_id)
        if not flow or flow.step != OnboardingStep.AWAITING_PASSWORD:
            return False, "Sir, no active portal password request was found."

        chat_id = flow.chat_id
        roll_number = flow.roll_number

        # 1. Immediately request deletion of the message from Telegram
        if adapter and hasattr(adapter, "delete_message"):
            try:
                await adapter.delete_message(chat_id, message_id)
            except Exception as e:
                logger.warning("Failed to delete password message %s: %s", message_id, e)

        # 2. Unregister chat from sensitive redaction
        if adapter and hasattr(adapter, "unregister_sensitive_chat"):
            adapter.unregister_sensitive_chat(chat_id)

        if not password or not password.strip():
            return False, "Sir, an empty password was received. Portal connection cancelled."

        # 3. Authenticate with Doctus FIRST before modifying database
        clean_password = password.strip()
        logger.info(
            "Verifying credentials against Doctus for student %s (roll=%s)",
            student_id,
            roll_number,
        )

        async with DoctusAdapter() as doctus:
            try:
                await doctus.login(roll_number, clean_password)
            except DoctusLoginError as e:
                now = datetime.now(UTC)
                logger.warning(
                    "Doctus login rejected during onboarding for student %s: %s",
                    student_id,
                    e,
                )
                # If student already has stored credentials, update last_auth_failure_at without degrading CONNECTED status
                cred_repo = PortalCredentialRepository(session)
                existing = await cred_repo.get_by_student_and_portal(student_id, "doctus")
                if existing:
                    await cred_repo.update_status(
                        student_id,
                        "doctus",
                        status=existing.status,
                        last_auth_failure_at=now,
                    )
                    await session.commit()

                self.cancel_flow(student_id)
                return (
                    False,
                    f"Sir, authentication failed with the Doctus portal: {e}. "
                    "Your existing credentials (if any) remain unchanged. Please verify your password and try again.",
                )
            except Exception as e:
                logger.error("Doctus communication error during onboarding: %s", e)
                self.cancel_flow(student_id)
                return (
                    False,
                    f"Sir, could not reach the college portal: {e}. Please try again later.",
                )

        # 4. Authentication succeeded! Perform transactional persistence
        now = datetime.now(UTC)
        try:
            config = FernetCredentialConfig.from_settings(
                settings.portal_credential_encryption_key
            )
            store = FernetCredentialStore(session, config)
            await store.save_credential(
                student_id=student_id,
                portal="doctus",
                roll_number=roll_number,
                password=clean_password,
                status="CONNECTED",
                connected_at=now,
                last_successful_auth_at=now,
            )
            await session.commit()
            logger.info("Successfully persisted encrypted portal credentials for student %s", student_id)
        except Exception as e:
            await session.rollback()
            logger.exception("Failed to persist portal credentials: %s", e)
            self.cancel_flow(student_id)
            return (
                False,
                "Sir, a database error occurred while saving your credentials. Please try again.",
            )

        # 5. Clean up flow
        self.cancel_flow(student_id)

        # 6. Attempt initial attendance sync if sync_service provided
        sync_msg = ""
        if sync_service:
            try:
                sync_result = await sync_service.sync_attendance(student_id)
                if sync_result.success:
                    sync_msg = (
                        f"\n\n<b>Initial Sync Complete:</b>\n"
                        f"• Overall Attendance: <b>{sync_result.overall_percentage}%</b>\n"
                        f"• Total Subjects: <b>{sync_result.subject_count}</b>"
                    )
            except Exception as e:
                logger.warning("Initial attendance sync error: %s", e)

        return (
            True,
            f"Sir, your VNR VJIET Doctus portal has been successfully verified and connected!{sync_msg}",
        )

    def cancel_flow(self, student_id: UUID, adapter=None) -> None:
        """Cancel an active onboarding flow and clean up sensitive filters."""
        flow = self._active_flows.pop(student_id, None)
        if flow and adapter and hasattr(adapter, "unregister_sensitive_chat"):
            adapter.unregister_sensitive_chat(flow.chat_id)
