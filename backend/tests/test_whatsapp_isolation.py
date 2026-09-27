from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.security.authorization import (
    AuthorizationError,
    authorize_student_resource,
)
from app.security.context import (
    AuthenticatedIdentity,
    AuthenticationMethod,
    UnauthenticatedIdentity,
)
from app.security.student_resolver import DatabaseStudentResolver
from app.whatsapp.auth import (
    WhatsAppIdentityResolver,
    create_whatsapp_incoming_identity,
)
from app.whatsapp.models import (
    IncomingWhatsAppMessage,
    OutgoingWhatsAppMessage,
    WhatsAppConnectionEvent,
    WhatsAppConnectionState,
    WhatsAppContactIdentity,
    WhatsAppMessageAttachment,
    WhatsAppMessageType,
)
from app.whatsapp.provider import (
    WhatsAppProvider,
    WhatsAppProviderConfig,
    provider_registry,
)


class MockProviderForTesting(WhatsAppProvider):
    """Mock WhatsApp provider for testing the interface."""

    def __init__(self):
        self._state = WhatsAppConnectionState.DISCONNECTED

    @property
    def provider_name(self) -> str:
        return "test"

    @property
    def supported_message_types(self) -> set[str]:
        return {"text"}

    async def initialize(self, config: WhatsAppProviderConfig) -> None:
        pass

    async def start(self) -> None:
        self._state = WhatsAppConnectionState.CONNECTED

    async def stop(self) -> None:
        self._state = WhatsAppConnectionState.DISCONNECTED

    async def get_connection_state(self) -> WhatsAppConnectionState:
        return self._state

    async def connection_events(self):
        yield WhatsAppConnectionEvent(
            state=self._state,
            provider="test",
        )

    async def get_our_identity(self) -> WhatsAppContactIdentity | None:
        return WhatsAppContactIdentity(
            provider="test",
            provider_user_id="test_user",
        )

    async def send_message(self, message: OutgoingWhatsAppMessage) -> str:
        return "test_msg_id"

    async def incoming_messages(self):
        yield IncomingWhatsAppMessage(
            event_id="test_event",
            provider="test",
            provider_timestamp=1234567890,
            from_contact=WhatsAppContactIdentity(
                provider="test",
                provider_user_id="test_user",
            ),
            to_contact=WhatsAppContactIdentity(
                provider="test",
                provider_user_id="bot_user",
            ),
            message_type=WhatsAppMessageType.TEXT,
            text="test",
        )

    async def delivery_receipts(self):
        yield

    async def request_qr_code(self) -> str | None:
        return None

    async def request_pairing_code(self, phone_number: str) -> str | None:
        return None

    async def logout(self) -> None:
        self._state = WhatsAppConnectionState.DISCONNECTED

    async def is_connected(self) -> bool:
        return self._state == WhatsAppConnectionState.CONNECTED


class TestProviderInterface:
    """Test that WhatsApp provider interface is properly defined."""

    def test_provider_registration(self):
        """Test that provider can be registered."""
        provider_registry.register(MockProviderForTesting)
        assert "test" in provider_registry.list_providers()

    def test_provider_registration_duplicate(self):
        """Test that duplicate registration overwrites existing."""
        provider_registry.register(MockProviderForTesting)
        # Second registration should overwrite, not raise
        provider_registry.register(MockProviderForTesting)
        assert "test" in provider_registry.list_providers()

    def test_provider_not_found(self):
        """Test that getting unknown provider raises error."""
        with pytest.raises(ValueError):
            provider_registry.get("nonexistent")


class TestNormalizedModels:
    """Test normalized WhatsApp message models."""

    def test_contact_identity_creation(self):
        """Test creating WhatsAppContactIdentity."""
        identity = WhatsAppContactIdentity(
            provider="baileys",
            provider_user_id="919876543210@s.whatsapp.net",
            normalized_identifier="+919876543210",
            display_name="Test User",
        )
        assert identity.provider == "baileys"
        assert identity.provider_user_id == "919876543210@s.whatsapp.net"
        assert identity.normalized_identifier == "+919876543210"

    def test_incoming_message_creation(self):
        """Test creating IncomingWhatsAppMessage."""
        identity = WhatsAppContactIdentity(
            provider="baileys",
            provider_user_id="919876543210@s.whatsapp.net",
        )
        msg = IncomingWhatsAppMessage(
            event_id="3EB0ABC123DEF",
            provider="baileys",
            provider_timestamp=1699900000,
            from_contact=identity,
            to_contact=WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id="919876543210@s.whatsapp.net",
            ),
            message_type=WhatsAppMessageType.TEXT,
            text="Hello, world!",
        )
        assert msg.text == "Hello, world!"
        assert msg.message_type == WhatsAppMessageType.TEXT

    def test_outgoing_message_creation(self):
        """Test creating OutgoingWhatsAppMessage."""
        msg = OutgoingWhatsAppMessage(
            to_contact=WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id="919876543210@s.whatsapp.net",
            ),
            from_contact=WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id="919876543210@s.whatsapp.net",
            ),
            message_type=WhatsAppMessageType.TEXT,
            text="Hello from bot!",
        )
        assert msg.text == "Hello from bot!"

    def test_connection_event(self):
        """Test creating WhatsAppConnectionEvent."""
        event = WhatsAppConnectionEvent(
            state=WhatsAppConnectionState.CONNECTED,
            provider="baileys",
        )
        assert event.state == WhatsAppConnectionState.CONNECTED
        assert event.provider == "baileys"

    def test_message_attachment(self):
        """Test creating WhatsAppMessageAttachment."""
        attachment = WhatsAppMessageAttachment(
            media_type=WhatsAppMessageType.IMAGE,
            mime_type="image/jpeg",
            file_name="photo.jpg",
            file_size=1024,
            media_key="media_key_123",
            caption="A photo",
        )
        assert attachment.media_type == WhatsAppMessageType.IMAGE
        assert attachment.mime_type == "image/jpeg"


class TestCoreIsolation:
    """Test that core models don't import WhatsApp provider classes."""

    def test_provider_abstraction_no_baileys_import(self):
        """Test that WhatsAppProvider interface doesn't import Baileys classes."""
        import inspect

        import app.whatsapp.provider as provider_module

        source = inspect.getsource(provider_module)
        # Should not import concrete adapter
        assert "BaileysAdapter" not in source
        assert "node" not in source.lower()

    def test_auth_module_no_baileys_import(self):
        """Test that auth module doesn't import Baileys."""
        import inspect

        import app.whatsapp.auth as auth_module

        source = inspect.getsource(auth_module)
        assert "BaileysAdapter" not in source

    def test_security_context_no_whatsapp_import(self):
        """Test that security context doesn't import WhatsApp provider classes."""
        import inspect

        import app.security.context as context_module

        source = inspect.getsource(context_module)
        # Should not import concrete provider classes
        assert "BaileysAdapter" not in source
        assert "TelegramBotAdapter" not in source


class TestAuthenticationIntegration:
    """Test WhatsApp authentication integration with security system."""

    @pytest.fixture
    def mock_student_resolver(self):
        mock_whatsapp_repo = MagicMock()
        mock_telegram_repo = MagicMock()
        mock_identity = MagicMock()
        mock_identity.student_id = "test-student-uuid"
        mock_identity.status = "active"
        mock_identity.provider = "baileys"
        mock_identity.provider_user_id = "919876543210@s.whatsapp.net"
        mock_whatsapp_repo.get_by_provider_identity = AsyncMock(
            return_value=mock_identity
        )
        mock_telegram_repo.get_by_provider_identity = AsyncMock(return_value=None)


        return DatabaseStudentResolver(mock_whatsapp_repo, mock_telegram_repo)

    @pytest.mark.asyncio
    async def test_active_identity_resolves_to_student(self, mock_student_resolver):
        resolver = WhatsAppIdentityResolver(mock_student_resolver)

        incoming = create_whatsapp_incoming_identity(
            provider="baileys",
            provider_user_id="919876543210@s.whatsapp.net",
        )

        result = await resolver.resolve(incoming)

        assert isinstance(result, AuthenticatedIdentity)
        assert result.student_id == "test-student-uuid"
        assert result.provider == "baileys"
        assert result.external_identity_id == "919876543210@s.whatsapp.net"

    @pytest.mark.asyncio
    async def test_unknown_identity_returns_unauthenticated(
        self, mock_student_resolver
    ):
        mock_student_resolver._whatsapp_repo.get_by_provider_identity = AsyncMock(
            return_value=None
        )

        resolver = WhatsAppIdentityResolver(mock_student_resolver)

        incoming = create_whatsapp_incoming_identity(
            provider="baileys",
            provider_user_id="unknown@s.whatsapp.net",
        )

        result = await resolver.resolve(incoming)

        assert isinstance(result, UnauthenticatedIdentity)
        assert result.reason == "Identity not found or not active"

    @pytest.mark.asyncio
    async def test_disabled_identity_rejected(self, mock_student_resolver):
        from app.models.whatsapp_identity import (
            WhatsAppIdentity,
            WhatsAppIdentityStatus,
        )

        mock_identity = WhatsAppIdentity(
            provider="baileys",
            provider_user_id="919876543210@s.whatsapp.net",
            status=WhatsAppIdentityStatus.DISABLED,
        )
        mock_student_resolver._whatsapp_repo.get_by_provider_identity = AsyncMock(
            return_value=mock_identity
        )

        resolver = WhatsAppIdentityResolver(mock_student_resolver)

        incoming = create_whatsapp_incoming_identity(
            provider="baileys",
            provider_user_id="919876543210@s.whatsapp.net",
        )

        result = await resolver.resolve(incoming)

        assert isinstance(result, UnauthenticatedIdentity)


class TestProviderAbstractionCompliance:
    """Verify mock provider implements the interface correctly."""

    @pytest.fixture
    def provider(self):
        return MockProviderForTesting()

    @pytest.mark.asyncio
    async def test_provider_interface_methods_exist(self, provider):
        """Verify all abstract methods are implemented."""
        await provider.initialize(
            WhatsAppProviderConfig(provider_name="test", config={})
        )
        await provider.start()
        state = await provider.get_connection_state()
        assert state == WhatsAppConnectionState.CONNECTED

        identity = await provider.get_our_identity()
        assert identity is not None
        assert identity.provider == "test"

        msg_id = await provider.send_message(
            OutgoingWhatsAppMessage(
                to_contact=MagicMock(),
                from_contact=MagicMock(),
                message_type=WhatsAppMessageType.TEXT,
                text="test",
            )
        )
        assert msg_id == "test_msg_id"

        await provider.stop()
        state = await provider.get_connection_state()
        assert state == WhatsAppConnectionState.DISCONNECTED


class TestSecurityContextIndependence:
    """Verify security context works independently of WhatsApp."""

    def test_authenticated_identity_creation(self):
        from app.security.context import AuthenticatedIdentity

        student_id = uuid4()
        identity = AuthenticatedIdentity(
            provider="baileys",
            external_identity_id="919876543210@s.whatsapp.net",
            student_id=student_id,
            authentication_method=AuthenticationMethod.BAILEYS,
        )

        assert identity.student_id == student_id
        assert identity.provider == "baileys"
        assert identity.authentication_method == AuthenticationMethod.BAILEYS

    def test_authorization_uses_student_id_not_provider_id(self):

        student_a = uuid4()
        student_b = uuid4()

        # Should succeed - same student
        authorize_student_resource(student_a, student_a, "attendance")

        # Should fail - different student
        with pytest.raises(AuthorizationError):
            authorize_student_resource(student_a, student_b, "attendance")

    def test_never_trust_client_student_id(self):
        """Core authorization NEVER trusts client-supplied IDs."""

        authenticated_student = uuid4()
        client_supplied_student = uuid4()  # Malicious client sends this

        # Must compare authenticated_student with resource_owner
        # NOT client_supplied_student with resource_owner
        with pytest.raises(AuthorizationError):
            authorize_student_resource(
                authenticated_student, client_supplied_student, "resource"
            )


class TestIdempotencyKeyGeneration:
    """Test idempotency key generation follows strategy."""

    def test_inbound_idempotency_key_format(self):
        msg = IncomingWhatsAppMessage(
            event_id="3EB0ABC123DEF",
            provider="baileys",
            provider_timestamp=1699900000,
            from_contact=WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id="919876543210@s.whatsapp.net",
            ),
            to_contact=WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id="919876543210@s.whatsapp.net",
            ),
            message_type=WhatsAppMessageType.TEXT,
            text="Test",
        )

        key = msg.get_idempotency_key()
        assert key.startswith("whatsapp:baileys:")
        assert "3EB0ABC123DEF" in key

    def test_different_messages_different_keys(self):
        msg1 = IncomingWhatsAppMessage(
            event_id="msg1",
            provider="baileys",
            provider_timestamp=1699900000,
            from_contact=WhatsAppContactIdentity(
                provider="baileys", provider_user_id="a@s.whatsapp.net"
            ),
            to_contact=WhatsAppContactIdentity(
                provider="baileys", provider_user_id="b@s.whatsapp.net"
            ),
            message_type=WhatsAppMessageType.TEXT,
            text="Test 1",
        )

        msg2 = IncomingWhatsAppMessage(
            event_id="msg2",
            provider="baileys",
            provider_timestamp=1699900000,
            from_contact=WhatsAppContactIdentity(
                provider="baileys", provider_user_id="a@s.whatsapp.net"
            ),
            to_contact=WhatsAppContactIdentity(
                provider="baileys", provider_user_id="b@s.whatsapp.net"
            ),
            message_type=WhatsAppMessageType.TEXT,
            text="Test 2",
        )

        assert msg1.get_idempotency_key() != msg2.get_idempotency_key()


class TestAuthenticationFlow:
    """Test complete authentication flow from provider to authorization."""

    @pytest.mark.asyncio
    async def test_full_flow_provider_to_authorization(self):
        """Test auth flow: Provider → Identity → AuthResolver → AuthIdentity → Authz"""
        # 1. Provider creates normalized identity
        incoming = create_whatsapp_incoming_identity(
            provider="baileys",
            provider_user_id="919876543210@s.whatsapp.net",
            normalized_identifier="+919876543210",
        )

        # 2. Resolve to authenticated identity
        mock_whatsapp_repo = MagicMock()
        mock_telegram_repo = MagicMock()
        mock_identity = MagicMock()
        mock_identity.student_id = "student-123"
        mock_identity.status = "active"
        mock_identity.provider = "baileys"
        mock_identity.provider_user_id = "919876543210@s.whatsapp.net"
        mock_whatsapp_repo.get_by_provider_identity = AsyncMock(
            return_value=mock_identity
        )
        mock_telegram_repo.get_by_provider_identity = AsyncMock(return_value=None)


        resolver = DatabaseStudentResolver(mock_whatsapp_repo, mock_telegram_repo)
        from app.whatsapp.auth import WhatsAppIdentityResolver

        auth_resolver = WhatsAppIdentityResolver(resolver)

        auth_result = await auth_resolver.resolve(incoming)

        # 3. Use in authorization
        from app.security.authorization import authorize_student_resource

        authorize_student_resource(auth_result.student_id, "student-123", "attendance")

        # 4. Cross-student access denied
        from app.security.authorization import AuthorizationError

        with pytest.raises(AuthorizationError):
            authorize_student_resource(
                auth_result.student_id, "student-999", "attendance"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
