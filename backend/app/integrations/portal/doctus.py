"""
Doctus portal adapter.

Provides authenticated HTTP access to the Doctus college portal
for attendance retrieval. Handles login, session management,
and attendance data retrieval.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    pass
else:
    pass

from app.core.config import settings
from app.integrations.portal.parser import DoctusParser, DoctusParserError


class DoctusAdapterError(Exception):
    """Base exception for Doctus adapter errors."""

    pass


class DoctusLoginError(DoctusAdapterError):
    """Raised when login fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class DoctusSessionError(DoctusAdapterError):
    """Raised when session is invalid or expired."""

    pass


class DoctusParseError(DoctusAdapterError):
    """Raised when HTML parsing fails."""

    def __init__(self, message: str, original: Exception | None = None):
        super().__init__(message)
        self.original = original


@dataclass(frozen=True, slots=True)
class DoctusSession:
    """Authenticated Doctus session."""

    cookies: httpx.Cookies
    protected_student_id: str


class DoctusAdapter:
    """
    Doctus portal adapter for attendance retrieval.

    Handles:
    - Login with roll number and password
    - Session cookie management
    - Semester option retrieval
    - Attendance data retrieval and parsing
    """

    BASE_URL = settings.portal_base_url.rstrip("/")
    LOGIN_ENDPOINT = "/Login"
    ATTENDANCE_ENDPOINT = "/Academic/Shared/GetStdAttPer"

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._session = None

    async def __aenter__(self) -> "DoctusAdapter":
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def login(self, roll_number: str, password: str) -> DoctusSession:
        """
        Authenticate with Doctus portal.

        Args:
            roll_number: Student's roll number
            password: Portal password

        Returns:
            DoctusSession with cookies and protected student ID

        Raises:
            DoctusLoginError: If authentication fails
        """
        if not self._client:
            raise RuntimeError("Adapter not initialized. Use async context manager.")

        # Prepare login payload
        # Doctus expects form data
        payload = {
            "UserName": roll_number,
            "Password": password,
        }

        try:
            response = await self._client.post(
                self.LOGIN_ENDPOINT,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
        except httpx.TimeoutException as e:
            raise DoctusLoginError("Login request timed out") from e
        except httpx.RequestError as e:
            raise DoctusLoginError(f"Login request failed: {e}") from e

        if response.status_code != 200:
            raise DoctusLoginError(
                f"Login failed with status {response.status_code}",
                status_code=response.status_code,
            )

        # Parse login response
        try:
            data = response.json()
        except ValueError as e:
            raise DoctusLoginError("Invalid login response format") from e

        if data.get("Status") != 1:
            msg = data.get("Data", {}).get("xMessage", "Unknown error")
            raise DoctusLoginError(f"Login failed: {msg}")

        # Extract session cookie
        cookies = response.cookies
        relic_cookie = cookies.get("relic_VNRVJIET")
        if not relic_cookie:
            raise DoctusLoginError("Session cookie not set after login")

        # Extract protected student ID from the login response if available
        # The protected student ID is often embedded in the login response
        protected_student_id = self._extract_protected_student_id_from_response(data)

        session = DoctusSession(
            cookies=cookies,
            protected_student_id=protected_student_id,
        )

        self._session = session
        return session

    def _extract_protected_student_id_from_response(self, data: dict) -> str:
        """
        Extract protected student ID from login response.

        The protected student ID may be embedded in the login response
        under various keys depending on the portal version.
        """
        # Check common locations in the login response
        data_obj = data.get("Data", {})
        if isinstance(data_obj, dict):
            # Check common field names for the protected student ID
            for key in ["StudentId", "ProtectedStudentId", "UserId", "ProtectedId"]:
                if data_obj.get(key):
                    return str(data_obj[key])
        return ""

    async def get_semesters(self):
        """
        Retrieve available semester options.

        Returns:
            List of SemesterOption objects
        """
        if not self._session:
            raise DoctusSessionError("Not authenticated. Call login() first.")

        if not self._client:
            raise RuntimeError("Client not initialized")

        try:
            # The semesters are typically embedded in the attendance page
            # We need to fetch the attendance page first
            response = await self._client.get(
                "/Academic/Student/Attendance",
                cookies=self._session.cookies,
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        except httpx.TimeoutException as e:
            raise DoctusAdapterError("Semester request timed out") from e
        except httpx.RequestError as e:
            raise DoctusAdapterError(f"Semester request failed: {e}") from e

        if response.status_code == 401:
            raise DoctusSessionError("Session expired or invalid")
        if response.status_code != 200:
            raise DoctusAdapterError(
                f"Semester request failed with status {response.status_code}"
            )

        # Extract protected student ID from the attendance page HTML
        if not self._session.protected_student_id:
            extracted_id = self._extract_protected_student_id_from_html(response.text)
            if extracted_id:
                self._session = DoctusSession(
                    cookies=self._session.cookies,
                    protected_student_id=extracted_id,
                )

        # Parse semester options from the page
        try:
            semesters = DoctusParser.parse_semester_options(response.text)
        except DoctusParserError as e:
            raise DoctusParseError("Failed to parse semesters", e) from e

        return semesters

    async def get_attendance(self, semester_id: str):
        """
        Retrieve attendance data for a specific semester.

        Args:
            semester_id: The semester identifier from get_semesters()

        Returns:
            PortalAttendance object
        """
        if not self._session:
            raise DoctusSessionError("Not authenticated. Call login() first.")

        if not self._client:
            raise RuntimeError("Client not initialized")

        # Build attendance request URL with protected student ID
        protected_student_id = self._extract_protected_student_id()
        if not protected_student_id:
            # Try to extract from the last fetched page (semester page)
            if not self._session.protected_student_id:
                # We need to fetch a page to extract it
                raise DoctusSessionError(
                    "Protected student ID not available. Call get_semesters() first."
                )
            protected_student_id = self._session.protected_student_id

        # Build attendance request URL with protected student ID
        url = (
            f"{self.ATTENDANCE_ENDPOINT}?"
            f"studentId={protected_student_id}&semId={semester_id}"
        )

        try:
            response = await self._client.get(
                url,
                cookies=self._session.cookies,
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        except httpx.TimeoutException as e:
            raise DoctusAdapterError("Attendance request timed out") from e
        except httpx.RequestError as e:
            raise DoctusAdapterError(f"Attendance request failed: {e}") from e

        if response.status_code == 401:
            raise DoctusSessionError("Session expired or invalid")
        if response.status_code != 200:
            raise DoctusAdapterError(
                f"Attendance request failed with status {response.status_code}"
            )

        # Parse JSON response
        try:
            data = response.json()
        except ValueError as e:
            raise DoctusAdapterError("Invalid attendance response format") from e

        if data.get("Status") != 1:
            raise DoctusAdapterError(
                f"Attendance API returned error: {data.get('Data', 'Unknown error')}"
            )

        html = data.get("Data", "")
        if not html:
            raise DoctusAdapterError("Empty attendance data")

        # Parse attendance HTML
        try:
            attendance = DoctusParser.parse_attendance(html, semester_id)
            attendance.semester_id = semester_id
        except DoctusParserError as e:
            raise DoctusParseError("Failed to parse attendance", e) from e

        return attendance

    def _extract_protected_student_id(self) -> str:
        """
        Extract the protected student ID from the session.

        Returns the already-extracted ID.
        """
        if not self._session:
            return ""

        return self._session.protected_student_id
