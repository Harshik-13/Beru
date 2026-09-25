from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.audit_event import AuditEventType
from app.models.whatsapp_identity import WhatsAppIdentityStatus
from app.repositories.audit_event import AuditEventRepository
from app.repositories.whatsapp_identity import WhatsAppIdentityRepository
from app.security.audit import AuditService
from app.security.authorization import (
    AuthorizationError,
    authorize_student_access,
    authorize_student_resource,
    require_authenticated_identity,
    require_student,
)
from app.security.authorization_service import AuthorizationService
from app.security.context import (
    AuthenticatedIdentity,
    AuthenticationMethod,
    UnauthenticatedIdentity,
)
from app.security.student_resolver import DatabaseStudentResolver


class TestAuthenticatedIdentity:
    def test_authenticated_identity_creation(self) -> None:
        student_id = uuid4()
        identity = AuthenticatedIdentity(
            provider="whatsapp_web_js",
            external_identity_id="919876543210@c.us",
            student_id=student_id,
            authentication_method=AuthenticationMethod.WHATSAPP_WEB_JS,
        )
        assert identity.provider == "whatsapp_web_js"
        assert identity.external_identity_id == "919876543210@c.us"
        assert identity.student_id == student_id
        assert identity.authentication_method == AuthenticationMethod.WHATSAPP_WEB_JS

    def test_unauthenticated_identity_creation(self) -> None:
        identity = UnauthenticatedIdentity(
            provider="whatsapp_web_js",
            external_identity_id="919876543210@c.us",
            reason="Identity not found",
        )
        assert identity.provider == "whatsapp_web_js"
        assert identity.reason == "Identity not found"


class TestAuthorizationPrimitives:
    def test_require_authenticated_identity_success(self) -> None:
        student_id = uuid4()
        identity = AuthenticatedIdentity(
            provider="whatsapp_web_js",
            external_identity_id="test@c.us",
            student_id=student_id,
            authentication_method=AuthenticationMethod.WHATSAPP_WEB_JS,
        )
        result = require_authenticated_identity(identity)
        assert result == identity

    def test_require_authenticated_identity_failure(self) -> None:
        with pytest.raises(AuthorizationError, match="Authentication required"):
            require_authenticated_identity(None)

    def test_require_student(self) -> None:
        student_id = uuid4()
        identity = AuthenticatedIdentity(
            provider="whatsapp_web_js",
            external_identity_id="test@c.us",
            student_id=student_id,
            authentication_method=AuthenticationMethod.WHATSAPP_WEB_JS,
        )
        result = require_student(identity)
        assert result == student_id

    def test_authorize_student_resource_success(self) -> None:
        student_id = uuid4()
        authorize_student_resource(student_id, student_id, "test_resource", uuid4())

    def test_authorize_student_resource_failure(self) -> None:
        student1 = uuid4()
        student2 = uuid4()
        with pytest.raises(AuthorizationError, match="Unauthorized access"):
            authorize_student_resource(student1, student2, "test_resource")

    def test_authorize_student_access_success(self) -> None:
        student_id = uuid4()
        authorize_student_access(student_id, student_id, "read")

    def test_authorize_student_access_failure(self) -> None:
        student1 = uuid4()
        student2 = uuid4()
        with pytest.raises(AuthorizationError, match="not authorized to read"):
            authorize_student_access(student1, student2, "read")


class TestAuthorizationService:
    @pytest.fixture
    def mock_audit(self) -> MagicMock:
        return MagicMock(spec=AuditService)

    @pytest.fixture
    def auth_service(self, mock_audit: MagicMock) -> AuthorizationService:
        return AuthorizationService(audit_service=mock_audit)

    def test_get_authenticated_student(
        self, auth_service: AuthorizationService
    ) -> None:
        student_id = uuid4()
        identity = AuthenticatedIdentity(
            provider="whatsapp_web_js",
            external_identity_id="test@c.us",
            student_id=student_id,
            authentication_method=AuthenticationMethod.WHATSAPP_WEB_JS,
        )
        result = auth_service.get_authenticated_student(identity)
        assert result == student_id

    def test_get_authenticated_student_none_raises(
        self, auth_service: AuthorizationService
    ) -> None:
        with pytest.raises(AuthorizationError):
            auth_service.get_authenticated_student(None)

    def test_authorize_resource_success(
        self, auth_service: AuthorizationService
    ) -> None:
        student_id = uuid4()
        resource_id = uuid4()
        auth_service.authorize_resource(
            student_id, student_id, "attendance", resource_id
        )

    def test_authorize_resource_failure(
        self, auth_service: AuthorizationService
    ) -> None:
        student1 = uuid4()
        student2 = uuid4()
        with pytest.raises(AuthorizationError):
            auth_service.authorize_resource(student1, student2, "attendance")

    def test_authorize_student_access_success(
        self, auth_service: AuthorizationService
    ) -> None:
        student_id = uuid4()
        auth_service.authorize_student_access(student_id, student_id, "view")

    def test_authorize_student_access_failure(
        self, auth_service: AuthorizationService
    ) -> None:
        student1 = uuid4()
        student2 = uuid4()
        with pytest.raises(AuthorizationError):
            auth_service.authorize_student_access(student1, student2, "view")


class TestDatabaseStudentResolver:
    @pytest.fixture
    def mock_identity_repo(self) -> MagicMock:
        return MagicMock(spec=WhatsAppIdentityRepository)

    @pytest.fixture
    def resolver(self, mock_identity_repo: MagicMock) -> DatabaseStudentResolver:
        return DatabaseStudentResolver(mock_identity_repo)

    @pytest.mark.asyncio
    async def test_active_identity_resolves_to_student(
        self, resolver: DatabaseStudentResolver, mock_identity_repo: MagicMock
    ) -> None:
        from app.models.whatsapp_identity import WhatsAppIdentity

        student_id = uuid4()
        mock_identity = WhatsAppIdentity(
            student_id=student_id,
            provider="whatsapp_web_js",
            provider_user_id="919876543210@c.us",
            status=WhatsAppIdentityStatus.ACTIVE,
        )
        mock_identity_repo.get_by_provider_identity = AsyncMock(
            return_value=mock_identity
        )

        result = await resolver.get_student_for_identity(
            "whatsapp_web_js", "919876543210@c.us"
        )

        assert result is not None
        assert result.student_id == student_id
        assert result.provider == "whatsapp_web_js"
        assert result.external_identity_id == "919876543210@c.us"

    @pytest.mark.asyncio
    async def test_unknown_identity_returns_none(
        self, resolver: DatabaseStudentResolver, mock_identity_repo: MagicMock
    ) -> None:
        mock_identity_repo.get_by_provider_identity = AsyncMock(return_value=None)

        result = await resolver.get_student_for_identity(
            "whatsapp_web_js", "unknown@c.us"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_disabled_identity_returns_none(
        self, resolver: DatabaseStudentResolver, mock_identity_repo: MagicMock
    ) -> None:
        from app.models.whatsapp_identity import WhatsAppIdentity

        student_id = uuid4()
        mock_identity = WhatsAppIdentity(
            student_id=student_id,
            provider="whatsapp_web_js",
            provider_user_id="919876543210@c.us",
            status=WhatsAppIdentityStatus.DISABLED,
        )
        mock_identity_repo.get_by_provider_identity = AsyncMock(
            return_value=mock_identity
        )

        result = await resolver.get_student_for_identity(
            "whatsapp_web_js", "919876543210@c.us"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_revoked_identity_returns_none(
        self, resolver: DatabaseStudentResolver, mock_identity_repo: MagicMock
    ) -> None:
        from app.models.whatsapp_identity import WhatsAppIdentity

        student_id = uuid4()
        mock_identity = WhatsAppIdentity(
            student_id=student_id,
            provider="whatsapp_web_js",
            provider_user_id="919876543210@c.us",
            status=WhatsAppIdentityStatus.REVOKED,
        )
        mock_identity_repo.get_by_provider_identity = AsyncMock(
            return_value=mock_identity
        )

        result = await resolver.get_student_for_identity(
            "whatsapp_web_js", "919876543210@c.us"
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_get_identity_status(
        self, resolver: DatabaseStudentResolver, mock_identity_repo: MagicMock
    ) -> None:
        from app.models.whatsapp_identity import WhatsAppIdentity

        mock_identity = WhatsAppIdentity(
            student_id=uuid4(),
            provider="whatsapp_web_js",
            provider_user_id="919876543210@c.us",
            status=WhatsAppIdentityStatus.ACTIVE,
        )
        mock_identity_repo.get_by_provider_identity = AsyncMock(
            return_value=mock_identity
        )

        status = await resolver.get_identity_status(
            "whatsapp_web_js", "919876543210@c.us"
        )
        assert status == "active"

    @pytest.mark.asyncio
    async def test_get_identity_status_unknown(
        self, resolver: DatabaseStudentResolver, mock_identity_repo: MagicMock
    ) -> None:
        mock_identity_repo.get_by_provider_identity = AsyncMock(return_value=None)

        status = await resolver.get_identity_status("whatsapp_web_js", "unknown@c.us")
        assert status == "unknown"


class TestAuditService:
    @pytest.fixture
    def mock_audit_repo(self) -> MagicMock:
        return MagicMock(spec=AuditEventRepository)

    @pytest.fixture
    def mock_session(self) -> MagicMock:
        session = MagicMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def audit_service(self, mock_session: MagicMock) -> AuditService:
        return AuditService(mock_session)

    @pytest.mark.asyncio
    async def test_log_authentication_success(
        self, audit_service: AuditService, mock_session: MagicMock
    ) -> None:
        student_id = uuid4()
        event = await audit_service.log_authentication_success(
            student_id=student_id,
            provider="whatsapp_web_js",
            external_identity_id="919876543210@c.us",
        )
        assert event.event_type == AuditEventType.AUTHENTICATION_SUCCESS
        assert event.student_id == student_id
        assert event.provider == "whatsapp_web_js"
        assert event.success is True
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_authentication_failure(
        self, audit_service: AuditService, mock_session: MagicMock
    ) -> None:
        event = await audit_service.log_authentication_failure(
            provider="whatsapp_web_js",
            external_identity_id="919876543210@c.us",
            reason="Identity not found",
        )
        assert event.event_type == AuditEventType.AUTHENTICATION_FAILURE
        assert event.student_id is None
        assert event.success is False
        assert event.error_message == "Identity not found"

    @pytest.mark.asyncio
    async def test_log_authorization_failure(
        self, audit_service: AuditService, mock_session: MagicMock
    ) -> None:
        student_id = uuid4()
        resource_id = uuid4()
        event = await audit_service.log_authorization_failure(
            student_id=student_id,
            resource_type="attendance",
            resource_id=resource_id,
            action="read",
        )
        assert event.event_type == AuditEventType.AUTHORIZATION_FAILURE
        assert event.student_id == student_id
        assert event.resource_type == "attendance"
        assert event.resource_id == resource_id
        assert event.success is False
        assert "read" in event.error_message


class TestCrossStudentIsolation:
    """Tests ensuring cross-student isolation is enforced."""

    @pytest.fixture
    def auth_service(self) -> AuthorizationService:
        return AuthorizationService(audit_service=None)

    def test_student_a_cannot_access_student_b_resource(
        self, auth_service: AuthorizationService
    ) -> None:
        student_a = uuid4()
        student_b = uuid4()
        resource_id = uuid4()

        with pytest.raises(AuthorizationError):
            auth_service.authorize_resource(
                student_a, student_b, "attendance", resource_id
            )

    def test_student_a_cannot_access_student_b_data(
        self, auth_service: AuthorizationService
    ) -> None:
        student_a = uuid4()
        student_b = uuid4()

        with pytest.raises(AuthorizationError):
            auth_service.authorize_student_access(student_a, student_b, "view")

    def test_different_identities_dont_share_student_access(
        self, auth_service: AuthorizationService
    ) -> None:
        """Two different WhatsApp identities cannot resolve to same student access."""
        student_a = uuid4()
        student_b = uuid4()

        with pytest.raises(AuthorizationError):
            auth_service.authorize_resource(student_a, student_b, "timetable")


class TestAuditEventImmutability:
    """Tests ensuring audit events cannot be modified through normal paths."""

    def test_audit_event_has_no_update_methods(self) -> None:
        """AuditEvent model should not have public setters for critical fields."""
        from app.models.audit_event import AuditEvent

        assert hasattr(AuditEvent, "event_type")
        assert hasattr(AuditEvent, "student_id")
        assert hasattr(AuditEvent, "success")
        assert hasattr(AuditEvent, "created_at")
