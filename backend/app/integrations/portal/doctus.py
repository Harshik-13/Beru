"""
Doctus portal adapter.

Provides authenticated HTTP access to the Doctus college portal
for attendance retrieval. Handles login, session management,
and attendance data retrieval.
"""

import re
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


def _extract_antiforgery_token(html: str) -> str:
    """
    Extract anti-forgery token from GET /Login HTML.

    Accepts arbitrary attribute ordering and casing. Never logs or leaks the token.
    """
    match = re.search(
        r'<input\b[^>]*?\bname=["\']__RequestVerificationToken["\'][^>]*?\bvalue=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r'<input\b[^>]*?\bvalue=["\']([^"\']+)["\'][^>]*?\bname=["\']__RequestVerificationToken["\']',
            html,
            re.IGNORECASE,
        )
    if match and match.group(1).strip():
        return match.group(1).strip()
    return ""


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

        Performs two-step authentication:
        1. GET /Login to obtain anti-forgery cookie and __RequestVerificationToken.
        2. POST /Login with xPassword and token headers.

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

        # Step 1: Pre-flight GET /Login to acquire anti-forgery token & cookie
        try:
            get_response = await self._client.get(
                self.LOGIN_ENDPOINT,
                headers={"Referer": f"{self.BASE_URL}/"},
            )
        except httpx.TimeoutException as e:
            raise DoctusLoginError("Portal connection timed out during pre-flight") from e
        except httpx.RequestError as e:
            raise DoctusLoginError(f"Portal unavailable during pre-flight: {e}") from e

        if get_response.status_code != 200:
            raise DoctusLoginError(
                f"Portal returned status {get_response.status_code} during pre-flight",
                status_code=get_response.status_code,
            )

        token = _extract_antiforgery_token(get_response.text)
        if not token:
            raise DoctusLoginError("Failed to acquire anti-forgery token from portal")

        # Step 2: Form POST /Login
        payload = {
            "__RequestVerificationToken": token,
            "UserName": roll_number.strip(),
            "xPassword": password,
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
            "RequestVerificationToken": token,
            "Referer": f"{self.BASE_URL}{self.LOGIN_ENDPOINT}",
        }

        try:
            post_response = await self._client.post(
                self.LOGIN_ENDPOINT,
                data=payload,
                headers=headers,
            )
        except httpx.TimeoutException as e:
            raise DoctusLoginError("Login request timed out") from e
        except httpx.RequestError as e:
            raise DoctusLoginError(f"Login request failed: {e}") from e

        # Handle specific HTTP error status codes safely without exposing raw payload/body
        if post_response.status_code == 400:
            raise DoctusLoginError(
                "Portal rejected authentication request (HTTP 400)",
                status_code=400,
            )
        if post_response.status_code >= 500:
            raise DoctusLoginError(
                f"Portal server error (HTTP {post_response.status_code})",
                status_code=post_response.status_code,
            )
        if post_response.status_code != 200:
            raise DoctusLoginError(
                f"Login failed with status {post_response.status_code}",
                status_code=post_response.status_code,
            )

        # Parse login response JSON
        try:
            data = post_response.json()
        except ValueError as e:
            raise DoctusLoginError("Invalid portal response format") from e

        if not isinstance(data, dict):
            raise DoctusLoginError("Invalid portal response format")

        # Check authentication status
        if data.get("Status") != 1:
            data_obj = data.get("Data")
            error_msg = "Invalid username or password."
            if isinstance(data_obj, dict):
                blocked_until = data_obj.get("BlockedUntil")
                raw_msg = data_obj.get("Message") or data_obj.get("xMessage")
                if blocked_until:
                    error_msg = f"Account temporarily blocked until {blocked_until}."
                elif raw_msg and isinstance(raw_msg, str):
                    error_msg = raw_msg.strip()
            raise DoctusLoginError(f"Login failed: {error_msg}")

        # Extract protected student ID from login response
        protected_student_id = self._extract_protected_student_id_from_response(data)
        if not protected_student_id:
            raise DoctusLoginError(
                "Authentication succeeded but failed to extract student identifier"
            )

        # Build session using authoritative self._client.cookies
        session = DoctusSession(
            cookies=self._client.cookies,
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
        data_obj = data.get("Data", {})
        if isinstance(data_obj, dict):
            for key in ["UserId", "StudentId", "ProtectedStudentId", "ProtectedId"]:
                val = data_obj.get(key)
                if val is not None and str(val).strip():
                    return str(val).strip()
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
