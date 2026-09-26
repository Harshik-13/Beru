"""
Doctus portal adapter.

Provides authenticated HTTP access to the Doctus college portal
for attendance retrieval. Handles login, session management,
and attendance data retrieval.
"""

from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.integrations.portal.dto import (
    PortalAttendance,
)
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
        self._session: DoctusSession | None = None

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

        # Extract protected student ID from response or subsequent page
        # The protected student ID is typically embedded in the dashboard HTML
        # For now, we'll extract it when needed for attendance requests
        session = DoctusSession(
            cookies=cookies,
            protected_student_id="",  # Will be populated on first attendance request
        )

        self._session = session
        return session

    async def get_semesters(self) -> list:
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

        # Parse semester options from the page
        try:
            semesters = DoctusParser.parse_semester_options(response.text)
        except DoctusParserError as e:
            raise DoctusParseError("Failed to parse semesters", e) from e

        return semesters

    async def get_attendance(self, semester_id: str) -> tuple[PortalAttendance, str]:
        """
        Retrieve attendance data for a specific semester.

        Args:
            semester_id: The semester identifier from get_semesters()

        Returns:
            Tuple of (PortalAttendance, protected_student_id)
        """
        if not self._session:
            raise DoctusSessionError("Not authenticated. Call login() first.")

        if not self._client:
            raise RuntimeError("Client not initialized")

        # Build attendance request URL
        url = f"{self.ATTENDANCE_ENDPOINT}?semId={semester_id}"

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

        # Extract protected student ID from cookies if not already set
        protected_student_id = self._extract_protected_student_id()

        # Parse attendance HTML
        try:
            attendance = DoctusParser.parse_attendance(html, semester_id)
            attendance.semester_id = semester_id
        except DoctusParserError as e:
            raise DoctusParseError("Failed to parse attendance", e) from e

        return attendance, protected_student_id

    def _extract_protected_student_id(self) -> str:
        """
        Extract the protected student ID from the session.

        The protected ID is typically embedded in the page HTML or
        available via an API endpoint. For now, we extract from cookies
        or return a placeholder.
        """
        if not self._session:
            return ""

        # The protected student ID might be in a cookie or need to be
        # fetched from a profile endpoint. For now, return empty string
        # and let the parser handle the data without it.
        return self._session.protected_student_id

    @property
    def is_authenticated(self) -> bool:
        """Check if currently authenticated."""
        return self._session is not None
