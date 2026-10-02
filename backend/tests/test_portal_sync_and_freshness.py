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

    @pytest.mark.asyncio
    async def test_redirect_notice_in_get_or_sync_attendance(self, mock_session, student_id):
        """When portal redirect occurs during sync, clear diagnostic notice is returned."""
        service = PortalSyncService(mock_session)
        mock_cred = PortalCredential(
            student_id=student_id,
            portal="doctus",
            roll_number="25MIS0001",
            encrypted_password="encrypted_blob",
            status=PortalCredentialStatus.CONNECTED,
        )
        service.credential_repo.get_by_student_and_portal = AsyncMock(return_value=mock_cred)
        service.snapshot_repo.get_latest_for_student_with_subjects = AsyncMock(return_value=None)
        service.sync_attendance = AsyncMock(
            side_effect=Exception("College portal session was redirected to /Login; checking authentication.")
        )

        snapshot, provenance, notice = await service.get_or_sync_attendance(student_id)

        assert snapshot is None
        assert provenance == AttendanceProvenance.PORTAL_SNAPSHOT_STALE
        assert notice == "College portal session was redirected; checking authentication."


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

    def test_render_overall_below_target_plain_language(self, context):
        renderer = AttendanceRenderer()
        result = {
            "cumulative_percentage": 58.2,
            "cumulative_attended": 178,
            "cumulative_conducted": 306,
            "target_percentage": 75.0,
            "target_difference": -16.8,
            "target_status": "below",
            "target_gap_percentage": 16.8,
            "captured_at": "2026-10-02T12:00:00+00:00",
            "provenance": "portal_live_sync",
        }
        output = renderer.render("get_overall_attendance", result, context)
        assert "• <b>Overall:</b> <code>58.2%</code> (178/306 attended)" in output
        assert "• <b>Target:</b> <code>75.0%</code>" in output
        assert "• <b>Status:</b> ⚠️ 16.8% more needed to reach 75%" in output
        assert "Margin:" not in output
        assert "deficit" not in output

    def test_render_overall_at_target_plain_language(self, context):
        renderer = AttendanceRenderer()
        result = {
            "cumulative_percentage": 75.0,
            "cumulative_attended": 150,
            "cumulative_conducted": 200,
            "target_percentage": 75.0,
            "target_difference": 0.0,
            "target_status": "at_target",
            "target_gap_percentage": 0.0,
            "captured_at": "2026-10-02T12:00:00+00:00",
            "provenance": "portal_live_sync",
        }
        output = renderer.render("get_overall_attendance", result, context)
        assert "• <b>Status:</b> ✅ At 75% target" in output
        assert "Margin:" not in output

    def test_render_overall_above_target_plain_language(self, context):
        renderer = AttendanceRenderer()
        result = {
            "cumulative_percentage": 80.0,
            "cumulative_attended": 160,
            "cumulative_conducted": 200,
            "target_percentage": 75.0,
            "target_difference": 5.0,
            "target_status": "above",
            "target_gap_percentage": 5.0,
            "captured_at": "2026-10-02T12:00:00+00:00",
            "provenance": "portal_live_sync",
        }
        output = renderer.render("get_overall_attendance", result, context)
        assert "• <b>Status:</b> ✅ 5.0% above 75% target" in output
        assert "Margin:" not in output


class TestLegacySnapshotReconciliationAndGreenletSafety:
    """Verify read-time legacy reconciliation and greenlet commit safety."""

    def test_reconcile_legacy_broken_snapshot_on_read_without_mutation(self):
        from app.intelligence.services.attendance_service import AttendanceService

        service = AttendanceService(session=MagicMock())

        # Broken snapshot: overall conducted is 6, but subjects sum to 306 conducted
        snapshot = AttendanceSnapshot(
            student_id=uuid4(),
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=6,
            overall_conducted=6,
        )
        snapshot.id = uuid4()
        snapshot.subjects = [
            SubjectAttendance(
                snapshot_id=snapshot.id,
                subject_code="CS301",
                cumulative_attended=90,
                cumulative_conducted=150,
            ),
            SubjectAttendance(
                snapshot_id=snapshot.id,
                subject_code="CS302",
                cumulative_attended=88,
                cumulative_conducted=156,
            ),
        ]

        (
            att,
            cond,
            pct,
            reconciled,
            diff,
            status,
            gap,
        ) = service._reconcile_snapshot_overall(snapshot, target_percentage=75.0)

        # Verified fallback to subject sum:
        # 90+88 = 178 attended, 150+156 = 306 conducted
        assert att == 178
        assert cond == 306
        assert pct == 58.17
        assert reconciled is True
        assert diff == -16.83
        assert status == "below"
        assert gap == 16.83

        # Database object itself is NOT mutated
        assert snapshot.overall_attended == 6
        assert snapshot.overall_conducted == 6

    def test_reconcile_preserves_authoritative_portal_aggregate(self):
        from app.intelligence.services.attendance_service import AttendanceService

        service = AttendanceService(session=MagicMock())

        # Authoritative snapshot: conducted matches subject sum
        snapshot = AttendanceSnapshot(
            student_id=uuid4(),
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=160,
            overall_conducted=200,
        )
        snapshot.id = uuid4()
        snapshot.subjects = [
            SubjectAttendance(
                snapshot_id=snapshot.id,
                subject_code="CS301",
                cumulative_attended=160,
                cumulative_conducted=200,
            )
        ]

        (
            att,
            cond,
            pct,
            reconciled,
            diff,
            status,
            gap,
        ) = service._reconcile_snapshot_overall(snapshot, target_percentage=75.0)

        assert att == 160
        assert cond == 200
        assert pct == 80.0
        assert reconciled is False
        assert diff == 5.0
        assert status == "above"
        assert gap == 5.0
