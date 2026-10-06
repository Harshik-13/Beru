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
from app.integrations.portal.dto import PortalAttendance, SemesterOption
from app.integrations.portal.parser import DoctusParser, DoctusParserError


class DoctusAdapterError(Exception):
    """Base exception for Doctus adapter errors."""

    pass


class DoctusLoginError(DoctusAdapterError):
    """Raised when login fails.

    Distinguishes between genuine credential rejection (e.g. invalid password,
    account locked) and transient server/infrastructure issues (e.g. HTTP 503,
    pre-flight failures, timeouts).
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        is_credential_rejection: bool | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        if is_credential_rejection is not None:
            self.is_credential_rejection = is_credential_rejection
        else:
            # Server errors (5xx) or pre-flight / network issues are not credential rejections
            if status_code is not None and status_code >= 500:
                self.is_credential_rejection = False
            elif any(
                s in message.lower()
                for s in ("pre-flight", "timeout", "unavailable", "server error", "format")
            ):
                self.is_credential_rejection = False
            else:
                self.is_credential_rejection = True


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
    APP_ENDPOINT = "/App"
    STDINFO_WIDGET_ENDPOINT = "/Shared/Widget/STDINFO"
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
            raise DoctusLoginError(
                f"Login failed: {error_msg}",
                status_code=200,
                is_credential_rejection=True,
            )

        self._roll_number = roll_number.strip().upper()

        # Retain authenticated navigation/landing path if returned in Data
        if isinstance(data.get("Data"), str) and data["Data"].startswith("/"):
            self._dashboard_path = data["Data"]

        # Extract protected student ID from login response dictionary if present;
        # otherwise leave empty to discover in-memory from STDINFO
        protected_student_id = self._extract_protected_student_id_from_response(data)

        # Build session using authoritative self._client.cookies
        session = DoctusSession(
            cookies=self._client.cookies,
            protected_student_id=protected_student_id,
        )

        logger.info(
            "Login successful. Session cookies established: %s",
            list(self._client.cookies.keys()),
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

    @staticmethod
    def _extract_protected_student_id_from_stdinfo(text: str) -> str:
        """
        Extract protected student ID embedded in STDINFO widget JavaScript.

        Matches function popAtt pattern: Academic/Shared/GetStdAttPer?studentId=<PROTECTED_ID>&semId=
        """
        match = re.search(
            r'Academic/Shared/GetStdAttPer\?studentId=([a-zA-Z0-9_\-]+)',
            text,
            re.IGNORECASE,
        )
        if match and match.group(1).strip():
            return match.group(1).strip()
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

    def _check_redirect_and_raise(self, response: httpx.Response, endpoint_name: str) -> None:
        """
        Detect redirects indicating unauthenticated session challenge or redirect to login.
        Halts immediately without following redirect, preventing session cookie expiration.
        """
        if response.status_code in (301, 302, 303, 307, 308):
            loc = response.headers.get("location", "/")
            logger.warning(
                "%s received redirect (status %s) to %s",
                endpoint_name,
                response.status_code,
                loc,
            )
            raise DoctusSessionError(
                f"College portal session was redirected to {loc}; checking authentication."
            )
        if response.history and any(
            r.status_code in (301, 302, 303, 307, 308) for r in response.history
        ):
            first_redirect = response.history[0]
            loc = first_redirect.headers.get("location", str(response.url))
            logger.warning(
                "%s followed redirect (status %s) to %s",
                endpoint_name,
                first_redirect.status_code,
                loc,
            )
            raise DoctusSessionError(
                f"College portal session was redirected to {loc}; checking authentication."
            )

    async def get_app_workspace(self) -> str:
        """
        Request /App workspace to establish session context.
        Uses follow_redirects=False to prevent automated redirection to root.
        """
        if not self._session:
            raise DoctusSessionError("Not authenticated. Call login() first.")
        if not self._client:
            raise RuntimeError("Client not initialized")

        doc_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Referer": f"{self.BASE_URL}{self.LOGIN_ENDPOINT}",
        }
        try:
            response = await self._client.get(
                self.APP_ENDPOINT,
                headers=doc_headers,
                follow_redirects=False,
            )
        except httpx.TimeoutException as e:
            raise DoctusAdapterError("App workspace request timed out") from e
        except httpx.RequestError as e:
            raise DoctusAdapterError(f"App workspace request failed: {e}") from e

        self._check_redirect_and_raise(response, "AppWorkspace")

        if response.status_code == 401:
            raise DoctusSessionError("Session expired or invalid")
        if response.status_code != 200:
            raise DoctusAdapterError(
                f"App workspace request failed with status {response.status_code}"
            )

        return response.text

    async def get_stdinfo_widget(self) -> str:
        """
        Fetch the STDINFO widget from /Shared/Widget/STDINFO to obtain the protected student ID.
        Stores the extracted student ID in the in-memory DoctusSession for this sync lifecycle.
        """
        if not self._session:
            raise DoctusSessionError("Not authenticated. Call login() first.")
        if not self._client:
            raise RuntimeError("Client not initialized")

        # Establish /App context first if not yet requested
        if not getattr(self, "_app_visited", False):
            try:
                await self.get_app_workspace()
                self._app_visited = True
            except Exception as e:
                logger.debug("Visiting /App resulted in: %s", e)

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.BASE_URL}{self.APP_ENDPOINT}",
            "Accept": "text/html, */*; q=0.01",
        }
        try:
            response = await self._client.get(
                self.STDINFO_WIDGET_ENDPOINT,
                headers=headers,
                follow_redirects=False,
            )
        except httpx.TimeoutException as e:
            raise DoctusAdapterError("STDINFO widget request timed out") from e
        except httpx.RequestError as e:
            raise DoctusAdapterError(f"STDINFO widget request failed: {e}") from e

        self._check_redirect_and_raise(response, "STDINFO")

        if response.status_code == 401:
            raise DoctusSessionError("Session expired or invalid")
        if response.status_code != 200:
            raise DoctusAdapterError(
                f"STDINFO request failed with status {response.status_code}"
            )

        extracted_id = self._extract_protected_student_id_from_stdinfo(response.text)
        if not extracted_id:
            extracted_id = self._extract_protected_student_id_from_html(response.text)

        if extracted_id:
            self._session = DoctusSession(
                cookies=self._client.cookies,
                protected_student_id=extracted_id,
            )
            logger.info("Discovered protected student ID from STDINFO widget")
        else:
            logger.warning("Could not extract protected student ID from STDINFO widget")

        return extracted_id

    async def get_attendance_and_semesters(
        self,
        target_semester_id: str | None = None,
    ) -> tuple[PortalAttendance, list[SemesterOption]]:
        """
        Retrieve attendance data and discover semester options.

        First calls GetStdAttPer with semId=undefined (or target_semester_id if specified),
        which the portal accepts and returns the #StdSemPop options along with the attendance
        for the default selected semester.

        If target_semester_id is specified and differs from the discovered default selected
        semester, makes a second query specifically for that semester.
        """
        if not self._session:
            raise DoctusSessionError("Not authenticated. Call login() first.")
        if not self._client:
            raise RuntimeError("Client not initialized")

        # Discover protected student ID if not yet available in-memory
        protected_student_id = self._session.protected_student_id
        if not protected_student_id or protected_student_id == getattr(self, "_roll_number", ""):
            discovered = await self.get_stdinfo_widget()
            if discovered:
                protected_student_id = discovered

        if not protected_student_id:
            raise DoctusSessionError("Protected student ID not available from portal.")

        # Explicit sem_id parameter: 'undefined' for initial discovery/default
        if target_semester_id is None or target_semester_id.strip() == "":
            sem_id = "undefined"
        else:
            sem_id = target_semester_id.strip()

        attendance_url = f"{self.ATTENDANCE_ENDPOINT}?studentId={protected_student_id}&semId={sem_id}"
        ajax_headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{self.BASE_URL}{self.APP_ENDPOINT}",
        }

        try:
            response = await self._client.get(
                attendance_url,
                headers=ajax_headers,
                follow_redirects=False,
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

        self._check_redirect_and_raise(response, "GetStdAttPer")

        if response.status_code == 401:
            raise DoctusSessionError("Session expired or invalid")
        if response.status_code != 200:
            raise DoctusAdapterError(
                f"Attendance request failed with status {response.status_code}"
            )

        try:
            data = response.json()
        except ValueError as e:
            raise DoctusAdapterError("Invalid attendance response format") from e

        if not isinstance(data, dict) or data.get("Status") != 1:
            err_msg = data.get("Data", "Unknown error") if isinstance(data, dict) else "Unknown error"
            raise DoctusAdapterError(f"Attendance API returned error: {err_msg}")

        html = data.get("Data", "")
        if not html:
            raise DoctusAdapterError("Empty attendance data")

        # Parse semester options from the HTML
        semesters = DoctusParser.parse_semester_options(html)
        default_selected_sem = next((s for s in semesters if s.is_selected), None)
        selected_sem_id = default_selected_sem.semester_id if default_selected_sem else (
            semesters[0].semester_id if semesters else sem_id
        )

        # Parse attendance from HTML (resolving semester ID dynamically)
        attendance = DoctusParser.parse_attendance(
            html,
            semester_id=selected_sem_id if sem_id == "undefined" else sem_id,
        )

        # If user explicitly requested a specific semester that differs from default returned,
        # issue secondary request for that specific semester ID
        if sem_id != "undefined" and default_selected_sem and sem_id != default_selected_sem.semester_id:
            logger.info("Fetching explicitly requested non-default semester: %s", sem_id)
            specific_url = f"{self.ATTENDANCE_ENDPOINT}?studentId={protected_student_id}&semId={sem_id}"
            try:
                spec_response = await self._client.get(
                    specific_url,
                    headers=ajax_headers,
                    follow_redirects=False,
                )
            except Exception as e:
                raise DoctusAdapterError(f"Secondary attendance request failed: {e}") from e

            self._check_redirect_and_raise(spec_response, "GetStdAttPer(specific)")
            if spec_response.status_code == 200:
                spec_data = spec_response.json()
                if isinstance(spec_data, dict) and spec_data.get("Status") == 1:
                    spec_html = spec_data.get("Data", "")
                    if spec_html:
                        attendance = DoctusParser.parse_attendance(spec_html, semester_id=sem_id)

        return attendance, semesters

    async def get_semesters(self) -> list[SemesterOption]:
        """
        Retrieve available semester options.
        """
        _, semesters = await self.get_attendance_and_semesters()
        return semesters

    async def get_attendance(self, semester_id: str) -> PortalAttendance:
        """
        Retrieve attendance data for a specific semester.
        """
        attendance, _ = await self.get_attendance_and_semesters(target_semester_id=semester_id)
        return attendance

    def _extract_protected_student_id(self) -> str:
        """
        Extract the protected student ID from the session.
        """
        if not self._session:
            return ""

        return self._session.protected_student_id
