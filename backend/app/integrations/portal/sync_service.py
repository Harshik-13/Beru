"""
Portal sync service.

Orchestrates the complete flow of syncing attendance data from the
Doctus portal into Beru's attendance domain.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import keyed_lock_manager
from app.integrations.portal.credential_store import (
    FernetCredentialConfig,
    FernetCredentialStore,
)
from app.integrations.portal.doctus import (
    DoctusAdapter,
    DoctusAdapterError,
    DoctusLoginError,
    DoctusSessionError,
)
from app.models.attendance import AttendanceProvenance
from app.models.portal_credential import PortalCredentialStatus

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.integrations.portal.dto import PortalAttendance
    from app.models.attendance import AttendanceSnapshot, SubjectAttendance
    from app.repositories.attendance import (
        AttendanceSnapshotRepository,
        SubjectAttendanceRepository,
    )
    from app.repositories.portal_credential import PortalCredentialRepository
else:
    from app.models.attendance import AttendanceSnapshot, SubjectAttendance
    from app.repositories.attendance import (
        AttendanceSnapshotRepository,
        SubjectAttendanceRepository,
    )
    from app.repositories.portal_credential import PortalCredentialRepository


class PortalSyncError(Exception):
    """Base exception for portal sync errors."""

    pass


class PortalCredentialsMissingError(PortalSyncError):
    """Raised when portal credentials are not configured for the student."""

    pass


class PortalLoginError(PortalSyncError):
    """Raised when portal login fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class PortalSessionError(PortalSyncError):
    """Raised when portal session is invalid or expired."""

    pass


class SemesterNotFoundError(PortalSyncError):
    """Raised when semester cannot be determined."""

    pass


@dataclass(frozen=True, slots=True)
class PortalSyncResult:
    """Result of a portal sync operation."""

    success: bool
    snapshot_id: str | None = None
    captured_at: str | None = None
    overall_percentage: float | None = None
    subject_count: int = 0
    message: str | None = None


@dataclass(frozen=True, slots=True)
class PortalSyncConfig:
    """Configuration for portal sync."""

    portal_base_url: str = "https://automation.vnrvjiet.ac.in"
    portal_name: str = "doctus"


class PortalSyncService:
    """
    Service for syncing attendance data from the Doctus portal.

    Orchestrates:
    - Credential retrieval and decryption
    - Portal authentication
    - Semester selection
    - Attendance data retrieval and parsing
    - Persistence as verified attendance snapshots
    """

    def __init__(
        self,
        session: AsyncSession,
        config: PortalSyncConfig | None = None,
    ):
        self.session = session
        self.config = config or PortalSyncConfig()
        self._credential_store: FernetCredentialStore | None = None
        self._credential_repo: PortalCredentialRepository | None = None
        self._snapshot_repo: AttendanceSnapshotRepository | None = None
        self._subject_repo: SubjectAttendanceRepository | None = None

    @property
    def credential_store(self) -> FernetCredentialStore:
        if self._credential_store is None:
            from app.core.config import settings

            config = FernetCredentialConfig.from_settings(
                settings.portal_credential_encryption_key
            )
            self._credential_store = FernetCredentialStore(self.session, config)
        return self._credential_store

    @property
    def credential_repo(self) -> "PortalCredentialRepository":
        if self._credential_repo is None:
            self._credential_repo = PortalCredentialRepository(self.session)
        return self._credential_repo

    @property
    def snapshot_repo(self) -> AttendanceSnapshotRepository:
        if self._snapshot_repo is None:
            self._snapshot_repo = AttendanceSnapshotRepository(self.session)
        return self._snapshot_repo

    @property
    def subject_repo(self) -> SubjectAttendanceRepository:
        if self._subject_repo is None:
            self._subject_repo = SubjectAttendanceRepository(self.session)
        return self._subject_repo

    FRESHNESS_TTL = timedelta(hours=4)

    def is_snapshot_fresh(self, snapshot: AttendanceSnapshot | None) -> bool:
        """Check if an attendance snapshot is less than 4 hours old."""
        if not snapshot or not snapshot.captured_at:
            return False
        age = datetime.now(UTC) - snapshot.captured_at
        return age < self.FRESHNESS_TTL

    async def get_or_sync_attendance(
        self,
        student_id: UUID,
        force_sync: bool = False,
        semester_id: str | None = None,
    ) -> tuple[AttendanceSnapshot | None, AttendanceProvenance, str | None]:
        """
        Retrieve fresh attendance data for a student, syncing from Doctus if stale.

        Enforces:
        - 4-hour freshness TTL
        - Async keyed locking to prevent concurrent duplicate syncs
        - Graceful fallback to cached snapshot if live sync fails
        - Zero fabrication if no data is available
        """
        # 1. Fast-path check without acquiring lock
        latest_snapshot = await self.snapshot_repo.get_latest_for_student_with_subjects(student_id)
        if not force_sync and self.is_snapshot_fresh(latest_snapshot):
            return latest_snapshot, AttendanceProvenance.PORTAL_SNAPSHOT_FRESH, None

        # 2. Acquire keyed lock to prevent thundering herd
        async with keyed_lock_manager.lock(f"portal_sync:{student_id}"):
            # Re-check under lock
            latest_snapshot = await self.snapshot_repo.get_latest_for_student_with_subjects(student_id)
            if not force_sync and self.is_snapshot_fresh(latest_snapshot):
                return latest_snapshot, AttendanceProvenance.PORTAL_SNAPSHOT_FRESH, None

            # Verify credentials exist
            credential = await self.credential_repo.get_by_student_and_portal(student_id, "doctus")
            if not credential:
                if latest_snapshot:
                    return (
                        latest_snapshot,
                        AttendanceProvenance.PORTAL_SNAPSHOT_STALE,
                        "No portal credentials configured. Showing cached snapshot.",
                    )
                return (
                    None,
                    AttendanceProvenance.PORTAL_SNAPSHOT_STALE,
                    "No portal credentials configured. Please connect your college portal.",
                )

            if credential.status == PortalCredentialStatus.RECONNECT_REQUIRED:
                if latest_snapshot:
                    return (
                        latest_snapshot,
                        AttendanceProvenance.PORTAL_SNAPSHOT_STALE,
                        "Portal credentials require reconnection. Showing cached snapshot.",
                    )
                return (
                    None,
                    AttendanceProvenance.PORTAL_SNAPSHOT_STALE,
                    "Portal credentials require reconnection. Please connect your college portal.",
                )

            # Attempt live sync
            try:
                await self.sync_attendance(student_id, semester_id)
                refreshed = await self.snapshot_repo.get_latest_for_student_with_subjects(student_id)
                return refreshed, AttendanceProvenance.PORTAL_LIVE_SYNC, None
            except DoctusLoginError as e:
                logger.warning(
                    "Portal authentication failed during sync for student %s: %s",
                    student_id,
                    e,
                )
                if latest_snapshot:
                    return (
                        latest_snapshot,
                        AttendanceProvenance.PORTAL_SNAPSHOT_STALE,
                        "Portal login failed. Please reconnect credentials.",
                    )
                return (
                    None,
                    AttendanceProvenance.PORTAL_SNAPSHOT_STALE,
                    "Portal login failed. Please reconnect credentials.",
                )
            except Exception as e:
                logger.warning("Portal sync failed for student %s: %s", student_id, e)
                if latest_snapshot:
                    return (
                        latest_snapshot,
                        AttendanceProvenance.PORTAL_SNAPSHOT_STALE,
                        f"Live portal refresh unavailable: {e}",
                    )
                return (
                    None,
                    AttendanceProvenance.PORTAL_SNAPSHOT_STALE,
                    f"Live portal refresh unavailable: {e}",
                )

    async def sync_attendance(
        self,
        student_id: UUID,
        semester_id: str | None = None,
    ) -> "PortalSyncResult":
        """
        Sync attendance data from the portal for a student.

        Args:
            student_id: The authenticated student's ID
            semester_id: Optional specific semester to sync. If None,
                         attempts to use the most recent available semester.

        Returns:
            PortalSyncResult with sync status and metadata

        Raises:
            PortalCredentialsMissingError: No stored credentials for the student
            PortalLoginError: Portal authentication failed
            PortalSyncError: Sync failed for any other reason
        """
        # Step 1: Retrieve and decrypt portal credentials
        credential = await self.credential_repo.get_by_student_and_portal(
            student_id, "doctus"
        )
        if not credential:
            raise PortalCredentialsMissingError(
                "No portal credentials configured. Please configure your "
                "portal credentials in settings."
            )

        _roll_number, password = await self.credential_store.get_credential(
            student_id, "doctus"
        )
        if not credential.roll_number or not password:
            raise PortalCredentialsMissingError(
                "Portal credentials not configured correctly."
            )

        # Step 2: Create Doctus adapter and authenticate
        async with DoctusAdapter() as adapter:
            try:
                await adapter.login(credential.roll_number, password)
            except DoctusLoginError as e:
                await self.credential_repo.update_status(
                    credential.id,
                    PortalCredentialStatus.RECONNECT_REQUIRED,
                    failure=True,
                )
                await self.session.commit()
                raise PortalLoginError(
                    f"Portal login failed: {e}", status_code=e.status_code
                ) from e
            except DoctusAdapterError as e:
                raise PortalSyncError(f"Portal communication error: {e}") from e

            # Step 3: Get available semesters
            try:
                semesters = await adapter.get_semesters()
            except Exception as e:
                raise PortalSyncError(f"Failed to retrieve semesters: {e}") from e

            if not semesters:
                raise PortalSyncError("No semesters available from portal")

            # Step 4: Determine and validate which semester to use
            available_sem_ids = {s.semester_id for s in semesters}
            default_sem = next((s for s in semesters if s.is_selected), semesters[0])
            target_semester_id = semester_id
            if target_semester_id:
                if target_semester_id not in available_sem_ids:
                    logger.warning(
                        "Requested semester %s not found in student's discovered semesters %s. Falling back to default %s.",
                        target_semester_id,
                        available_sem_ids,
                        default_sem.semester_id,
                    )
                    target_semester_id = default_sem.semester_id
            else:
                # Use the default active semester (marked selected, or first in list)
                target_semester_id = default_sem.semester_id

            # Step 5: Fetch attendance data adhering strictly to canonical PortalAttendance contract
            try:
                attendance = await adapter.get_attendance(target_semester_id)
            except DoctusSessionError:
                raise PortalSyncError(
                    "Portal session expired or invalid during attendance fetch"
                ) from None
            except DoctusAdapterError as e:
                raise PortalSyncError(f"Attendance fetch failed: {e}") from e

            # Step 6: Persist attendance data
            snapshot = await self._persist_attendance(
                student_id=student_id,
                attendance=attendance,
                semester_id=target_semester_id,
            )

            now = datetime.now(UTC)
            await self.credential_repo.update_sync_timestamp(credential.id, now)
            await self.credential_repo.update_status(
                credential.id,
                PortalCredentialStatus.CONNECTED,
                failure=False,
            )
            await self.session.commit()

            return PortalSyncResult(
                success=True,
                snapshot_id=str(snapshot.id),
                captured_at=snapshot.captured_at.isoformat(),
                overall_percentage=snapshot.overall_percentage(),
                subject_count=len(snapshot.subjects),
                message="Attendance synced successfully",
            )

    async def _persist_attendance(
        self,
        student_id: UUID,
        attendance: "PortalAttendance",
        semester_id: str,
    ):
        """
        Persist attendance data as a new snapshot with subject records.

        This creates an immutable snapshot that preserves the exact
        state of attendance at the time of sync.
        """
        # Create the snapshot
        snapshot = AttendanceSnapshot(
            student_id=student_id,
            source="doctus",
            captured_at=datetime.now(UTC),
            semester_id=attendance.semester_id or semester_id,
            overall_attended=attendance.overall_attended,
            overall_conducted=attendance.overall_conducted,
        )
        await self.snapshot_repo.create(snapshot)

        # Create subject attendance records
        subject_records = []
        for subject in attendance.subjects:
            subject_record = SubjectAttendance(
                snapshot_id=snapshot.id,
                subject_code=subject.subject_code,
                subject_name=subject.subject_name,
                monthly_period=subject.monthly_period,
                monthly_attended=subject.monthly_attended,
                monthly_conducted=subject.monthly_conducted,
                cumulative_attended=subject.cumulative_attended,
                cumulative_conducted=subject.cumulative_conducted,
            )
            subject_records.append(subject_record)

        if subject_records:
            await self.subject_repo.create_batch(subject_records)

        # Refresh to load subjects relationship
        await self.session.refresh(snapshot)
        return snapshot


def create_portal_sync_service(session: AsyncSession) -> PortalSyncService:
    """Factory function to create a portal sync service."""
    return PortalSyncService(session)
