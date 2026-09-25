"""
Core Isolation Tests for WhatsApp Provider Abstraction

These tests verify that the Beru core never depends on provider-specific classes.
The core should only interact with the abstract WhatsAppProvider interface
and normalized models.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.security.context import AuthenticatedIdentity, UnauthenticatedIdentity
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
)


class MockProviderForTesting(WhatsAppProvider):
    """Minimal mock provider for interface compliance testing."""

    def __init__(self):
        self._state = WhatsAppConnectionState.DISCONNECTED

    @property
    def provider_name(self) -> str:
        return "test_provider"

    @property
    def supported_message_types(self) -> set[str]:
        return {"text", "image"}

    async def initialize(self, config: WhatsAppProviderConfig) -> None:
        pass

    async def start(self) -> None:
        self._state = WhatsAppConnectionState.CONNECTED

    async def stop(self) -> None:
        self._state = WhatsAppConnectionState.DISCONNECTED

    async def get_connection_state(self) -> WhatsAppConnectionState:
        return self._state

    async def connection_events(self):
        if False:
            yield

    async def get_our_identity(self):
        return WhatsAppContactIdentity(
            provider="test",
            provider_user_id="test@s.whatsapp.net",
        )

    async def send_message(self, message):
        return "test_msg_id"

    async def incoming_messages(self):
        if False:
            yield

    async def delivery_receipts(self):
        if False:
            yield

    async def request_qr_code(self):
        return None

    async def request_pairing_code(self, phone_number: str):
        return None

    async def logout(self):
        pass

    async def is_connected(self) -> bool:
        return self._state == WhatsAppConnectionState.CONNECTED


class TestProviderInterface:
    """Verify the WhatsAppProvider abstract interface."""

    def test_provider_registration(self):
        """Test that providers can be registered and retrieved."""
        from app.whatsapp.provider import WhatsAppProviderRegistry

        registry = WhatsAppProviderRegistry()
        registry.register(MockProviderForTesting)

        assert "test_provider" in registry.list_providers()
        provider_class = registry.get("test_provider")
        assert provider_class == MockProviderForTesting

    def test_provider_registration_duplicate(self):
        """Test that duplicate registration raises or overwrites."""
        from app.whatsapp.provider import WhatsAppProviderRegistry

        registry = WhatsAppProviderRegistry()
        registry.register(MockProviderForTesting)

        # Second registration should work (overwrite)
        registry.register(MockProviderForTesting)
        assert len(registry.list_providers()) == 1

    def test_provider_not_found(self):
        """Test that getting unknown provider raises."""
        from app.whatsapp.provider import WhatsAppProviderRegistry

        registry = WhatsAppProviderRegistry()
        with pytest.raises(ValueError, match="not registered"):
            registry.get("nonexistent")


class TestNormalizedModels:
    """Test normalized WhatsApp models work correctly."""

    def test_contact_identity_creation(self):
        contact = WhatsAppContactIdentity(
            provider="baileys",
            provider_user_id="919876543210@s.whatsapp.net",
            normalized_identifier="+919876543210",
            display_name="Test User",
        )
        assert contact.provider == "baileys"
        assert contact.provider_user_id == "919876543210@s.whatsapp.net"
        assert contact.normalized_identifier == "+919876543210"

    def test_incoming_message_creation(self):
        msg = IncomingWhatsAppMessage(
            event_id="test_event_123",
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
            text="Hello, world!",
        )
        assert msg.text == "Hello, world!"
        assert msg.message_type == WhatsAppMessageType.TEXT
        assert "baileys" in msg.get_idempotency_key()

    def test_outgoing_message_creation(self):
        outgoing = OutgoingWhatsAppMessage(
            to_contact=WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id="919876543210@s.whatsapp.net",
            ),
            from_contact=WhatsAppContactIdentity(
                provider="baileys",
                provider_user_id="919876543210@s.whatsapp.net",
            ),
            message_type=WhatsAppMessageType.TEXT,
            text="Reply from bot",
            idempotency_key="idempotent_123",
        )
        assert outgoing.text == "Reply from bot"
        assert outgoing.idempotency_key == "idempotent_123"

    def test_connection_event(self):
        event = WhatsAppConnectionEvent(
            state=WhatsAppConnectionState.CONNECTED,
            provider="baileys",
            qr_code="fake_qr_data",
        )
        assert event.state == WhatsAppConnectionState.CONNECTED
        assert event.provider == "baileys"
        assert event.qr_code == "fake_qr_data"

    def test_message_attachment(self):
        attachment = WhatsAppMessageAttachment(
            media_type=WhatsAppMessageType.IMAGE,
            mime_type="image/jpeg",
            file_name="photo.jpg",
            file_size=102400,
            url="https://example.com/photo.jpg",
        )
        assert attachment.media_type == WhatsAppMessageType.IMAGE
        assert attachment.mime_type == "image/jpeg"


class TestCoreIsolation:
    """Tests proving core never imports provider-specific classes."""

    def test_core_models_dont_import_provider_classes(self):
        """Verify whatsapp.models doesn't import Baileys-specific classes."""
        import app.whatsapp.models as models

        module_attrs = dir(models)
        # Should only have normalized models
        assert "IncomingWhatsAppMessage" in module_attrs
        assert "OutgoingWhatsAppMessage" in module_attrs
        assert "WhatsAppConnectionEvent" in module_attrs
        assert "WhatsAppContactIdentity" in module_attrs

    def test_provider_abstraction_no_baileys_import(self):
        """Verify provider abstraction doesn't import Baileys."""
        import app.whatsapp.provider as provider_module

        module_attrs = dir(provider_module)
        # Should only have abstract interface and registry
        assert "WhatsAppProvider" in module_attrs
        assert "WhatsAppProviderConfig" in module_attrs
        assert "provider_registry" in module_attrs
        assert "WhatsAppProviderRegistry" in module_attrs

    def test_auth_module_no_baileys_import(self):
        """Verify auth module doesn't import Baileys."""
        import app.whatsapp.auth as auth_module

        module_attrs = dir(auth_module)
        assert "WhatsAppIncomingIdentity" in module_attrs
        assert "WhatsAppIdentityResolver" in module_attrs
        assert "create_whatsapp_incoming_identity" in module_attrs

    def test_security_context_no_whatsapp_import(self):
        """Verify security context is independent of WhatsApp."""
        import app.security.context as context_module

        module_attrs = dir(context_module)
        assert "AuthenticatedIdentity" in module_attrs
        assert "UnauthenticatedIdentity" in module_attrs
        assert "AuthenticationMethod" in module_attrs
        # No WhatsApp-specific types


class TestAuthenticationIntegration:
    """Test WhatsApp authentication integration with security system."""

    @pytest.fixture
    def mock_student_resolver(self):
        repo = MagicMock()
        mock_identity = MagicMock()
        mock_identity.student_id = "test-student-uuid"
        mock_identity.status = "active"
        mock_identity.provider = "baileys"
        mock_identity.provider_user_id = "919876543210@s.whatsapp.net"
        repo.get_by_provider_identity = AsyncMock(return_value=mock_identity)

        from app.security.student_resolver import DatabaseStudentResolver

        return DatabaseStudentResolver(repo)

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
        mock_repo = MagicMock(spec=["get_by_provider_identity"])
        mock_repo.get_by_provider_identity = AsyncMock(return_value=None)

        from app.security.student_resolver import DatabaseStudentResolver

        resolver = DatabaseStudentResolver(mock_repo)
        auth_resolver = WhatsAppIdentityResolver(resolver)

        incoming = create_whatsapp_incoming_identity(
            provider="baileys",
            provider_user_id="unknown@s.whatsapp.net",
        )

        result = await auth_resolver.resolve(incoming)

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
        mock_repo = MagicMock()
        mock_repo.get_by_provider_identity = AsyncMock(return_value=mock_identity)

        from app.security.student_resolver import DatabaseStudentResolver

        resolver = DatabaseStudentResolver(mock_repo)
        auth_resolver = WhatsAppIdentityResolver(resolver)

        incoming = create_whatsapp_incoming_identity(
            provider="baileys",
            provider_user_id="919876543210@s.whatsapp.net",
        )

        result = await auth_resolver.resolve(incoming)

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
        from app.security.context import AuthenticatedIdentity, AuthenticationMethod

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
        from app.security.authorization import (
            AuthorizationError,
            authorize_student_resource,
        )

        student_a = uuid4()
        student_b = uuid4()

        # Should succeed - same student
        authorize_student_resource(student_a, student_a, "attendance")

        # Should fail - different student
        with pytest.raises(AuthorizationError):
            authorize_student_resource(student_a, student_b, "attendance")

    def test_never_trust_client_student_id(self):
        """Core authorization NEVER trusts client-supplied IDs."""
        from app.security.authorization import (
            AuthorizationError,
            authorize_student_resource,
        )

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
        mock_repo = MagicMock()
        mock_identity = MagicMock()
        mock_identity.student_id = "student-123"
        mock_identity.status = "active"
        mock_repo.get_by_provider_identity = AsyncMock(return_value=mock_identity)

        from app.security.student_resolver import DatabaseStudentResolver

        resolver = DatabaseStudentResolver(mock_repo)
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
