"""Tests for Telegram provider isolation and normalization."""

from datetime import UTC, datetime

import pytest

from app.telegram.auth import (
    TelegramIncomingIdentity,
    create_telegram_incoming_identity,
)
from app.telegram.models import (
    IncomingTelegramMessage,
    OutgoingTelegramMessage,
    TelegramConnectionEvent,
    TelegramContactIdentity,
    TelegramMessageAttachment,
    TelegramMessageType,
)
from app.telegram.provider import (
    TelegramProvider,
    telegram_provider_registry,
)


class TestProviderInterface:
    """Test that Telegram provider interface is properly defined."""

    def test_provider_registration(self):
        """Test that provider can be registered."""
        telegram_provider_registry.register(type("TestProvider", (TelegramProvider,), {
            "provider_name": "test",
            "supported_message_types": {"text"},
            "initialize": lambda self, config: None,
            "start": lambda self: None,
            "stop": lambda self: None,
            "get_connection_state": lambda self: "connected",
            "connection_events": lambda self: (),
            "get_our_identity": lambda self: None,
            "send_message": lambda self, msg: "123",
            "incoming_messages": lambda self: (),
            "delivery_receipts": lambda self: (),
        }))
        assert "test" in telegram_provider_registry.list_providers()

    def test_provider_not_found(self):
        """Test that getting unknown provider raises error."""
        with pytest.raises(ValueError):
            telegram_provider_registry.get("nonexistent")


class TestNormalizedModels:
    """Test normalized Telegram message models."""

    def test_contact_identity_creation(self):
        """Test creating TelegramContactIdentity."""
        identity = TelegramContactIdentity(
            provider="telegram_bot",
            provider_user_id="123456789",
            normalized_identifier="@testuser",
            display_name="Test User",
            is_bot=False,
            is_premium=True,
            language_code="en",
        )
        assert identity.provider == "telegram_bot"
        assert identity.provider_user_id == "123456789"
        assert identity.normalized_identifier == "@testuser"

    def test_incoming_message_creation(self):
        """Test creating IncomingTelegramMessage."""
        identity = TelegramContactIdentity(
            provider="telegram_bot",
            provider_user_id="123456789",
        )
        msg = IncomingTelegramMessage(
            event_id="12345:67890",
            provider="telegram_bot",
            provider_timestamp=int(datetime.now(UTC).timestamp()),
            from_contact=identity,
            to_contact=TelegramContactIdentity(
                provider="telegram_bot",
                provider_user_id="987654321",
            ),
            message_type=TelegramMessageType.TEXT,
            text="Hello, world!",
            chat_id="123456789",
        )
        assert msg.text == "Hello, world!"
        assert msg.message_type == TelegramMessageType.TEXT
        assert msg.get_idempotency_key() == "telegram:telegram_bot:12345:67890"

    def test_outgoing_message_creation(self):
        """Test creating OutgoingTelegramMessage."""
        msg = OutgoingTelegramMessage(
            to_contact=TelegramContactIdentity(
                provider="telegram_bot",
                provider_user_id="123456789",
            ),
            from_contact=TelegramContactIdentity(
                provider="telegram_bot",
                provider_user_id="987654321",
            ),
            message_type=TelegramMessageType.TEXT,
            text="Hello from bot!",
            chat_id="123456789",
        )
        assert msg.text == "Hello from bot!"
        assert msg.chat_id == "123456789"

    def test_connection_event(self):
        """Test creating TelegramConnectionEvent."""
        event = TelegramConnectionEvent(
            state="polling",
            provider="telegram_bot",
        )
        assert event.state == "polling"
        assert event.provider == "telegram_bot"

    def test_message_attachment(self):
        """Test creating TelegramMessageAttachment."""
        attachment = TelegramMessageAttachment(
            media_type=TelegramMessageType.PHOTO,
            mime_type="image/jpeg",
            file_name="photo.jpg",
            file_size=1024,
            file_id="file_123",
            file_unique_id="unique_123",
            caption="A photo",
        )
        assert attachment.media_type == TelegramMessageType.PHOTO
        assert attachment.mime_type == "image/jpeg"


class TestCoreIsolation:
    """Test that core models don't import Telegram provider classes."""

    def test_provider_abstraction_no_telegram_import(self):
        """Test that TelegramProvider interface doesn't import concrete classes."""
        import inspect

        import app.telegram.provider as provider_module
        source = inspect.getsource(provider_module)
        # Should not import concrete adapter
        assert "TelegramBotAdapter" not in source
        assert "aiohttp" not in source

    def test_models_no_provider_import(self):
        """Test that models don't import provider."""
        import inspect

        import app.telegram.models as models_module
        source = inspect.getsource(models_module)
        assert "TelegramProvider" not in source


class TestAuthenticationIntegration:
    """Test Telegram identity authentication integration."""

    def test_telegram_incoming_identity_creation(self):
        """Test creating TelegramIncomingIdentity from contact."""
        contact = TelegramContactIdentity(
            provider="telegram_bot",
            provider_user_id="123456789",
            normalized_identifier="@testuser",
            display_name="Test User",
        )
        incoming = TelegramIncomingIdentity.from_contact(contact)
        assert incoming.provider == "telegram_bot"
        assert incoming.provider_user_id == "123456789"
        assert incoming.normalized_identifier == "@testuser"

    def test_telegram_incoming_identity_to_incoming_identity(self):
        """Test conversion to security IncomingIdentity."""
        incoming = create_telegram_incoming_identity(
            provider="telegram_bot",
            provider_user_id="123456789",
            normalized_identifier="@testuser",
            provider_metadata={"display_name": "Test User"},
        )
        security_identity = incoming.to_incoming_identity()
        assert security_identity.provider == "telegram_bot"
        assert security_identity.external_identity_id == "123456789"

    def test_factory_function(self):
        """Test factory function for creating TelegramIncomingIdentity."""
        incoming = create_telegram_incoming_identity(
            provider="telegram_bot",
            provider_user_id="123456789",
            normalized_identifier="@testuser",
        )
        assert incoming.provider == "telegram_bot"
        assert incoming.provider_user_id == "123456789"


class TestIdempotencyKeyGeneration:
    """Test idempotency key generation for Telegram updates."""

    def test_incoming_idempotency_key_format(self):
        """Test that idempotency keys are properly formatted."""
        identity = TelegramContactIdentity(
            provider="telegram_bot",
            provider_user_id="123456789",
        )
        msg = IncomingTelegramMessage(
            event_id="12345:67890",
            provider="telegram_bot",
            provider_timestamp=int(datetime.now(UTC).timestamp()),
            from_contact=identity,
            to_contact=TelegramContactIdentity(
                provider="telegram_bot",
                provider_user_id="987654321",
            ),
            message_type=TelegramMessageType.TEXT,
            text="Test",
            chat_id="123456789",
        )
        key = msg.get_idempotency_key()
        assert key == "telegram:telegram_bot:12345:67890"

    def test_different_updates_different_keys(self):
        """Test that different updates generate different keys."""
        identity = TelegramContactIdentity(
            provider="telegram_bot",
            provider_user_id="123456789",
        )
        to_contact = TelegramContactIdentity(
            provider="telegram_bot",
            provider_user_id="987654321",
        )
        msg1 = IncomingTelegramMessage(
            event_id="12345:67890",
            provider="telegram_bot",
            provider_timestamp=int(datetime.now(UTC).timestamp()),
            from_contact=identity,
            to_contact=to_contact,
            message_type=TelegramMessageType.TEXT,
            text="Test 1",
            chat_id="123456789",
        )
        msg2 = IncomingTelegramMessage(
            event_id="12345:67891",
            provider="telegram_bot",
            provider_timestamp=int(datetime.now(UTC).timestamp()),
            from_contact=identity,
            to_contact=to_contact,
            message_type=TelegramMessageType.TEXT,
            text="Test 2",
            chat_id="123456789",
        )
        assert msg1.get_idempotency_key() != msg2.get_idempotency_key()


class TestUnsupportedUpdateHandling:
    """Test handling of unsupported Telegram update types."""

    def test_unknown_message_type_graceful(self):
        """Test that unknown message types are handled gracefully."""
        # This is tested at the adapter level, but we verify the model supports UNKNOWN
        identity = TelegramContactIdentity(
            provider="telegram_bot",
            provider_user_id="123456789",
        )
        msg = IncomingTelegramMessage(
            event_id="12345:67890",
            provider="telegram_bot",
            provider_timestamp=int(datetime.now(UTC).timestamp()),
            from_contact=identity,
            to_contact=TelegramContactIdentity(
                provider="telegram_bot",
                provider_user_id="987654321",
            ),
            message_type=TelegramMessageType.UNKNOWN,
            text=None,
            chat_id="123456789",
        )
        assert msg.message_type == TelegramMessageType.UNKNOWN


class TestSecurityContextIndependence:
    """Test security isolation between Telegram students."""

    def test_telegram_identity_resolver_uses_provider_field(self):
        """Test that resolver uses provider field for lookup."""
        # The resolver should use the provider field, not just user ID
        incoming = create_telegram_incoming_identity(
            provider="telegram_bot",
            provider_user_id="123456789",
        )
        security_identity = incoming.to_incoming_identity()
        # Both provider and external_identity_id must be used
        assert security_identity.provider == "telegram_bot"
        assert security_identity.external_identity_id == "123456789"


class TestTelegramCredentialsNotInLLM:
    """Test that Telegram credentials never enter LLM/tool arguments."""

    def test_bot_token_not_in_models(self):
        """Test that bot token is not part of message models."""
        import inspect

        import app.telegram.models as models_module
        source = inspect.getsource(models_module)
        assert "bot_token" not in source.lower()
        assert "BOT_TOKEN" not in source

    def test_config_separates_credentials(self):
        """Test that configuration keeps credentials separate from message data."""
        import inspect

        import app.telegram.bot_adapter as bot_module
        source = inspect.getsource(bot_module)
        # Bot token should only be in config, not in message processing
        assert "bot_token" in source
        # But message models don't have it
        import app.telegram.models as models_module
        models_source = inspect.getsource(models_module)
        assert "bot_token" not in models_source
