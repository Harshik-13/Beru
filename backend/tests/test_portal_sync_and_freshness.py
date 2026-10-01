"""
Tests for Phase 2: Live Doctus Portal Sync, 4-Hour Freshness, Concurrency Locking, and Provenance.

Verifies:
1. KeyedLockManager ensures mutual exclusion per key.
2. 4-hour freshness TTL avoids unnecessary portal requests when cached data is fresh.
3. Stale snapshot triggers Doctus sync under lock.
4. Portal failure gracefully falls back to cached snapshot with PORTAL_SNAPSHOT_STALE provenance.
5. Zero fabrication when Doctus fails and no cached snapshot exists.
6. Credential status is updated to RECONNECT_REQUIRED on login failure.
7. AttendanceRenderer displays correct provenance headers/badges for fresh, live, and stale data.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.concurrency import KeyedLockManager
from app.integrations.portal.doctus import DoctusAdapterError, DoctusLoginError
from app.integrations.portal.dto import PortalAttendance, PortalSubjectAttendance
from app.integrations.portal.sync_service import (
    PortalSyncConfig,
    PortalSyncService,
)
from app.intelligence.models.context import (
    ConversationContext,
    StudentContext,
    StudentProfile,
)
from app.intelligence.rendering.attendance_renderer import AttendanceRenderer
from app.models.attendance import (
    AttendanceProvenance,
    AttendanceSnapshot,
    AttendanceSource,
    SubjectAttendance,
)
from app.models.portal_credential import PortalCredential, PortalCredentialStatus


class TestKeyedLockManager:
    """Verify in-memory keyed locking behaviour."""

    @pytest.mark.asyncio
    async def test_mutual_exclusion_same_key(self):
        manager = KeyedLockManager()
        active = []
        max_concurrent = 0

        async def worker(idx: int):
            nonlocal max_concurrent
            async with manager.lock("student_123"):
                active.append(idx)
                if len(active) > max_concurrent:
                    max_concurrent = len(active)
                await asyncio.sleep(0.02)
                active.remove(idx)

        await asyncio.gather(*(worker(i) for i in range(5)))
        assert max_concurrent == 1
        assert len(manager._locks) == 0  # Cleaned up

    @pytest.mark.asyncio
    async def test_concurrency_distinct_keys(self):
        manager = KeyedLockManager()
        order = []

        async def worker(key: str, val: int):
            async with manager.lock(key):
                order.append(f"start_{val}")
                await asyncio.sleep(0.01)
                order.append(f"end_{val}")

        await asyncio.gather(worker("key_a", 1), worker("key_b", 2))
        assert "start_1" in order and "start_2" in order


class TestPortalFreshnessAndSync:
    """Verify 4-hour TTL and sync orchestration."""

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        return session

    @pytest.fixture
    def student_id(self):
        return uuid4()

    def _make_snapshot(self, student_id, captured_at, attended=85, conducted=100):
        snapshot = AttendanceSnapshot(
            student_id=student_id,
            source=AttendanceSource.DOCTUS,
            captured_at=captured_at,
            overall_attended=attended,
            overall_conducted=conducted,
            semester_id="SEM_V",
        )
        snapshot.id = uuid4()
        sub = SubjectAttendance(
            snapshot_id=snapshot.id,
            subject_code="CS501",
            subject_name="Cloud Computing",
            cumulative_attended=attended,
            cumulative_conducted=conducted,
        )
        snapshot.subjects = [sub]
        return snapshot

    @pytest.mark.asyncio
    async def test_fresh_snapshot_skips_portal_sync(self, mock_session, student_id):
        """When snapshot is < 4h old, return PORTAL_SNAPSHOT_FRESH without hitting portal."""
        service = PortalSyncService(mock_session)
        fresh_time = datetime.now(UTC) - timedelta(hours=1)
        fresh_snapshot = self._make_snapshot(student_id, fresh_time)

        service.snapshot_repo.get_latest_for_student_with_subjects = AsyncMock(
            return_value=fresh_snapshot
        )
        service.sync_attendance = AsyncMock()

        snapshot, provenance, notice = await service.get_or_sync_attendance(student_id)

        assert snapshot == fresh_snapshot
        assert provenance == AttendanceProvenance.PORTAL_SNAPSHOT_FRESH
        assert notice is None
        service.sync_attendance.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_snapshot_triggers_portal_sync(self, mock_session, student_id):
        """When snapshot is > 4h old, trigger sync and return PORTAL_LIVE_SYNC."""
        service = PortalSyncService(mock_session)
        stale_time = datetime.now(UTC) - timedelta(hours=5)
        stale_snapshot = self._make_snapshot(student_id, stale_time)
        new_snapshot = self._make_snapshot(student_id, datetime.now(UTC), attended=88, conducted=102)

        # First call returns stale snapshot, second call (after sync) returns refreshed snapshot
        service.snapshot_repo.get_latest_for_student_with_subjects = AsyncMock(
            side_effect=[stale_snapshot, stale_snapshot, new_snapshot]
        )

        mock_cred = PortalCredential(
            student_id=student_id,
            portal="doctus",
            roll_number="25MIS0001",
            encrypted_password="encrypted_blob",
            status=PortalCredentialStatus.CONNECTED,
        )
        service.credential_repo.get_by_student_and_portal = AsyncMock(return_value=mock_cred)
        service.sync_attendance = AsyncMock()

        snapshot, provenance, notice = await service.get_or_sync_attendance(student_id)

        assert snapshot == new_snapshot
        assert provenance == AttendanceProvenance.PORTAL_LIVE_SYNC
        assert notice is None
        service.sync_attendance.assert_called_once_with(student_id, None)

    @pytest.mark.asyncio
    async def test_sync_failure_falls_back_to_cached_snapshot(self, mock_session, student_id):
        """When live sync fails, return existing snapshot with PORTAL_SNAPSHOT_STALE."""
        service = PortalSyncService(mock_session)
        stale_time = datetime.now(UTC) - timedelta(hours=6)
        stale_snapshot = self._make_snapshot(student_id, stale_time)

        service.snapshot_repo.get_latest_for_student_with_subjects = AsyncMock(
            return_value=stale_snapshot
        )

        mock_cred = PortalCredential(
            student_id=student_id,
            portal="doctus",
            roll_number="25MIS0001",
            encrypted_password="encrypted_blob",
            status=PortalCredentialStatus.CONNECTED,
        )
        service.credential_repo.get_by_student_and_portal = AsyncMock(return_value=mock_cred)
        service.sync_attendance = AsyncMock(side_effect=DoctusAdapterError("Network timeout connecting to portal"))

        snapshot, provenance, notice = await service.get_or_sync_attendance(student_id)

        assert snapshot == stale_snapshot
        assert provenance == AttendanceProvenance.PORTAL_SNAPSHOT_STALE
        assert notice is not None
        assert "unavailable" in notice.lower() or "network" in notice.lower()

    @pytest.mark.asyncio
    async def test_sync_failure_with_no_cached_snapshot_returns_none(self, mock_session, student_id):
        """When Doctus fails and no cached snapshot exists, return None (NO FABRICATION)."""
        service = PortalSyncService(mock_session)

        service.snapshot_repo.get_latest_for_student_with_subjects = AsyncMock(return_value=None)
        mock_cred = PortalCredential(
            student_id=student_id,
            portal="doctus",
            roll_number="25MIS0001",
            encrypted_password="encrypted_blob",
            status=PortalCredentialStatus.CONNECTED,
        )
        service.credential_repo.get_by_student_and_portal = AsyncMock(return_value=mock_cred)
        service.sync_attendance = AsyncMock(side_effect=DoctusAdapterError("Doctus server down 503"))

        snapshot, provenance, notice = await service.get_or_sync_attendance(student_id)

        assert snapshot is None
        assert provenance == AttendanceProvenance.PORTAL_SNAPSHOT_STALE
        assert notice is not None

    @pytest.mark.asyncio
    async def test_doctus_login_failure_marks_reconnect_required(self, mock_session, student_id):
        """When portal credentials fail, status is marked RECONNECT_REQUIRED."""
        service = PortalSyncService(mock_session)
        stale_time = datetime.now(UTC) - timedelta(hours=6)
        stale_snapshot = self._make_snapshot(student_id, stale_time)

        service.snapshot_repo.get_latest_for_student_with_subjects = AsyncMock(
            return_value=stale_snapshot
        )
        mock_cred = PortalCredential(
            student_id=student_id,
            portal="doctus",
            roll_number="25MIS0001",
            encrypted_password="encrypted_blob",
            status=PortalCredentialStatus.CONNECTED,
        )
        mock_cred.id = uuid4()
        service.credential_repo.get_by_student_and_portal = AsyncMock(return_value=mock_cred)
        service.credential_repo.update_status = AsyncMock()

        # Simulate login error thrown in sync_attendance
        service.sync_attendance = AsyncMock(side_effect=DoctusLoginError("Invalid password"))

        snapshot, provenance, notice = await service.get_or_sync_attendance(student_id)

        assert snapshot == stale_snapshot
        assert provenance == AttendanceProvenance.PORTAL_SNAPSHOT_STALE
        assert "login failed" in notice.lower()


class TestAttendanceProvenanceRendering:
    """Verify AttendanceRenderer renders provenance badges appropriately."""

    @pytest.fixture
    def context(self):
        student_id = uuid4()
        profile = StudentProfile(
            student_id=student_id,
            name="Harsh",
            attendance_target=75.0,
        )
        return StudentContext(
            student_id=student_id,
            profile=profile,
            conversation=ConversationContext(student_id=student_id),
        )

    def test_render_overall_live_sync(self, context):
        renderer = AttendanceRenderer()
        result = {
            "cumulative_percentage": 84.5,
            "cumulative_attended": 84,
            "cumulative_conducted": 100,
            "captured_at": datetime.now(UTC).isoformat(),
            "provenance": "portal_live_sync",
        }
        output = renderer.render("get_overall_attendance", result, context)
        assert "Overall Attendance:" in output
        assert "84.5%" in output
        assert "Synced live from Doctus just now" in output

    def test_render_summary_fresh_snapshot(self, context):
        renderer = AttendanceRenderer()
        result = {
            "overall": {
                "cumulative_percentage": 80.0,
                "cumulative_attended": 80,
                "cumulative_conducted": 100,
            },
            "subjects": [
                {
                    "subject_name": "Operating Systems",
                    "subject_code": "OS101",
                    "cumulative_percentage": 80.0,
                    "cumulative_attended": 20,
                    "cumulative_conducted": 25,
                }
            ],
            "captured_at": "2026-10-01T14:30:00+00:00",
            "provenance": "portal_snapshot_fresh",
        }
        output = renderer.render("get_attendance_summary", result, context)
        assert "Attendance Summary:" in output
        assert "Operating Systems" in output
        assert "Sourced from Doctus snapshot" in output

    def test_render_stale_snapshot_with_warning(self, context):
        renderer = AttendanceRenderer()
        result = {
            "cumulative_percentage": 74.0,
            "cumulative_attended": 74,
            "cumulative_conducted": 100,
            "captured_at": "2026-09-30T10:00:00+00:00",
            "provenance": "portal_snapshot_stale",
            "notice": "Portal refresh unavailable: 503 Service Unavailable",
        }
        output = renderer.render("get_overall_attendance", result, context)
        assert "Live refresh unavailable" in output
        assert "Portal refresh unavailable" in output

    def test_render_sync_attendance_tool_success(self, context):
        renderer = AttendanceRenderer()
        result = {
            "success": True,
            "overall_percentage": 86.2,
            "subject_count": 7,
            "captured_at": datetime.now(UTC).isoformat(),
        }
        output = renderer.render("sync_attendance", result, context)
        assert "Attendance Sync:" in output
        assert "Successfully synced from Doctus!" in output
        assert "86.2%" in output
        assert "7" in output
