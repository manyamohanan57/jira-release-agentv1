import json
import sqlite3
from pathlib import Path

from app.models import ReleaseReadinessReport


class AssessmentStore:
    def __init__(self, path: str = "assessment_history.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _init(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS assessments (
                    assessment_id TEXT PRIMARY KEY,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def save(self, report: ReleaseReadinessReport) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO assessments (assessment_id, report_json, created_at) VALUES (?, ?, ?)",
                (report.report_id, report.model_dump_json(), report.generated_at.isoformat()),
            )

    def get(self, assessment_id: str) -> ReleaseReadinessReport | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT report_json FROM assessments WHERE assessment_id = ?",
                (assessment_id,),
            ).fetchone()
        if not row:
            return None
        return ReleaseReadinessReport.model_validate_json(row[0])
