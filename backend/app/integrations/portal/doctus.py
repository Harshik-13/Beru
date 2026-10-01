"""
Doctus portal adapter.

Provides authenticated HTTP access to the Doctus college portal
for attendance retrieval. Handles login, session management,
and attendance data retrieval.
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

logger = logging.getLogger(__name__)

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

    BROWSER_USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._session = None

    async def __aenter__(self) -> "DoctusAdapter":
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={
                "User-Agent": self.BROWSER_USER_AGENT,
                "Accept-Language": "en-US,en;q=0.9",
            },
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
            "xUsername": roll_number.strip(),
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

        # Retain authenticated navigation/landing path if returned in Data
        if isinstance(data.get("Data"), str) and data["Data"].startswith("/"):
            self._dashboard_path = data["Data"]

        # Extract protected student ID from login response dictionary if present;
        # otherwise fall back to normalized roll number (never treat redirect URLs as ID)
        protected_student_id = self._extract_protected_student_id_from_response(data)
        if not protected_student_id:
            protected_student_id = roll_number.strip().upper()

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

        Checks known keys if Data is a dictionary. Never treats redirect URLs as student IDs.
        """
        data_obj = data.get("Data")
        if isinstance(data_obj, dict):
            for key in ["UserId", "StudentId", "ProtectedStudentId", "ProtectedId", "id"]:
                val = data_obj.get(key)
                if val is not None and str(val).strip():
                    candidate = str(val).strip()
                    if not candidate.startswith("/"):
                        return candidate
        return ""

    def _extract_protected_student_id_from_html(self, html: str) -> str:
        """
        Extract internal student ID (StdId / StudentId) from authenticated dashboard/attendance HTML.

        Supports standard and reversed attribute ordering (name/id and value) and known JavaScript variables.
        Validates that extracted candidate is non-empty, non-generic, and not a path.
        """
        # 1. Check HTML input elements: name/id before value
        match = re.search(
            r'<input\b[^>]*?\b(?:name|id)=["\'](?:StdId|StudentId|student_id)["\'][^>]*?\bvalue=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if not match:
            # Check HTML input elements: value before name/id
            match = re.search(
                r'<input\b[^>]*?\bvalue=["\']([^"\']+)["\'][^>]*?\b(?:name|id)=["\'](?:StdId|StudentId|student_id)["\']',
                html,
                re.IGNORECASE,
            )
        if match and match.group(1).strip():
            candidate = match.group(1).strip()
            if candidate and not candidate.startswith("/"):
                return candidate

        # 2. Check JavaScript variables: e.g. var stdId = "..." or studentId = "..."
        js_match = re.search(
            r'\b(?:var|let|const)?\s*(?:stdId|studentId|student_id)\s*[:=]\s*["\']([^"\']+)["\']',
            html,
            re.IGNORECASE,
        )
        if js_match and js_match.group(1).strip():
            candidate = js_match.group(1).strip()
            if candidate and not candidate.startswith("/"):
                return candidate

        return ""

    async def get_semesters(self):
        """
        Retrieve available semester options.

        Requests the post-login landing route (/Student/Dashboard) with fallback to legacy
        /Academic/Student/Attendance, extracts internal student ID from HTML if present,
        and parses semester options.

        Returns:
            List of SemesterOption objects
        """
        if not self._session:
            raise DoctusSessionError("Not authenticated. Call login() first.")

        if not self._client:
            raise RuntimeError("Client not initialized")

        target_url = getattr(self, "_dashboard_path", None) or "/Student/Dashboard"
        doc_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Referer": f"{self.BASE_URL}{self.LOGIN_ENDPOINT}",
        }
        try:
            response = await self._client.get(
                target_url,
                cookies=self._session.cookies,
                headers=doc_headers,
            )
            # If landing route returned 404 and was not already the legacy path, attempt legacy fallback
            if response.status_code == 404 and target_url != "/Academic/Student/Attendance":
                response = await self._client.get(
                    "/Academic/Student/Attendance",
                    cookies=self._session.cookies,
                    headers=doc_headers,
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

        # Attempt to extract actual internal student ID from the dashboard HTML to enrich session
        extracted_id = self._extract_protected_student_id_from_html(response.text)
        if extracted_id and extracted_id != self._session.protected_student_id:
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

        ajax_headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{self.BASE_URL}/Student/Dashboard",
        }

        try:
            response = await self._client.get(
                url,
                cookies=self._session.cookies,
                headers=ajax_headers,
            )
        except httpx.TimeoutException as e:
            raise DoctusAdapterError("Attendance request timed out") from e
        except httpx.RequestError as e:
            raise DoctusAdapterError(f"Attendance request failed: {e}") from e

        logger.info(
            "GetStdAttPer response status: %s, content-type: %s, url: %s",
            response.status_code,
            response.headers.get("content-type"),
            response.url,
        )

        # Detect redirects indicating unauthenticated session challenge
        if response.history and any(
            r.status_code in (301, 302, 303, 307, 308) for r in response.history
        ):
            first_redirect = response.history[0]
            loc = first_redirect.headers.get("location", str(response.url))
            logger.warning(
                "GetStdAttPer request was redirected (status %s) to %s (final url: %s)",
                first_redirect.status_code,
                loc,
                response.url,
            )
            raise DoctusSessionError(
                f"College portal session was redirected to {loc}; checking authentication."
            )

        if response.status_code in (301, 302, 303, 307, 308):
            loc = response.headers.get("location", "/")
            logger.warning(
                "GetStdAttPer received direct redirect %s to %s",
                response.status_code,
                loc,
            )
            raise DoctusSessionError(
                f"College portal session was redirected to {loc}; checking authentication."
            )

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

        logger.info(
            "GetStdAttPer JSON response Status: %s, keys: %s",
            data.get("Status"),
            list(data.keys()) if isinstance(data, dict) else [],
        )

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
