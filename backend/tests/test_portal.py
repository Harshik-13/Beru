"""
Tests for Doctus portal integration.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.integrations.portal.credential_store import FernetCredentialStore
from app.integrations.portal.credentials import FernetCredentialConfig
from app.integrations.portal.dto import PortalSubjectAttendance, SemesterOption
from app.integrations.portal.parser import DoctusParser, DoctusParserError


class TestFernetCredentialConfig:
    """Test Fernet credential configuration."""

    def test_generate_key(self):
        """Test key generation produces valid Fernet key."""
        key = FernetCredentialStore.generate_key()
        assert len(key) > 0
        # Should be valid base64
        import base64

        decoded = base64.urlsafe_b64decode(key.encode())
        assert len(decoded) == 32

    def test_from_settings(self):
        """Test creating config from settings."""
        key = FernetCredentialStore.generate_key()
        config = FernetCredentialConfig.from_settings(key)
        assert config.encryption_key == key


class TestFernetCredentialStore:
    """Test Fernet credential store operations."""

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        return session

    @pytest.fixture
    def config(self):
        key = FernetCredentialStore.generate_key()
        return FernetCredentialConfig(encryption_key=key)

    @pytest.fixture
    def store(self, mock_session, config):
        return FernetCredentialStore(mock_session, config)

    @pytest.mark.asyncio
    async def test_save_and_get_credential(self, store, mock_session):
        """Test saving and retrieving a credential."""
        student_id = uuid4()

        # Mock the database to return the saved credential
        from app.models.portal_credential import PortalCredential

        saved_credential = PortalCredential(
            student_id=student_id,
            portal="doctus",
            roll_number="2021CSE1234",
            encrypted_password="dummy_enc_val",  # noqa: S106
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = saved_credential
        mock_session.execute.return_value = mock_result

        # Save credential
        await store.save_credential(
            student_id, "doctus", "2021CSE1234", "test_password_123"
        )

        # Verify session add and flush were called
        mock_session.add.assert_called()
        mock_session.flush.assert_called()

    @pytest.mark.asyncio
    async def test_get_credential_not_found(self, store, mock_session):
        """Test getting non-existent credential returns None."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await store.get_credential(uuid4(), "doctus")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_credential(self, store, mock_session):
        """Test deleting a credential."""
        await store.delete_credential(uuid4(), "doctus")
        mock_session.execute.assert_called()


class TestDoctusParser:
    """Test Doctus HTML parser."""

    def test_parse_semester_options(self):
        """Test parsing semester options from HTML."""
        html = """
        <html>
            <body>
                <select id="StdSemPop">
                    <option value="102">BT25290203</option>
                    <option value="94" selected>BT25290102</option>
                    <option value="81">BT25290101</option>
                </select>
            </body>
        </html>
        """
        semesters = DoctusParser.parse_semester_options(html)
        assert len(semesters) == 3
        assert semesters[0].semester_id == "102"
        assert semesters[0].display_name == "BT25290203"
        assert semesters[1].semester_id == "94"
        assert semesters[1].display_name == "BT25290102"

    def test_parse_semester_options_empty(self):
        """Test parsing when no select element exists."""
        html = "<html><body><div>No semesters</div></body></html>"
        semesters = DoctusParser.parse_semester_options(html)
        assert semesters == []

    def test_parse_overall_attendance_with_counts_and_pct(self):
        """Test parsing overall attendance with counts and percentage."""
        html = """
        <html>
            <body>
                <div>Overall Attendance: 163 / 284 (57.39)</div>
            </body>
        </html>
        """
        attended, conducted, pct = DoctusParser._parse_overall_attendance(
            __import__("bs4").BeautifulSoup(html, "html.parser")
        )
        assert attended == 163
        assert conducted == 284
        assert pct == 57.39

    def test_parse_overall_attendance_percentage_only(self):
        """Test parsing when only percentage is available."""
        html = """
        <html>
            <body>
                <div>Overall: 75.50%</div>
            </body>
        </html>
        """
        attended, conducted, pct = DoctusParser._parse_overall_attendance(
            __import__("bs4").BeautifulSoup(html, "html.parser")
        )
        assert attended == 0
        assert conducted == 0
        assert pct == 75.50

    def test_parse_overall_attendance_not_found(self):
        """Test when no attendance info found."""
        html = "<html><body><div>No attendance data</div></body></html>"
        attended, conducted, pct = DoctusParser._parse_overall_attendance(
            __import__("bs4").BeautifulSoup(html, "html.parser")
        )
        assert attended == 0
        assert conducted == 0
        assert pct is None

    def test_parse_subject_row_with_monthly_and_cumulative(self):
        """Test parsing subject row with monthly and cumulative data."""
        cells = ["25PC1CS201", "Database Systems", "6 / 7", "16 / 34"]
        subject = DoctusParser._parse_subject_row(cells)
        assert subject is not None
        assert subject.subject_code == "25PC1CS201"
        assert subject.monthly_attended == 6
        assert subject.monthly_conducted == 7
        assert subject.cumulative_attended == 16
        assert subject.cumulative_conducted == 34

    def test_parse_subject_row_cumulative_only(self):
        """Test parsing subject with only cumulative data."""
        cells = ["25PC1CS201", "16 / 34"]
        subject = DoctusParser._parse_subject_row(cells)
        assert subject is not None
        assert subject.subject_code == "25PC1CS201"
        assert subject.monthly_attended is None
        assert subject.monthly_conducted is None
        assert subject.cumulative_attended == 16
        assert subject.cumulative_conducted == 34

    def test_parse_subject_row_invalid_counts(self):
        """Test that invalid counts are rejected."""
        cells = ["25PC1CS201", "20 / 10"]  # attended > conducted
        subject = DoctusParser._parse_subject_row(cells)
        assert subject is None

    def test_parse_subject_row_no_subject_code(self):
        """Test that rows without subject code are rejected."""
        cells = ["Database Systems", "6 / 7", "16 / 34"]
        subject = DoctusParser._parse_subject_row(cells)
        assert subject is None

    def test_parse_subject_row_too_few_cells(self):
        """Test that rows with too few cells are rejected."""
        cells = ["25PC1CS201"]
        subject = DoctusParser._parse_subject_row(cells)
        assert subject is None

    def test_parse_attendance_no_table(self):
        """Test parsing when no table found."""
        html = "<html><body><div>No table here</div></body></html>"
        with pytest.raises(DoctusParserError):
            DoctusParser.parse_attendance(html, "102")


class TestSemesterOptionDTO:
    """Test SemesterOption DTO."""

    def test_creation(self):
        sem = SemesterOption(semester_id="102", display_name="BT25290203")
        assert sem.semester_id == "102"
        assert sem.display_name == "BT25290203"


class TestPortalSubjectAttendanceDTO:
    """Test PortalSubjectAttendance DTO."""

    def test_creation(self):
        subj = PortalSubjectAttendance(
            subject_code="25PC1CS201",
            subject_name="Database Systems",
            monthly_period="September 2026",
            monthly_attended=6,
            monthly_conducted=7,
            cumulative_attended=16,
            cumulative_conducted=34,
        )
        assert subj.subject_code == "25PC1CS201"
        assert subj.monthly_attended == 6
        assert subj.monthly_conducted == 7
        assert subj.cumulative_attended == 16
        assert subj.cumulative_conducted == 34
