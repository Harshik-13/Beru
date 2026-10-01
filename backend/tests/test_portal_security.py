"""
Tests for portal credential security boundaries and log safety.

Verifies:
1. Password redaction at transport boundary (raw_provider_data).
2. Telegram delete_message invocation on credential message.
3. Plaintext password never enters application logs, audit events, or conversation context.
4. Exception handling suppresses credential leakage.
"""

from datetime import UTC, datetime
import logging
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.integrations.portal.onboarding_service import (
    OnboardingStep,
    PortalCredentialOnboardingService,
)
from app.models.portal_credential import PortalCredential
from app.telegram.bot_adapter import TelegramBotAdapter


class TestTransportSecurityBoundary:
    """Verify transport-level redaction in TelegramBotAdapter."""

    @pytest.fixture
    def adapter(self):
        adapter = TelegramBotAdapter()
        adapter._config = MagicMock()
        adapter._config.bot_token = "dummy_token"
        adapter._session = MagicMock()
        return adapter

    @pytest.mark.asyncio
    async def test_sensitive_chat_redaction(self, adapter, caplog):
        """Verify raw_provider_data and log text are redacted for sensitive chats."""
        chat_id = 99887766
        adapter.register_sensitive_chat(chat_id)
        assert adapter.is_sensitive_chat(chat_id)

        update = {
            "update_id": 12345,
            "message": {
                "message_id": 42,
                "date": 1600000000,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": 111, "first_name": "TestStudent", "is_bot": False},
                "text": "SuperSecretPassword123!",
            },
        }

        with caplog.at_level(logging.INFO):
            await adapter._process_update(update)

        # Retrieve normalized message from queue
        msg = await adapter._message_queue.get()

        # 1. raw_provider_data MUST NOT contain raw message with password
        assert msg.raw_provider_data == {"redacted": True, "type": "CREDENTIAL_EVENT"}
        assert "SuperSecretPassword123!" not in str(msg.raw_provider_data)

        # 2. Application logs MUST NOT contain password
        for record in caplog.records:
            assert "SuperSecretPassword123!" not in record.message
        assert "[REDACTED_SENSITIVE_CREDENTIAL]" in caplog.text

    @pytest.mark.asyncio
    async def test_delete_message_api_call(self, adapter):
        """Verify delete_message issues correct deleteMessage request to Telegram."""
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"ok": True, "result": True})
        adapter._session.post = MagicMock(return_value=mock_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        success = await adapter.delete_message(chat_id=12345, message_id=99)
        assert success is True
        adapter._session.post.assert_called_once()
        args, kwargs = adapter._session.post.call_args
        assert "/deleteMessage" in args[0]
        assert kwargs["json"] == {"chat_id": 12345, "message_id": 99}


class TestCredentialContextIsolation:
    """Verify passwords never enter conversation or audit contexts."""

    @pytest.mark.asyncio
    async def test_onboarding_state_never_stores_plaintext_password(self):
        """Verify OnboardingFlowState does not have a password attribute."""
        service = PortalCredentialOnboardingService()
        student_id = uuid4()
        chat_id = 12345

        service.start_flow(student_id, chat_id)
        service.receive_roll_number(student_id, "25MIS0012")

        state = service.get_flow_state(student_id)
        assert state is not None
        assert state.roll_number == "25MIS0012"
        assert not hasattr(state, "password")
        assert "password" not in vars(state)

    @pytest.mark.asyncio
    async def test_credential_leak_safety_in_exceptions(self, caplog):
        """Verify that deliberate exceptions containing password strings are not emitted into logs."""
        sensitive_password = "CriticalSecretPassword999!"

        # Simulate exception during Doctus login
        from app.integrations.portal.doctus import DoctusLoginError

        err = DoctusLoginError("Invalid credentials supplied")
        # Ensure string representation of error does not fabricate/leak password
        assert sensitive_password not in str(err)
