"""SQLite project repository compatible with both local OS and Streamlit Community Cloud (FT-24)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.demos import get_demo_projects
from core.models import DepartmentInput, PlannerConfig, ReserveInput


@dataclass
class ProjectRecord:
    """Stored project entity."""

    id: int
    name: str
    description: str
    config: PlannerConfig
    departments: list[DepartmentInput]
    reserves: list[ReserveInput]
    created_at: str
    updated_at: str


def resolve_default_db_path() -> Path:
    """Return a writable SQLite path for local runs or Streamlit Community Cloud."""
    env_path = os.environ.get("SMART_IP_PLANNER_DB")
    if env_path:
        p = Path(env_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    local_dir = Path(__file__).resolve().parent.parent / "data"
    try:
        local_dir.mkdir(parents=True, exist_ok=True)
        probe = local_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return local_dir / "smart_ip_planner.db"
    except OSError:
        tmp_dir = Path(tempfile.gettempdir()) / "smart_ip_planner"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir / "smart_ip_planner.db"


class ProjectRepository:
    """CRUD repository for Smart IP Planner projects in SQLite."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else resolve_default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL,
                    departments_json TEXT NOT NULL,
                    reserves_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def seed_demos_if_empty(self) -> list[int]:
        """Populate the 3 built-in demo projects when the DB has no projects."""
        if self.list_projects():
            return []
        ids: list[int] = []
        for demo in get_demo_projects():
            pid = self.create_project(
                name=demo["name"],
                description=demo["description"],
                config=demo["config"],
                departments=demo["departments"],
                reserves=demo["reserves"],
            )
            ids.append(pid)
        return ids

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ProjectRecord:
        cfg = PlannerConfig.from_dict(json.loads(row["config_json"]))
        depts = [DepartmentInput.from_dict(d) for d in json.loads(row["departments_json"])]
        reserves = [ReserveInput.from_dict(r) for r in json.loads(row["reserves_json"])]
        return ProjectRecord(
            id=int(row["id"]),
            name=str(row["name"]),
            description=str(row["description"]),
            config=cfg,
            departments=depts,
            reserves=reserves,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def list_projects(self) -> list[ProjectRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY id ASC").fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_project(self, project_id: int) -> Optional[ProjectRecord]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def create_project(
        self,
        name: str,
        config: PlannerConfig,
        departments: list[DepartmentInput],
        reserves: list[ReserveInput],
        description: str = "",
    ) -> int:
        now = self._now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO projects (name, description, config_json, departments_json, reserves_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name.strip() or "Жаңа жоба",
                    description.strip(),
                    json.dumps(config.to_dict(), ensure_ascii=False),
                    json.dumps([d.to_dict() for d in departments], ensure_ascii=False),
                    json.dumps([r.to_dict() for r in reserves], ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def update_project(
        self,
        project_id: int,
        config: PlannerConfig,
        departments: list[DepartmentInput],
        reserves: list[ReserveInput],
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        existing = self.get_project(project_id)
        if not existing:
            return False
        new_name = name.strip() if name is not None and name.strip() else existing.name
        new_desc = description.strip() if description is not None else existing.description
        now = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE projects
                SET name = ?, description = ?, config_json = ?, departments_json = ?, reserves_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_name,
                    new_desc,
                    json.dumps(config.to_dict(), ensure_ascii=False),
                    json.dumps([d.to_dict() for d in departments], ensure_ascii=False),
                    json.dumps([r.to_dict() for r in reserves], ensure_ascii=False),
                    now,
                    project_id,
                ),
            )
            conn.commit()
        return True

    def rename_project(self, project_id: int, new_name: str) -> bool:
        if not new_name.strip():
            return False
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
                (new_name.strip(), self._now_iso(), project_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def copy_project(self, project_id: int, copy_suffix: str = " (көшірме)") -> Optional[int]:
        existing = self.get_project(project_id)
        if not existing:
            return None
        return self.create_project(
            name=f"{existing.name}{copy_suffix}",
            description=existing.description,
            config=existing.config,
            departments=existing.departments,
            reserves=existing.reserves,
        )

    def delete_project(self, project_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
            return cur.rowcount > 0
