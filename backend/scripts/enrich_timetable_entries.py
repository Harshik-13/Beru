"""Enrich confirmed timetable entries with verified room and faculty metadata from PDF legend."""

import asyncio
import sys
import uuid

# Ensure backend package is in python path
sys.path.insert(0, "backend")

from app.core.database import async_session_factory
from app.repositories.timetable import TimetableEntryRepository, TimetableRepository

# Map course/activity keywords to verified room and faculty from timetable legend
LEGEND_METADATA: dict[str, dict[str, str]] = {
    "PSA": {
        "room": "E-505",
        "faculty": "Dr. V. Ganesh Kumar",
        "course_code": "25BS1MT204",
    },
    "OOPJ": {
        "room": "E-505",
        "faculty": "Mrs. G. Ashalatha",
        "course_code": "25PC1CS201",
    },
    "CN": {
        "room": "E-505",
        "faculty": "Mr. Mohd Ashfakul Hasan",
        "course_code": "25PC1CY201",
    },
    "OS": {
        "room": "E-505",
        "faculty": "Dr. Swathi Sambangi",
        "course_code": "25PC1IT204",
    },
    "ES": {
        "room": "E-505",
        "faculty": "Dr. K. Archana",
        "course_code": "25MC1ES201",
    },
    "DT": {
        "room": "E-505",
        "faculty": "Faculty Team",
        "course_code": "25MN1DT201",
    },
    "MTP": {
        "room": "E-505",
        "faculty": "Placement Team",
        "course_code": "MTP",
    },
    "DV LAB": {
        "room": "E-505",
        "faculty": "Dr. C. Jyotsna / Ms. P. Meenakshi",
        "course_code": "25PW4CY201",
    },
    "CM LAB": {
        "room": "E-417",
        "faculty": "Dr. V. Ganesh Kumar / Dr. B. Nagamalleswari",
        "course_code": "25BS2MT211",
    },
    "OOPJ LAB": {
        "room": "E-502",
        "faculty": "Mrs. G. Ashalatha / Mrs. Jothsna Duggirala",
        "course_code": "25PC2CS201",
    },
    "CN LAB": {
        "room": "E-332",
        "faculty": "Mr. Mohd Ashfakul Hasan / Mr. Y. Manohar Reddy",
        "course_code": "25PC2CY201",
    },
    "OS LAB": {
        "room": "E-431",
        "faculty": "Dr. Swathi Sambangi",
        "course_code": "25PC2IT204",
    },
    "CF LAB": {
        "room": "E-502",
        "faculty": "Dr. Swathi Sambangi",
        "course_code": "25PC2CY202",
    },
    "SPORTS": {
        "room": "Sports Ground",
        "faculty": "Physical Education Dept",
        "course_code": "SPORTS",
    },
    "LIBRARY": {
        "room": "Central Library",
        "faculty": "Library Staff",
        "course_code": "LIB",
    },
    "ECA": {
        "room": "E-505",
        "faculty": "Cultural Committee",
        "course_code": "ECA",
    },
}


async def enrich_confirmed_timetable():
    student_id = uuid.UUID("90627ae2-5050-444f-8be0-00dbb1fef469")
    async with async_session_factory() as session:
        t_repo = TimetableRepository(session)
        e_repo = TimetableEntryRepository(session)

        timetable = await t_repo.get_confirmed_for_student(student_id)
        if not timetable:
            print("No confirmed timetable found for student.")
            return

        entries = await e_repo.get_for_timetable(timetable.id)
        print(f"Found {len(entries)} entries for confirmed timetable {timetable.id}")

        updated_count = 0
        for entry in entries:
            act_name = entry.activity_name.strip().upper()
            meta = LEGEND_METADATA.get(act_name)
            if not meta:
                # Fallback partial match (e.g. 'OOPJ' in 'OOPJ LAB' handling: exact match preferred first)
                for k, v in LEGEND_METADATA.items():
                    if k == act_name:
                        meta = v
                        break

            if meta:
                entry.room = meta["room"]
                entry.faculty = meta["faculty"]
                entry.course_code = meta.get("course_code")
                updated_count += 1
            elif not entry.room and timetable.default_classroom:
                entry.room = timetable.default_classroom
                updated_count += 1

        await session.commit()
        print(f"Successfully enriched {updated_count} entries with verified room/faculty metadata.")


if __name__ == "__main__":
    asyncio.run(enrich_confirmed_timetable())
