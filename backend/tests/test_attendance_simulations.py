"""
Comprehensive Test Suite for Attendance & Bunk Simulations.

Validates the 8 core requirements:
1. Rejection of same-date conflicts (ATTEND + SKIP on same date -> ScenarioConflictError).
2. Confirmation that instructional days are driven purely by confirmed timetable entries
   (Sunday is included if sessions are scheduled; sessionless days are skipped).
3. Ambiguous lab batch handling (raises LabBatchAmbiguityError with affected subjects/dates,
   proceeds when student has a known batch).
4. Automatic reconciliation of legacy corrupted 6/6 snapshots to true cumulative sums (178/306).
5. Valid mixed attend/skip scenarios across distinct dates.
6. Subject periods simulation by exact code or natural language query (OS, Operating Systems).
7. Absolute isolation from Doctus portal sync (zero HTTP calls, zero risk of portal lockouts).
8. Read-only execution with zero mutation to stored attendance records or snapshots.
"""

from datetime import UTC, date, datetime, time
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.intelligence.rendering.attendance_renderer import AttendanceRenderer
from app.intelligence.services.attendance_service import (
    AttendanceService,
    reconcile_snapshot_overall,
)
from app.intelligence.services.scenario_resolver import (
    InvalidSessionCountError,
    LabBatchAmbiguityError,
    NoConfirmedTimetableError,
    PartialDayRequest,
    ResolvedSessionAction,
    ScenarioConflictError,
    ScenarioResolver,
    SessionConflictError,
    SimulationAction,
    SubjectNotFoundError,
)
from app.intelligence.services.simulation_service import AttendanceSimulationService
from app.intelligence.tools.attendance_tools import execute_attendance_tool
from app.models.attendance import (
    AttendanceSnapshot,
    AttendanceSource,
    SubjectAttendance,
)
from app.models.student import Student
from app.models.timetable import (
    ActivityType,
    LabBatch,
    Timetable,
    TimetableEntry,
    TimetableStatus,
)


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def student_id():
    return uuid4()


@pytest.fixture
def student_batch1(student_id):
    return Student(
        id=student_id,
        name="Harsh V",
        attendance_target=75.0,
        lab_batch=LabBatch.BATCH_1,
    )


@pytest.fixture
def student_unknown_batch(student_id):
    return Student(
        id=student_id,
        name="Harsh V",
        attendance_target=75.0,
        lab_batch=LabBatch.UNKNOWN,
    )


@pytest.fixture
def legacy_corrupted_snapshot(student_id):
    """
    Snapshot mimicking the legacy Doctus issue where overall was 6/6 (100%),
    but subjects sum up to 178 attended / 306 conducted (~58.17%).
    """
    snapshot = AttendanceSnapshot(
        id=uuid4(),
        student_id=student_id,
        source=AttendanceSource.DOCTUS,
        captured_at=datetime.now(UTC),
        overall_attended=6,
        overall_conducted=6,
    )
    # 5 subjects summing to 178 / 306
    s1 = SubjectAttendance(
        id=uuid4(),
        snapshot_id=snapshot.id,
        subject_code="25PC1CS201",
        subject_name="Operating Systems",
        cumulative_attended=40,
        cumulative_conducted=60,
    )
    s2 = SubjectAttendance(
        id=uuid4(),
        snapshot_id=snapshot.id,
        subject_code="25PC1CS202",
        subject_name="Data Structures and Algorithms",
        cumulative_attended=50,
        cumulative_conducted=80,
    )
    s3 = SubjectAttendance(
        id=uuid4(),
        snapshot_id=snapshot.id,
        subject_code="25PC1CS203",
        subject_name="Database Management Systems",
        cumulative_attended=35,
        cumulative_conducted=70,
    )
    s4 = SubjectAttendance(
        id=uuid4(),
        snapshot_id=snapshot.id,
        subject_code="25PC1CS204",
        subject_name="Computer Networks",
        cumulative_attended=30,
        cumulative_conducted=50,
    )
    s5 = SubjectAttendance(
        id=uuid4(),
        snapshot_id=snapshot.id,
        subject_code="25PC1CS205",
        subject_name="Environmental Science",
        cumulative_attended=23,
        cumulative_conducted=46,
    )
    snapshot.subjects = [s1, s2, s3, s4, s5]
    return snapshot


@pytest.fixture
def standard_timetable(student_id):
    """
    Timetable with:
    - Monday (day_of_week=0): 4 periods (CS201, CS202, CS203, CS204)
    - Tuesday (day_of_week=1): 1 theory + divided lab batch (Batch 1 & Batch 2 for CS205)
    - Sunday (day_of_week=6): 2 periods (CS201, CS202) -> Demonstrates Sunday can be instructional!
    - Wednesday (day_of_week=2): 0 periods (Free day)
    """
    tt = Timetable(
        id=uuid4(),
        student_id=student_id,
        academic_year="2026-2027",
        semester=3,
        status=TimetableStatus.CONFIRMED,
        created_at=datetime.now(UTC),
    )
    entries = [
        # Monday (0)
        TimetableEntry(
            id=uuid4(),
            timetable_id=tt.id,
            day_of_week=0,
            start_time=time(9, 0),
            end_time=time(10, 0),
            course_code="25PC1CS201",
            activity_name="Operating Systems",
            activity_type=ActivityType.ACADEMIC,
        ),
        TimetableEntry(
            id=uuid4(),
            timetable_id=tt.id,
            day_of_week=0,
            start_time=time(10, 0),
            end_time=time(11, 0),
            course_code="25PC1CS202",
            activity_name="Data Structures and Algorithms",
            activity_type=ActivityType.ACADEMIC,
        ),
        TimetableEntry(
            id=uuid4(),
            timetable_id=tt.id,
            day_of_week=0,
            start_time=time(11, 15),
            end_time=time(12, 15),
            course_code="25PC1CS203",
            activity_name="Database Management Systems",
            activity_type=ActivityType.ACADEMIC,
        ),
        TimetableEntry(
            id=uuid4(),
            timetable_id=tt.id,
            day_of_week=0,
            start_time=time(13, 0),
            end_time=time(14, 0),
            course_code="25PC1CS204",
            activity_name="Computer Networks",
            activity_type=ActivityType.ACADEMIC,
        ),
        # Tuesday (1): 1 theory + 1 divided lab (Batch 1 & Batch 2)
        TimetableEntry(
            id=uuid4(),
            timetable_id=tt.id,
            day_of_week=1,
            start_time=time(9, 0),
            end_time=time(10, 0),
            course_code="25PC1CS201",
            activity_name="Operating Systems",
            activity_type=ActivityType.ACADEMIC,
        ),
        TimetableEntry(
            id=uuid4(),
            timetable_id=tt.id,
            day_of_week=1,
            start_time=time(10, 0),
            end_time=time(12, 0),
            course_code="25PC1CS205",
            activity_name="OS Lab",
            activity_type=ActivityType.LAB,
            lab_batch=LabBatch.BATCH_1,
        ),
        TimetableEntry(
            id=uuid4(),
            timetable_id=tt.id,
            day_of_week=1,
            start_time=time(10, 0),
            end_time=time(12, 0),
            course_code="25PC1CS205",
            activity_name="OS Lab",
            activity_type=ActivityType.LAB,
            lab_batch=LabBatch.BATCH_2,
        ),
        # Sunday (6): Special makeup / instructional classes
        TimetableEntry(
            id=uuid4(),
            timetable_id=tt.id,
            day_of_week=6,
            start_time=time(10, 0),
            end_time=time(11, 0),
            course_code="25PC1CS201",
            activity_name="Operating Systems",
            activity_type=ActivityType.ACADEMIC,
        ),
        TimetableEntry(
            id=uuid4(),
            timetable_id=tt.id,
            day_of_week=6,
            start_time=time(11, 0),
            end_time=time(12, 0),
            course_code="25PC1CS202",
            activity_name="Data Structures and Algorithms",
            activity_type=ActivityType.ACADEMIC,
        ),
    ]
    tt.entries = entries
    return tt


# ==============================================================================
# 1. Same-Date Conflict Rejection
# ==============================================================================

class TestScenarioConflictDetection:
    """Test that conflicting actions on the same calendar date are rejected immediately."""

    @pytest.mark.asyncio
    async def test_explicit_same_date_attend_and_skip_rejected(
        self, student_batch1, standard_timetable
    ):
        mock_tt_repo = AsyncMock()
        mock_tt_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_tt_repo, mock_student_repo)
        with pytest.raises(ScenarioConflictError) as exc_info:
            await resolver.resolve_scenario(
                student_id=student_batch1.id,
                days_to_skip=["2026-10-05"],
                days_to_attend=["2026-10-05"],
                custom_today=date(2026, 10, 4),
            )
        assert exc_info.value.conflicting_date == date(2026, 10, 5)
        assert "05 Oct 2026" in str(exc_info.value)
        assert "both attend and skip" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_relative_and_explicit_same_date_rejected(
        self, student_batch1, standard_timetable
    ):
        # 2026-10-04 is Sunday. Tomorrow is 2026-10-05 (Monday).
        mock_tt_repo = AsyncMock()
        mock_tt_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_tt_repo, mock_student_repo)
        with pytest.raises(ScenarioConflictError) as exc_info:
            await resolver.resolve_scenario(
                student_id=student_batch1.id,
                days_to_skip=["tomorrow"],
                days_to_attend=["2026-10-05"],
                custom_today=date(2026, 10, 4),
            )
        assert exc_info.value.conflicting_date == date(2026, 10, 5)
        assert "05 Oct 2026" in str(exc_info.value)


# ==============================================================================
# 2. Instructional Days & Zero Sunday Assumptions
# ==============================================================================

class TestInstructionalDaysResolution:
    """Test that instructional days are determined purely by confirmed timetable sessions."""

    @pytest.mark.asyncio
    async def test_sunday_included_when_scheduled(
        self, student_batch1, standard_timetable
    ):
        mock_tt_repo = AsyncMock()
        mock_tt_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_tt_repo, mock_student_repo)
        # Starting Saturday 2026-10-03:
        # 2026-10-04 (Sun): HAS 2 ENTRIES (day_of_week=6) -> Included!
        # 2026-10-05 (Mon): HAS 4 ENTRIES (day_of_week=0) -> Included!
        scenario = await resolver.resolve_scenario(
            student_id=student_batch1.id,
            skip_next_n_days=2,
            custom_today=date(2026, 10, 3),
        )
        assert len(scenario.actions) == 2
        # First instructional day must be Sunday 2026-10-04
        assert scenario.actions[0].date == date(2026, 10, 4)
        assert scenario.actions[0].day_name == "Sunday"
        assert scenario.actions[0].action == SimulationAction.SKIP
        # Second instructional day must be Monday 2026-10-05
        assert scenario.actions[1].date == date(2026, 10, 5)
        assert scenario.actions[1].day_name == "Monday"

    @pytest.mark.asyncio
    async def test_sessionless_weekday_skipped_from_instructional_days(
        self, student_batch1, standard_timetable
    ):
        mock_tt_repo = AsyncMock()
        mock_tt_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_tt_repo, mock_student_repo)
        # Starting Monday 2026-10-05:
        # Day 1: Mon 2026-10-05 (has classes)
        # Day 2: Tue 2026-10-06 (has classes)
        # Wed 2026-10-07: no classes -> skipped!
        # Thu/Fri/Sat: no classes in fixture -> skipped!
        # Day 3: Sun 2026-10-11 (has classes)
        scenario = await resolver.resolve_scenario(
            student_id=student_batch1.id,
            skip_next_n_days=3,
            custom_today=date(2026, 10, 5),
        )
        assert len(scenario.actions) == 3
        dates = [a.date for a in scenario.actions]
        assert date(2026, 10, 6) in dates
        assert date(2026, 10, 7) not in dates  # Wednesday has 0 classes, skipped
        assert date(2026, 10, 11) in dates  # Next Sunday has classes, included
        assert date(2026, 10, 12) in dates  # Next Monday has classes, included


# ==============================================================================
# 3. Lab Batch Ambiguity Defense
# ==============================================================================

class TestLabBatchAmbiguity:
    """Test that divided lab sessions require a known lab batch to avoid distorted calculations."""

    @pytest.mark.asyncio
    async def test_unknown_lab_batch_raises_ambiguity_error(
        self, student_unknown_batch, standard_timetable
    ):
        mock_tt_repo = AsyncMock()
        mock_tt_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_unknown_batch)

        resolver = ScenarioResolver(mock_tt_repo, mock_student_repo)
        # Tuesday 2026-10-06 has OS Lab divided into Batch 1 & Batch 2
        with pytest.raises(LabBatchAmbiguityError) as exc_info:
            await resolver.resolve_scenario(
                student_id=student_unknown_batch.id,
                days_to_skip=["2026-10-06"],
                custom_today=date(2026, 10, 4),
            )
        err = exc_info.value
        assert err.activity_name == "OS Lab"
        assert err.target_date == date(2026, 10, 6)
        assert "batch" in str(err).lower()

    @pytest.mark.asyncio
    async def test_known_lab_batch_proceeds(
        self, student_batch1, standard_timetable
    ):
        mock_tt_repo = AsyncMock()
        mock_tt_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_tt_repo, mock_student_repo)
        # Tuesday 2026-10-06 with student in BATCH_1 succeeds without error
        scenario = await resolver.resolve_scenario(
            student_id=student_batch1.id,
            days_to_skip=["2026-10-06"],
            custom_today=date(2026, 10, 4),
        )
        assert len(scenario.actions) == 1
        assert scenario.actions[0].date == date(2026, 10, 6)


# ==============================================================================
# 4. Legacy Snapshot Reconciliation in Simulations
# ==============================================================================

class TestLegacySnapshotReconciliation:
    """Test that simulations correct legacy 6/6 snapshots to true cumulative sums (178/306)."""

    def test_reconcile_snapshot_overall_helper(self, legacy_corrupted_snapshot):
        (
            attended,
            conducted,
            pct,
            reconciled,
            diff,
            status,
            gap,
        ) = reconcile_snapshot_overall(legacy_corrupted_snapshot, 75.0)
        assert attended == 178
        assert conducted == 306
        assert round(pct, 2) == 58.17
        assert reconciled is True

    @pytest.mark.asyncio
    async def test_simulation_uses_reconciled_baseline(
        self,
        mock_session,
        student_batch1,
        legacy_corrupted_snapshot,
        standard_timetable,
    ):
        mock_snapshot_repo = AsyncMock()
        mock_snapshot_repo.get_latest = AsyncMock(return_value=legacy_corrupted_snapshot)

        mock_timetable_repo = AsyncMock()
        mock_timetable_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)

        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_timetable_repo, mock_student_repo)
        sim_service = AttendanceSimulationService(
            session=mock_session,
            snapshot_repo=mock_snapshot_repo,
            timetable_repo=mock_timetable_repo,
            student_repo=mock_student_repo,
        )

        # Simulate skipping Monday 2026-10-05 (4 theory classes)
        scenario = await resolver.resolve_scenario(
            student_id=student_batch1.id,
            days_to_skip=["2026-10-05"],
            custom_today=date(2026, 10, 4),
        )

        result = await sim_service.simulate_schedule_scenario(scenario)

        # Baseline must be 178 / 306 (NOT 6 / 6)
        assert result.current_attended == 178
        assert result.current_conducted == 306
        assert round(result.current_percentage, 2) == 58.17

        # Projected: 4 periods skipped -> 178 attended / 310 conducted
        assert result.projected_attended == 178
        assert result.projected_conducted == 310
        expected_projected_pct = round((178 / 310) * 100, 2)
        assert result.projected_percentage == expected_projected_pct
        assert result.percentage_change == round(expected_projected_pct - 58.17, 2)


# ==============================================================================
# 5. Mixed Action Scenario (Attend + Skip Across Distinct Dates)
# ==============================================================================

class TestMixedActionScenarios:
    """Test valid combinations of days_to_attend and days_to_skip."""

    @pytest.mark.asyncio
    async def test_attend_tuesday_and_skip_monday(
        self,
        mock_session,
        student_batch1,
        legacy_corrupted_snapshot,
        standard_timetable,
    ):
        mock_snapshot_repo = AsyncMock()
        mock_snapshot_repo.get_latest = AsyncMock(return_value=legacy_corrupted_snapshot)
        mock_timetable_repo = AsyncMock()
        mock_timetable_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_timetable_repo, mock_student_repo)
        sim_service = AttendanceSimulationService(
            session=mock_session,
            snapshot_repo=mock_snapshot_repo,
            timetable_repo=mock_timetable_repo,
            student_repo=mock_student_repo,
        )

        # Skip Monday 2026-10-05 (4 periods) and Attend Tuesday 2026-10-06 (2 periods for Batch 1)
        scenario = await resolver.resolve_scenario(
            student_id=student_batch1.id,
            days_to_skip=["2026-10-05"],
            days_to_attend=["2026-10-06"],
            custom_today=date(2026, 10, 4),
        )

        result = await sim_service.simulate_schedule_scenario(scenario)

        # Net change:
        # Monday skipped: +0 attended, +4 conducted
        # Tuesday attended: +2 attended, +2 conducted
        # Total added: +2 attended, +6 conducted
        assert result.current_attended == 178
        assert result.current_conducted == 306
        assert result.projected_attended == 178 + 2  # 180
        assert result.projected_conducted == 306 + 6  # 312
        assert len(result.scenario_dates) == 2


# ==============================================================================
# 6. Subject Periods Simulation & Natural Language Resolution
# ==============================================================================

class TestSubjectPeriodsSimulation:
    """Test period-level simulation and natural-language subject resolution."""

    @pytest.mark.asyncio
    async def test_simulate_missing_periods_by_code(
        self,
        mock_session,
        student_batch1,
        legacy_corrupted_snapshot,
        standard_timetable,
    ):
        mock_snapshot_repo = AsyncMock()
        mock_snapshot_repo.get_latest = AsyncMock(return_value=legacy_corrupted_snapshot)
        mock_timetable_repo = AsyncMock()
        mock_timetable_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        sim_service = AttendanceSimulationService(
            session=mock_session,
            snapshot_repo=mock_snapshot_repo,
            timetable_repo=mock_timetable_repo,
            student_repo=mock_student_repo,
        )

        # Miss 2 periods of 25PC1CS201 (OS: baseline 40/60 = 66.67%)
        result = await sim_service.simulate_subject_periods(
            student_id=student_batch1.id,
            subject_code="25PC1CS201",
            periods_to_miss=2,
        )

        assert result.available is True
        assert result.subject_code == "25PC1CS201"
        assert result.subject_current_attended == 40
        assert result.subject_current_conducted == 60
        # 2 periods missed -> 40 attended / 62 conducted
        assert result.subject_projected_attended == 40
        assert result.subject_projected_conducted == 62
        assert result.subject_projected_percentage == round((40 / 62) * 100, 2)
        # Overall also adjusted: 178 attended / 308 conducted
        assert result.overall_projected_attended == 178
        assert result.overall_projected_conducted == 308

    @pytest.mark.asyncio
    async def test_simulate_attending_periods_by_natural_name(
        self,
        mock_session,
        student_batch1,
        legacy_corrupted_snapshot,
        standard_timetable,
    ):
        mock_snapshot_repo = AsyncMock()
        mock_snapshot_repo.get_latest = AsyncMock(return_value=legacy_corrupted_snapshot)
        mock_timetable_repo = AsyncMock()
        mock_timetable_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_timetable_repo, mock_student_repo)
        sim_service = AttendanceSimulationService(
            session=mock_session,
            snapshot_repo=mock_snapshot_repo,
            timetable_repo=mock_timetable_repo,
            student_repo=mock_student_repo,
        )

        # "Operating Systems" query -> matches 25PC1CS201 via resolver
        code, name = await resolver.resolve_subject_query(student_batch1.id, "Operating Systems")
        assert code == "25PC1CS201"

        result = await sim_service.simulate_subject_periods(
            student_id=student_batch1.id,
            subject_code=code,
            periods_to_attend=3,
            display_name=name,
        )

        assert result.available is True
        assert result.subject_code == "25PC1CS201"
        # 3 periods attended -> 43 attended / 63 conducted
        assert result.subject_projected_attended == 43
        assert result.subject_projected_conducted == 63
        assert result.overall_projected_attended == 181
        assert result.overall_projected_conducted == 309

    @pytest.mark.asyncio
    async def test_unfound_subject_raises_error(
        self,
        student_batch1,
        standard_timetable,
    ):
        mock_timetable_repo = AsyncMock()
        mock_timetable_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_timetable_repo, mock_student_repo)

        with pytest.raises(SubjectNotFoundError) as exc_info:
            await resolver.resolve_subject_query(
                student_id=student_batch1.id,
                subject_query="Nonexistent Quantum Physics",
            )
        assert "Nonexistent Quantum Physics" in str(exc_info.value)


# ==============================================================================
# 7. Zero Portal Network Calls & Database Non-Mutation
# ==============================================================================

class TestZeroPortalRiskAndReadonlyGuarantee:
    """Guarantee that simulations cannot trigger Doctus portal HTTP calls or mutate the DB."""

    @pytest.mark.asyncio
    async def test_no_portal_service_dependency_or_network_calls(
        self,
        mock_session,
        student_batch1,
        legacy_corrupted_snapshot,
        standard_timetable,
    ):
        mock_snapshot_repo = AsyncMock()
        mock_snapshot_repo.get_latest = AsyncMock(return_value=legacy_corrupted_snapshot)
        mock_timetable_repo = AsyncMock()
        mock_timetable_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_timetable_repo, mock_student_repo)
        sim_service = AttendanceSimulationService(
            session=mock_session,
            snapshot_repo=mock_snapshot_repo,
            timetable_repo=mock_timetable_repo,
            student_repo=mock_student_repo,
        )

        # Verify AttendanceSimulationService has NO portal_sync_service attribute
        assert not hasattr(sim_service, "portal_sync_service")

        scenario = await resolver.resolve_scenario(
            student_id=student_batch1.id,
            days_to_skip=["2026-10-05"],
            custom_today=date(2026, 10, 4),
        )

        # Run simulation
        await sim_service.simulate_schedule_scenario(scenario)

        # Database session commit must NOT be called
        mock_session.commit.assert_not_called()

        # Stored snapshot metrics must be completely untouched
        assert legacy_corrupted_snapshot.overall_attended == 6
        assert legacy_corrupted_snapshot.overall_conducted == 6


# ==============================================================================
# 8. Tool Execution & Renderer Verification
# ==============================================================================

class TestToolExecutionAndRendering:
    """Test execute_attendance_tool and AttendanceRenderer integration."""

    @pytest.mark.asyncio
    async def test_execute_simulate_schedule_scenario_tool(
        self,
        mock_session,
        student_batch1,
        legacy_corrupted_snapshot,
        standard_timetable,
    ):
        mock_attendance_service = MagicMock(spec=AttendanceService)
        mock_attendance_service.session = mock_session
        mock_attendance_service.snapshot_repo = AsyncMock()
        mock_attendance_service.snapshot_repo.get_latest = AsyncMock(return_value=legacy_corrupted_snapshot)
        mock_attendance_service.student_repo = AsyncMock()
        mock_attendance_service.student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        mock_timetable_service = MagicMock()
        mock_timetable_service.timetable_repo = AsyncMock()
        mock_timetable_service.timetable_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)

        result = await execute_attendance_tool(
            attendance_service=mock_attendance_service,
            timetable_service=mock_timetable_service,
            tool_name="simulate_schedule_scenario",
            student_id=str(student_batch1.id),
            days_to_skip=["2026-10-05"],
            custom_today=date(2026, 10, 4),
        )

        assert result["available"] is True
        assert result["current_attended"] == 178
        assert result["current_conducted"] == 306
        assert result["projected_attended"] == 178
        assert result["projected_conducted"] == 310

        # Render output
        renderer = AttendanceRenderer()
        text = renderer.render_schedule_scenario(result)
        assert "Schedule Simulation" in text
        assert "Operating Systems" in text
        assert "58.2%" in text

    @pytest.mark.asyncio
    async def test_execute_simulate_subject_periods_tool(
        self,
        mock_session,
        student_batch1,
        legacy_corrupted_snapshot,
        standard_timetable,
    ):
        mock_attendance_service = MagicMock(spec=AttendanceService)
        mock_attendance_service.session = mock_session
        mock_attendance_service.snapshot_repo = AsyncMock()
        mock_attendance_service.snapshot_repo.get_latest = AsyncMock(return_value=legacy_corrupted_snapshot)
        mock_attendance_service.student_repo = AsyncMock()
        mock_attendance_service.student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        mock_timetable_service = MagicMock()
        mock_timetable_service.timetable_repo = AsyncMock()
        mock_timetable_service.timetable_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)

        result = await execute_attendance_tool(
            attendance_service=mock_attendance_service,
            timetable_service=mock_timetable_service,
            tool_name="simulate_subject_periods",
            student_id=str(student_batch1.id),
            subject_name="Operating Systems",
            periods_to_miss=2,
        )

        assert result["available"] is True
        assert result["subject_code"] == "25PC1CS201"
        assert result["subject_projected_conducted"] == 62

        # Render output
        renderer = AttendanceRenderer()
        text = renderer.render_subject_periods(result)
        assert "Operating Systems" in text
        assert "Simulation" in text


# ==============================================================================
# 9. Strict Partial-Day Validation & Unified Session Actions
# ==============================================================================

class TestPartialDayValidationAndResolution:
    """Validate partial-day bounds, session count checks, and conflict detection."""

    @pytest.mark.asyncio
    async def test_partial_day_request_exceeds_available_periods(
        self, student_batch1, standard_timetable
    ):
        """
        If Sunday has only 2 scheduled classes, requesting to skip first 3 must raise
        InvalidSessionCountError with clear clarification (Directive 4).
        """
        mock_tt_repo = AsyncMock()
        mock_tt_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_tt_repo, mock_student_repo)

        # Sunday 2026-10-04 has only 2 scheduled classes in standard_timetable
        with pytest.raises(InvalidSessionCountError) as exc_info:
            await resolver.resolve_scenario(
                student_id=student_batch1.id,
                partial_day_scenarios=[
                    {"date": "2026-10-04", "skip_first_n_periods": 3}
                ],
                custom_today=date(2026, 10, 3),
            )
        assert "only 2 scheduled classes" in str(exc_info.value)
        assert "skip the first 3" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_same_session_cannot_be_attend_and_skip(
        self, student_batch1, standard_timetable
    ):
        """
        A single scheduled session cannot be requested as both ATTEND and SKIP.
        """
        mock_tt_repo = AsyncMock()
        mock_tt_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_tt_repo, mock_student_repo)

        with pytest.raises(SessionConflictError) as exc_info:
            await resolver.resolve_scenario(
                student_id=student_batch1.id,
                partial_day_scenarios=[
                    {
                        "date": "2026-10-05",  # Monday has 4 classes
                        "periods_to_skip": [1],
                        "periods_to_attend": [1],
                    }
                ],
                custom_today=date(2026, 10, 4),
            )
        assert "both ATTEND and SKIP" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_partial_day_first_n_periods_simulation(
        self,
        mock_session,
        student_batch1,
        legacy_corrupted_snapshot,
        standard_timetable,
    ):
        """
        Simulate skipping first 3 classes on Monday and attending the remaining 1.
        Baseline: 178 / 306.
        After: 1 attended, 3 missed -> total 4 evaluated -> 179 / 310.
        """
        mock_snapshot_repo = AsyncMock()
        mock_snapshot_repo.get_latest = AsyncMock(return_value=legacy_corrupted_snapshot)
        mock_timetable_repo = AsyncMock()
        mock_timetable_repo.get_latest_confirmed_for_student = AsyncMock(return_value=standard_timetable)
        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(mock_timetable_repo, mock_student_repo)
        sim_service = AttendanceSimulationService(
            session=mock_session,
            snapshot_repo=mock_snapshot_repo,
            timetable_repo=mock_timetable_repo,
            student_repo=mock_student_repo,
        )

        scenario = await resolver.resolve_scenario(
            student_id=student_batch1.id,
            partial_day_scenarios=[
                {
                    "date": "2026-10-05",  # Monday: 4 classes (CS201, CS202, CS203, CS204)
                    "skip_first_n_periods": 3,
                    "attend_remaining": True,
                }
            ],
            custom_today=date(2026, 10, 4),
        )

        # 4 session actions: periods 1,2,3 SKIP; period 4 ATTEND
        assert len(scenario.session_actions) == 4
        assert [s.action for s in scenario.session_actions] == [
            SimulationAction.SKIP,
            SimulationAction.SKIP,
            SimulationAction.SKIP,
            SimulationAction.ATTEND,
        ]

        result = await sim_service.simulate_schedule_scenario(scenario)
        assert result.available is True
        assert result.total_scheduled_periods == 4
        assert result.total_delta_conducted == 4
        assert result.total_delta_attended == 1
        assert result.projected_attended == 179
        assert result.projected_conducted == 310


# ==============================================================================
# 10. Authoritative Stored Monthly View Verification
# ==============================================================================

class TestMonthlyBreakdownView:
    """Validate that view='monthly' displays stored portal monthly fields directly."""

    @pytest.mark.asyncio
    async def test_render_monthly_subject_attendance_breakdown(
        self, student_batch1
    ):
        """Verify stored monthly fields are rendered accurately without cumulative fallback."""
        snapshot = AttendanceSnapshot(
            id=uuid4(),
            student_id=student_batch1.id,
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=178,
            overall_conducted=306,
        )
        s1 = SubjectAttendance(
            id=uuid4(),
            snapshot_id=snapshot.id,
            subject_code="25PC1CS201",
            subject_name="Operating Systems",
            monthly_attended=18,
            monthly_conducted=20,
            monthly_period="SEP 2026",
            cumulative_attended=40,
            cumulative_conducted=60,
        )
        s2 = SubjectAttendance(
            id=uuid4(),
            snapshot_id=snapshot.id,
            subject_code="25PC1CS202",
            subject_name="Data Structures",
            monthly_attended=14,
            monthly_conducted=20,
            monthly_period="SEP 2026",
            cumulative_attended=50,
            cumulative_conducted=80,
        )
        snapshot.subjects = [s1, s2]

        service = AttendanceService(session=None, sync_service=None)
        service.get_latest_snapshot = AsyncMock(return_value=snapshot)
        service._get_student_target = AsyncMock(return_value=75.0)
        service._get_confirmed_timetable_mapping = AsyncMock(return_value={})

        result = await execute_attendance_tool(
            attendance_service=service,
            timetable_service=MagicMock(),
            tool_name="get_attendance_summary",
            student_id=str(student_batch1.id),
            view="monthly",
        )

        assert result["available"] is True
        assert result["view"] == "monthly"
        assert result["monthly_period"] == "SEP 2026"
        assert len(result["subjects"]) == 2

        # Renderer verification
        renderer = AttendanceRenderer()
        text = renderer.render_summary(result)

        assert "Monthly Attendance Breakdown (SEP 2026)" in text
        assert "Operating Systems" in text
        assert "18/20" in text
        assert "90.0%" in text
        assert "Data Structures" in text
        assert "14/20" in text
        assert "70.0%" in text


# ==============================================================================
# 11. MissingGreenlet Elimination via Explicit Repository Injection
# ==============================================================================

class TestMissingGreenletElimination:
    """Verify that MissingGreenlet cannot occur when timetable relationship is lazy."""

    @pytest.mark.asyncio
    async def test_missing_greenlet_prevented_by_entry_repo(
        self, student_batch1
    ):
        """
        When timetable.entries would raise MissingGreenlet, injecting entry_repo
        safely loads entries via explicit async database query.
        """
        class LazyLoadedTimetableDouble:
            id = uuid4()
            student_id = student_batch1.id
            status = TimetableStatus.CONFIRMED

            @property
            def entries(self):
                from sqlalchemy.exc import MissingGreenlet
                raise MissingGreenlet("greenlet_spawn has not been called; can't call in sync context")

        lazy_tt = LazyLoadedTimetableDouble()
        mock_tt_repo = AsyncMock()
        mock_tt_repo.get_latest_confirmed_for_student = AsyncMock(return_value=lazy_tt)

        mock_entry = TimetableEntry(
            id=uuid4(),
            timetable_id=lazy_tt.id,
            day_of_week=0,
            start_time=time(9, 0),
            end_time=time(10, 0),
            course_code="25PC1CS201",
            activity_name="Operating Systems",
            activity_type=ActivityType.ACADEMIC,
        )

        mock_entry_repo = AsyncMock()
        mock_entry_repo.get_for_timetable = AsyncMock(return_value=[mock_entry])

        mock_student_repo = AsyncMock()
        mock_student_repo.get_by_id = AsyncMock(return_value=student_batch1)

        resolver = ScenarioResolver(
            timetable_repo=mock_tt_repo,
            student_repo=mock_student_repo,
            entry_repo=mock_entry_repo,
        )

        # Resolving scenario must use entry_repo and NEVER trigger lazy-load on lazy_tt.entries
        scenario = await resolver.resolve_scenario(
            student_id=student_batch1.id,
            days_to_skip=["2026-10-05"],
            custom_today=date(2026, 10, 4),
        )

        assert len(scenario.session_actions) == 1
        assert scenario.session_actions[0].course_code == "25PC1CS201"
        assert scenario.session_actions[0].action == SimulationAction.SKIP
        mock_entry_repo.get_for_timetable.assert_awaited_once_with(lazy_tt.id)

