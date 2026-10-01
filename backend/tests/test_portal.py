"""
Tests for Doctus portal integration.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest

from app.integrations.portal.credential_store import FernetCredentialStore
from app.integrations.portal.credentials import FernetCredentialConfig
from app.integrations.portal.doctus import (
    DoctusAdapter,
    DoctusLoginError,
    DoctusSession,
    DoctusSessionError,
    _extract_antiforgery_token,
)
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


class TestDoctusTokenExtraction:
    """Test anti-forgery token extraction logic."""

    def test_extract_token_standard_attributes(self):
        html = '<input name="__RequestVerificationToken" type="hidden" value="token_val_123" />'
        assert _extract_antiforgery_token(html) == "token_val_123"

    def test_extract_token_reversed_attributes(self):
        html = '<input type="hidden" value="token_val_reversed" name="__RequestVerificationToken" />'
        assert _extract_antiforgery_token(html) == "token_val_reversed"

    def test_extract_token_mixed_casing(self):
        html = '<INPUT NAME="__RequestVerificationToken" TYPE="HIDDEN" VALUE="TOKEN_CASE" />'
        assert _extract_antiforgery_token(html) == "TOKEN_CASE"

    def test_extract_token_missing(self):
        html = '<div><input name="Other" value="123" /></div>'
        assert _extract_antiforgery_token(html) == ""


class TestDoctusHtmlStudentIdExtraction:
    """Test HTML student ID extraction logic."""

    def test_extract_html_id_standard_input(self):
        adapter = DoctusAdapter()
        html = '<div><input name="StdId" type="hidden" value="456" /></div>'
        assert adapter._extract_protected_student_id_from_html(html) == "456"

    def test_extract_html_id_reversed_input(self):
        adapter = DoctusAdapter()
        html = '<div><input value="789" type="hidden" name="StudentId" /></div>'
        assert adapter._extract_protected_student_id_from_html(html) == "789"

    def test_extract_html_id_js_variable(self):
        adapter = DoctusAdapter()
        html = '<script>var stdId = "101112";</script>'
        assert adapter._extract_protected_student_id_from_html(html) == "101112"

    def test_extract_html_id_missing_returns_empty(self):
        adapter = DoctusAdapter()
        html = '<div><p>Welcome to portal</p></div>'
        assert adapter._extract_protected_student_id_from_html(html) == ""

    def test_extract_html_id_rejects_url_values(self):
        adapter = DoctusAdapter()
        html = '<input name="StdId" value="/Student/Dashboard" />'
        assert adapter._extract_protected_student_id_from_html(html) == ""


class TestDoctusAdapterLogin:
    """Test suite for DoctusAdapter login and session management."""

    @pytest.mark.asyncio
    async def test_login_success(self):
        """1. Verify standard successful login with token and session."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="csrf_test_token" />',
                    headers={"Set-Cookie": "OM5.Antiforgery=csrf_cookie_val; path=/"},
                )
            if request.method == "POST" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    json={"Status": 1, "Data": {"UserId": "std_12345", "xMessage": "Welcome"}},
                    headers={"Set-Cookie": ".AspNetCore.Cookies=auth_cookie_val; path=/"},
                )
            return httpx.Response(404)

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        session = await adapter.login("25071A6231", "test_pass_123")
        assert isinstance(session, DoctusSession)
        assert session.protected_student_id == "std_12345"
        assert session.cookies.get("OM5.Antiforgery") == "csrf_cookie_val"
        assert session.cookies.get(".AspNetCore.Cookies") == "auth_cookie_val"

    @pytest.mark.asyncio
    async def test_login_get_happens_before_post(self):
        """2. Verify GET happens before POST."""
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path))
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="token1" />',
                )
            return httpx.Response(200, json={"Status": 1, "Data": {"UserId": "u1"}})

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        await adapter.login("25071A6231", "pass")
        assert calls == [("GET", "/Login"), ("POST", "/Login")]

    @pytest.mark.asyncio
    async def test_login_uses_correct_password_field(self):
        """3. Verify POST contains xPassword and NOT Password."""
        captured_data = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            if request.method == "POST":
                # Parse form content
                body = request.content.decode()
                for part in body.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        captured_data[k] = v
                return httpx.Response(200, json={"Status": 1, "Data": {"UserId": "u1"}})
            return httpx.Response(404)

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        await adapter.login("25071A6231", "my_secret_pass")
        assert "xPassword" in captured_data
        assert captured_data["xPassword"] == "my_secret_pass"
        assert "Password" not in captured_data

    @pytest.mark.asyncio
    async def test_login_sends_antiforgery_token(self):
        """4. Verify token in form data and RequestVerificationToken header."""
        captured_headers = {}
        captured_data = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="token_xyz_999" />',
                )
            if request.method == "POST":
                captured_headers.update(dict(request.headers))
                for part in request.content.decode().split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        captured_data[k] = v
                return httpx.Response(200, json={"Status": 1, "Data": {"UserId": "u1"}})
            return httpx.Response(404)

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        await adapter.login("25071A6231", "pass")
        assert captured_data.get("__RequestVerificationToken") == "token_xyz_999"
        assert captured_data.get("UserName") == "25071A6231"
        assert captured_data.get("xUsername") == "25071A6231"
        assert captured_headers.get("requestverificationtoken") == "token_xyz_999"

    @pytest.mark.asyncio
    async def test_login_sends_referer(self):
        """5. Verify Referer header in POST."""
        captured_headers = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            if request.method == "POST":
                captured_headers.update(dict(request.headers))
                return httpx.Response(200, json={"Status": 1, "Data": {"UserId": "u1"}})
            return httpx.Response(404)

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        await adapter.login("25071A6231", "pass")
        assert captured_headers.get("referer") == f"{adapter.BASE_URL}/Login"

    @pytest.mark.asyncio
    async def test_login_preserves_get_cookie(self):
        """6. Seed antiforgery cookie on GET and verify session preserves it."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                    headers={"Set-Cookie": "OM5.Antiforgery=csrf_seed_cookie; path=/"},
                )
            return httpx.Response(200, json={"Status": 1, "Data": {"UserId": "u1"}})

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        session = await adapter.login("25071A6231", "pass")
        assert session.cookies.get("OM5.Antiforgery") == "csrf_seed_cookie"

    @pytest.mark.asyncio
    async def test_login_does_not_require_legacy_relic_cookie(self):
        """7. Successful login without relic_VNRVJIET cookie still succeeds."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            return httpx.Response(
                200,
                json={"Status": 1, "Data": {"UserId": "u1"}},
                headers={"Set-Cookie": ".AspNetCore.Session=session_val; path=/"},
            )

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        session = await adapter.login("25071A6231", "pass")
        assert session.protected_student_id == "u1"
        assert "relic_VNRVJIET" not in session.cookies

    @pytest.mark.asyncio
    async def test_login_missing_antiforgery_token(self):
        """8. Missing token in GET HTML fails safely."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html><body>No token here</body></html>")

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        with pytest.raises(DoctusLoginError) as exc_info:
            await adapter.login("25071A6231", "pass")
        assert "Failed to acquire anti-forgery token from portal" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self):
        """9. Status == 0 raises DoctusLoginError with portal message."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            return httpx.Response(
                200,
                json={"Status": 0, "Data": {"Message": "Invalid username or password."}},
            )

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        with pytest.raises(DoctusLoginError) as exc_info:
            await adapter.login("25071A6231", "wrong_pass")
        assert "Invalid username or password." in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_login_blocked_or_captcha_message(self):
        """10. Preserves blocked/CAPTCHA information safely."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            return httpx.Response(
                200,
                json={"Status": 0, "Data": {"BlockedUntil": "2026-10-01 23:59:59"}},
            )

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        with pytest.raises(DoctusLoginError) as exc_info:
            await adapter.login("25071A6231", "pass")
        assert "Account temporarily blocked until 2026-10-01 23:59:59." in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_login_http_400(self):
        """11. Verify HTTP 400 produces safe DoctusLoginError without body leakage."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            return httpx.Response(400, text="ASP.NET Bad Request Internal Trace")

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        with pytest.raises(DoctusLoginError) as exc_info:
            await adapter.login("25071A6231", "pass")
        assert "Portal rejected authentication request (HTTP 400)" in str(exc_info.value)
        assert "Internal Trace" not in str(exc_info.value)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_login_http_500(self):
        """12. Verify HTTP 500 produces safe DoctusLoginError."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            return httpx.Response(500, text="Server Error")

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        with pytest.raises(DoctusLoginError) as exc_info:
            await adapter.login("25071A6231", "pass")
        assert "Portal server error (HTTP 500)" in str(exc_info.value)
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_login_malformed_json(self):
        """13. Verify malformed JSON response fails safely."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            return httpx.Response(200, text="<html><body>Not JSON</body></html>")

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        with pytest.raises(DoctusLoginError) as exc_info:
            await adapter.login("25071A6231", "pass")
        assert "Invalid portal response format" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_login_password_never_leaks(self):
        """14. Verify sentinel password never appears in exceptions or traces."""
        sentinel_pass = "SENTINEL_SECRET_XYZ987!"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            return httpx.Response(400, text="Bad Request")

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        with pytest.raises(DoctusLoginError) as exc_info:
            await adapter.login("25071A6231", sentinel_pass)
        assert sentinel_pass not in str(exc_info.value)
        assert sentinel_pass not in repr(exc_info.value)

    @pytest.mark.asyncio
    async def test_login_token_and_cookies_never_leak(self):
        """15. Verify token and cookie values never leak into exception messages."""
        sentinel_token = "SENTINEL_TOKEN_SECRET_123"
        sentinel_cookie = "SENTINEL_COOKIE_SECRET_456"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    text=f'<input name="__RequestVerificationToken" type="hidden" value="{sentinel_token}" />',
                    headers={"Set-Cookie": f"OM5.Antiforgery={sentinel_cookie}; path=/"},
                )
            return httpx.Response(
                200,
                json={"Status": 0, "Data": {"Message": "Invalid credentials"}},
            )

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        with pytest.raises(DoctusLoginError) as exc_info:
            await adapter.login("25071A6231", "pass")
        assert sentinel_token not in str(exc_info.value)
        assert sentinel_cookie not in str(exc_info.value)


class TestAuthenticatedSessionContinuity:
    """Test downstream session continuity across portal operations."""

    @pytest.mark.asyncio
    async def test_authenticated_session_continuity(self):
        """Verify login session cookies are passed to downstream get_semesters call at /Student/Dashboard."""
        captured_requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            if request.method == "GET" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="csrf_tok" />',
                    headers={"Set-Cookie": "OM5.Antiforgery=csrf_abc123; path=/"},
                )
            if request.method == "POST" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    json={"Status": 1, "Data": "/Student/Dashboard"},
                    headers={"Set-Cookie": ".AspNetCore.Cookies=aspnet_auth_xyz; path=/"},
                )
            if request.method == "GET" and request.url.path == "/Student/Dashboard":
                html = """
                <html>
                    <body>
                        <select id="StdSemPop">
                            <option value="102">BT25290203</option>
                        </select>
                    </body>
                </html>
                """
                return httpx.Response(200, text=html)
            return httpx.Response(404)

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        # Step 1 & 2: Login
        session = await adapter.login("25071A6231", "valid_pass")
        assert session.protected_student_id == "25071A6231"

        # Step 3 & 4: Call get_semesters() using the established session
        semesters = await adapter.get_semesters()
        assert len(semesters) == 1
        assert semesters[0].semester_id == "102"

        # Step 5: Verify downstream request went to /Student/Dashboard as document GET
        sem_request = captured_requests[-1]
        assert sem_request.url.path == "/Student/Dashboard"
        assert "x-requested-with" not in sem_request.headers
        assert "text/html" in sem_request.headers.get("accept", "")
        cookie_header = sem_request.headers.get("cookie", "")
        assert "OM5.Antiforgery=csrf_abc123" in cookie_header
        assert ".AspNetCore.Cookies=aspnet_auth_xyz" in cookie_header

    @pytest.mark.asyncio
    async def test_login_success_with_redirect_url_data(self):
        """Verify login succeeds when Data is a redirect URL and falls back to roll number."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                    headers={"Set-Cookie": "OM5.Antiforgery=cookie1; path=/"},
                )
            if request.method == "POST" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    json={"Status": 1, "Data": "/Student/Dashboard"},
                    headers={"Set-Cookie": ".AspNetCore.Cookies=cookie2; path=/"},
                )
            return httpx.Response(404)

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        session = await adapter.login("25071a6231", "pass")
        assert session.protected_student_id == "25071A6231"
        assert session.protected_student_id != "/Student/Dashboard"

    @pytest.mark.asyncio
    async def test_session_enriched_by_html_id_discovery(self):
        """Verify session.protected_student_id is enriched when get_semesters discovers internal StdId in dashboard HTML."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            if request.method == "POST" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    json={"Status": 1, "Data": "/Student/Dashboard"},
                )
            if request.method == "GET" and request.url.path == "/Student/Dashboard":
                html = """
                <html>
                    <body>
                        <input type="hidden" name="StdId" value="internal_std_9999" />
                        <select id="StdSemPop">
                            <option value="102">BT25290203</option>
                        </select>
                    </body>
                </html>
                """
                return httpx.Response(200, text=html)
            return httpx.Response(404)

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        # Login initially sets temporary fallback to normalized roll number
        session = await adapter.login("25071a6231", "pass")
        assert session.protected_student_id == "25071A6231"

        # get_semesters discovers the internal StdId and enriches the session
        await adapter.get_semesters()
        assert adapter._session.protected_student_id == "internal_std_9999"

    @pytest.mark.asyncio
    async def test_get_semesters_fallback_to_legacy_attendance_route(self):
        """Verify get_semesters falls back to /Academic/Student/Attendance if /Student/Dashboard is 404."""
        requested_paths = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            if request.method == "GET" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            if request.method == "POST" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    json={"Status": 1, "Data": "/Student/Dashboard"},
                )
            if request.method == "GET" and request.url.path == "/Student/Dashboard":
                return httpx.Response(404, text="Not Found")
            if request.method == "GET" and request.url.path == "/Academic/Student/Attendance":
                html = """
                <html>
                    <body>
                        <select id="StdSemPop">
                            <option value="105">BT25290205</option>
                        </select>
                    </body>
                </html>
                """
                return httpx.Response(200, text=html)
            return httpx.Response(404)

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        await adapter.login("25071a6231", "pass")
        semesters = await adapter.get_semesters()
        assert len(semesters) == 1
        assert semesters[0].semester_id == "105"
        assert "/Student/Dashboard" in requested_paths
        assert "/Academic/Student/Attendance" in requested_paths

    @pytest.mark.asyncio
    async def test_get_attendance_uses_verified_parameterized_endpoint(self):
        """Verify get_attendance calls /Academic/Shared/GetStdAttPer?studentId={id}&semId={sem_id}."""
        captured_requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            if request.method == "GET" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            if request.method == "POST" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    json={"Status": 1, "Data": {"UserId": "std_param_test"}},
                )
            if request.method == "GET" and request.url.path == "/Academic/Shared/GetStdAttPer":
                return httpx.Response(
                    200,
                    json={
                        "Status": 1,
                        "Data": "<table><tr><th>Subject</th><th>Attended</th><th>Conducted</th></tr><tr><td>CS101</td><td>20</td><td>25</td></tr></table>",
                    },
                )
            return httpx.Response(404)

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
        )

        await adapter.login("25071a6231", "pass")
        attendance = await adapter.get_attendance("99")

        assert attendance is not None
        assert captured_requests[-1].url.path == "/Academic/Shared/GetStdAttPer"
        assert captured_requests[-1].url.params.get("studentId") == "std_param_test"
        assert captured_requests[-1].url.params.get("semId") == "99"
        assert captured_requests[-1].headers.get("x-requested-with") == "XMLHttpRequest"
        assert "/Student/Dashboard" in captured_requests[-1].headers.get("referer", "")

    @pytest.mark.asyncio
    async def test_get_attendance_redirect_raises_session_error(self):
        """Verify that a 302 redirect on GetStdAttPer raises DoctusSessionError with redirect location."""
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    text='<input name="__RequestVerificationToken" type="hidden" value="tok" />',
                )
            if request.method == "POST" and request.url.path == "/Login":
                return httpx.Response(
                    200,
                    json={"Status": 1, "Data": "/Student/Dashboard"},
                )
            if request.method == "GET" and request.url.path == "/Academic/Shared/GetStdAttPer":
                return httpx.Response(
                    302,
                    headers={"Location": "https://automation.vnrvjiet.ac.in/Login?ReturnUrl=%2F"},
                )
            return httpx.Response(404)

        adapter = DoctusAdapter()
        adapter._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=adapter.BASE_URL,
            follow_redirects=False,
        )

        await adapter.login("25071a6231", "pass")
        with pytest.raises(DoctusSessionError, match="redirected"):
            await adapter.get_attendance("3")

