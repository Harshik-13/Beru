"""
Tests for PortalCredentialOnboardingService.

Verifies:
1. Multi-step onboarding: roll number -> password -> Doctus auth -> persistence.
2. Failed auth does not overwrite existing valid credentials.
3. Successful auth updates credentials and sets status to CONNECTED.
4. Immediate message deletion invocation.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.integrations.portal.credential_store import FernetCredentialStore
from app.integrations.portal.doctus import DoctusLoginError
from app.integrations.portal.onboarding_service import (
    OnboardingStep,
    PortalCredentialOnboardingService,
)
from app.models.portal_credential import PortalCredential, PortalCredentialStatus


class TestPortalCredentialOnboardingService:
    """Test suite for PortalCredentialOnboardingService."""

    @pytest.fixture(autouse=True)
    def mock_encryption_key(self, monkeypatch):
        key = FernetCredentialStore.generate_key()
        monkeypatch.setattr(
            "app.integrations.portal.onboarding_service.settings.portal_credential_encryption_key",
            key,
        )
        return key

    @pytest.fixture
    def service(self):
        return PortalCredentialOnboardingService()

    @pytest.fixture
    def mock_adapter(self):
        adapter = MagicMock()
        adapter.delete_message = AsyncMock(return_value=True)
        adapter.register_sensitive_chat = MagicMock()
        adapter.unregister_sensitive_chat = MagicMock()
        return adapter

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        return session

    def test_start_flow(self, service):
        student_id = uuid4()
        chat_id = 12345
        msg = service.start_flow(student_id, chat_id)
        assert "roll number" in msg.lower()
        assert service.has_active_flow(student_id)
        state = service.get_flow_state(student_id)
        assert state.step == OnboardingStep.AWAITING_ROLL_NUMBER

    def test_receive_roll_number(self, service, mock_adapter):
        student_id = uuid4()
        chat_id = 12345
        service.start_flow(student_id, chat_id)

        msg = service.receive_roll_number(student_id, "25mis0099", adapter=mock_adapter)
        assert "25MIS0099" in msg
        assert "password" in msg.lower()
        mock_adapter.register_sensitive_chat.assert_called_once_with(chat_id)

        state = service.get_flow_state(student_id)
        assert state.step == OnboardingStep.AWAITING_PASSWORD
        assert state.roll_number == "25MIS0099"

    @pytest.mark.asyncio
    async def test_receive_password_success(self, service, mock_adapter, mock_session):
        student_id = uuid4()
        chat_id = 12345
        service.start_flow(student_id, chat_id)
        service.receive_roll_number(student_id, "25MIS0099", adapter=mock_adapter)

        # Mock successful Doctus login
        with patch("app.integrations.portal.onboarding_service.DoctusAdapter") as mock_doctus_cls:
            mock_doctus = MagicMock()
            mock_doctus.login = AsyncMock(return_value=MagicMock())
            mock_doctus_cls.return_value.__aenter__ = AsyncMock(return_value=mock_doctus)
            mock_doctus_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            success, msg = await service.receive_password(
                student_id=student_id,
                password="ValidPassword123",
                message_id=456,
                session=mock_session,
                adapter=mock_adapter,
            )

        assert success is True
        assert "successfully" in msg.lower()
        # Message was deleted
        mock_adapter.delete_message.assert_called_once_with(chat_id, 456)
        # Sensitive filter unregistered
        mock_adapter.unregister_sensitive_chat.assert_called_once_with(chat_id)
        # DB commit called
        mock_session.commit.assert_called_once()
        # Flow ended
        assert not service.has_active_flow(student_id)

    @pytest.mark.asyncio
    async def test_receive_password_auth_failure_does_not_corrupt_existing_credential(
        self, service, mock_adapter, mock_session
    ):
        student_id = uuid4()
        chat_id = 12345
        service.start_flow(student_id, chat_id)
        service.receive_roll_number(student_id, "25MIS0099", adapter=mock_adapter)

        # Mock existing working credential in DB
        existing_cred = PortalCredential(
            student_id=student_id,
            portal="doctus",
            roll_number="25MIS0099",
            encrypted_password="valid_encrypted_blob",
            status=PortalCredentialStatus.CONNECTED.value,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_cred
        mock_session.execute.return_value = mock_result

        # Mock Doctus rejection
        with patch("app.integrations.portal.onboarding_service.DoctusAdapter") as mock_doctus_cls:
            mock_doctus = MagicMock()
            mock_doctus.login = AsyncMock(side_effect=DoctusLoginError("Invalid password"))
            mock_doctus_cls.return_value.__aenter__ = AsyncMock(return_value=mock_doctus)
            mock_doctus_cls.return_value.__aexit__ = AsyncMock(return_value=None)

            success, msg = await service.receive_password(
                student_id=student_id,
                password="WrongPassword!",
                message_id=789,
                session=mock_session,
                adapter=mock_adapter,
            )

        assert success is False
        assert "authentication failed" in msg.lower()
        # Existing status MUST remain CONNECTED!
        assert existing_cred.status == PortalCredentialStatus.CONNECTED.value
        # Failure timestamp recorded
        assert existing_cred.last_auth_failure_at is not None
        # Message still deleted for privacy
        mock_adapter.delete_message.assert_called_once_with(chat_id, 789)
        # Flow cleaned up
        assert not service.has_active_flow(student_id)
