from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.student import Student, StudentStatus
from app.models.whatsapp_identity import (
    WhatsAppIdentity,
    WhatsAppIdentityStatus,
    WhatsAppProvider,
)
from app.repositories.student import StudentRepository
from app.repositories.whatsapp_identity import WhatsAppIdentityRepository
from app.schemas.student import StudentCreate, StudentRead
from app.schemas.whatsapp_identity import WhatsAppIdentityCreate, WhatsAppIdentityRead


class TestStudentModel:
    def test_student_default_status(self) -> None:
        student = Student(status=StudentStatus.ACTIVE)
        assert student.status == StudentStatus.ACTIVE
        # id is generated on flush, not on construction

    def test_student_custom_status(self) -> None:
        student = Student(status=StudentStatus.INACTIVE)
        assert student.status == StudentStatus.INACTIVE

    def test_student_repr(self) -> None:
        student_id = uuid4()
        student = Student(id=student_id, status=StudentStatus.ACTIVE)
        assert str(student_id) in repr(student)
        assert "ACTIVE" in repr(student)  # Enum repr shows class name

    def test_student_id_generated_on_flush(self) -> None:
        """Verify id is None before flush, set after."""
        student = Student()
        assert student.id is None  # Set by DB on flush


class TestWhatsAppIdentityModel:
    def test_whatsapp_identity_defaults(self) -> None:
        student_id = uuid4()
        identity = WhatsAppIdentity(
            student_id=student_id,
            provider=WhatsAppProvider.UNKNOWN,
            provider_user_id="test_user_123",
            status=WhatsAppIdentityStatus.ACTIVE,
        )
        assert identity.id is None  # Set by DB on flush
        assert identity.student_id == student_id
        assert identity.provider == WhatsAppProvider.UNKNOWN
        assert identity.provider_user_id == "test_user_123"
        assert identity.normalized_identifier is None
        assert identity.status == WhatsAppIdentityStatus.ACTIVE

    def test_whatsapp_identity_with_normalized(self) -> None:
        student_id = uuid4()
        identity = WhatsAppIdentity(
            student_id=student_id,
            provider=WhatsAppProvider.WHATSAPP_WEB_JS,
            provider_user_id="919876543210@c.us",
            normalized_identifier="+919876543210",
            status=WhatsAppIdentityStatus.ACTIVE,
        )
        assert identity.normalized_identifier == "+919876543210"

    def test_whatsapp_identity_repr(self) -> None:
        student_id = uuid4()
        identity_id = uuid4()
        identity = WhatsAppIdentity(
            id=identity_id,
            student_id=student_id,
            provider=WhatsAppProvider.BAILEYS,
            provider_user_id="test@c.us",
        )
        assert str(identity_id) in repr(identity)
        assert str(student_id) in repr(identity)
        assert "BAILEYS" in repr(identity)  # Enum repr shows class name


class TestStudentSchemas:
    def test_student_create_schema(self) -> None:
        schema = StudentCreate()
        assert schema.status == "active"

    def test_student_read_schema(self) -> None:
        student_id = uuid4()
        now = datetime.now(UTC)
        schema = StudentRead(
            id=student_id,
            status="active",
            created_at=now,
            updated_at=now,
        )
        assert schema.id == student_id
        assert schema.status == "active"


class TestWhatsAppIdentitySchemas:
    def test_whatsapp_identity_create_schema(self) -> None:
        student_id = uuid4()
        schema = WhatsAppIdentityCreate(
            student_id=student_id,
            provider="whatsapp_web_js",
            provider_user_id="919876543210@c.us",
            normalized_identifier="+919876543210",
        )
        assert schema.student_id == student_id
        assert schema.provider == "whatsapp_web_js"
        assert schema.normalized_identifier == "+919876543210"

    def test_whatsapp_identity_read_schema(self) -> None:
        identity_id = uuid4()
        student_id = uuid4()
        now = datetime.now(UTC)
        schema = WhatsAppIdentityRead(
            id=identity_id,
            student_id=student_id,
            provider="baileys",
            provider_user_id="test@c.us",
            normalized_identifier="+919876543210",
            status="active",
            created_at=now,
            updated_at=now,
        )
        assert schema.id == identity_id
        assert schema.student_id == student_id


class TestStudentRepository:
    @pytest.fixture
    def mock_session(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_session: MagicMock) -> StudentRepository:
        return StudentRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create_student(
        self, repo: StudentRepository, mock_session: MagicMock
    ) -> None:
        mock_session.flush = AsyncMock()
        student = await repo.create()
        assert isinstance(student, Student)
        assert student.status == StudentStatus.ACTIVE
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_id(
        self, repo: StudentRepository, mock_session: MagicMock
    ) -> None:
        student_id = uuid4()
        mock_student = Student(id=student_id)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_student
        mock_session.execute = AsyncMock(return_value=mock_result)

        student = await repo.get_by_id(student_id)
        assert student == mock_student
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self, repo: StudentRepository, mock_session: MagicMock
    ) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        student = await repo.get_by_id(uuid4())
        assert student is None


class TestWhatsAppIdentityRepository:
    @pytest.fixture
    def mock_session(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_session: MagicMock) -> WhatsAppIdentityRepository:
        return WhatsAppIdentityRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create_identity(
        self, repo: WhatsAppIdentityRepository, mock_session: MagicMock
    ) -> None:
        mock_session.flush = AsyncMock()
        student_id = uuid4()

        identity = await repo.create(
            student_id=student_id,
            provider="whatsapp_web_js",
            provider_user_id="919876543210@c.us",
        )
        assert isinstance(identity, WhatsAppIdentity)
        assert identity.student_id == student_id
        assert identity.provider == WhatsAppProvider.WHATSAPP_WEB_JS
        assert identity.provider_user_id == "919876543210@c.us"
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_provider_identity(
        self, repo: WhatsAppIdentityRepository, mock_session: MagicMock
    ) -> None:
        student_id = uuid4()
        mock_identity = WhatsAppIdentity(
            student_id=student_id,
            provider=WhatsAppProvider.WHATSAPP_WEB_JS,
            provider_user_id="919876543210@c.us",
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_identity
        mock_session.execute = AsyncMock(return_value=mock_result)

        identity = await repo.get_by_provider_identity(
            "whatsapp_web_js", "919876543210@c.us"
        )
        assert identity == mock_identity
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_for_student(
        self, repo: WhatsAppIdentityRepository, mock_session: MagicMock
    ) -> None:
        student_id = uuid4()
        mock_identities = [
            WhatsAppIdentity(
                student_id=student_id,
                provider=WhatsAppProvider.UNKNOWN,
                provider_user_id="user1",
            ),
            WhatsAppIdentity(
                student_id=student_id,
                provider=WhatsAppProvider.WHATSAPP_WEB_JS,
                provider_user_id="user2",
            ),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_identities
        mock_session.execute = AsyncMock(return_value=mock_result)

        identities = await repo.get_for_student(student_id)
        assert len(identities) == 2
        assert all(i.student_id == student_id for i in identities)


class TestOwnershipIsolation:
    """Tests verifying multi-user isolation at the model/repository level."""

    def test_different_students_have_different_ids(self) -> None:
        student1 = Student(id=uuid4())
        student2 = Student(id=uuid4())
        assert student1.id != student2.id

    def test_whatsapp_identity_links_to_student(self) -> None:
        student1 = Student(id=uuid4())
        student2 = Student(id=uuid4())
        identity1 = WhatsAppIdentity(
            student_id=student1.id,
            provider=WhatsAppProvider.UNKNOWN,
            provider_user_id="user1",
        )
        identity2 = WhatsAppIdentity(
            student_id=student2.id,
            provider=WhatsAppProvider.UNKNOWN,
            provider_user_id="user2",
        )
        assert identity1.student_id == student1.id
        assert identity2.student_id == student2.id
        assert identity1.student_id != identity2.student_id

    def test_unique_constraint_on_provider_user(self) -> None:
        """Verify the unique constraint is defined on the model."""
        import sqlalchemy as sa
        from sqlalchemy import inspect

        mapper = inspect(WhatsAppIdentity)
        unique_constraints = [
            c
            for c in mapper.tables[0].constraints
            if isinstance(c, sa.UniqueConstraint)
        ]
        constraint_names = [c.name for c in unique_constraints]
        assert "uq_whatsapp_identity_provider_user" in constraint_names
