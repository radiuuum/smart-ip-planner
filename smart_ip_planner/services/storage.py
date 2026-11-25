"""SQLite storage (Section 7.3) and JSON import/export (Section 7.4)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEMO_FILE = Path(__file__).resolve().parent.parent / "data" / "demo_projects.json"


def load_demo_projects() -> list[dict[str, Any]]:
    """Load the 3 built-in synthetic demo projects from data/demo_projects.json (Section 9)."""
    raw = DEMO_FILE.read_text(encoding="utf-8")
    return json.loads(raw)


def resolve_db_path() -> Path:
    """Resolve a writable SQLite path for both local macOS/Windows/Linux and Streamlit Cloud."""
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
        return local_dir / "projects.db"
    except OSError:
        tmp_dir = Path(tempfile.gettempdir()) / "smart_ip_planner"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return tmp_dir / "projects.db"


def export_project_json(project_data: dict[str, Any]) -> str:
    """Serialize project dict strictly in Section 7.4 JSON format."""
    payload = {
        "name": str(project_data.get("name", "")).strip() or "Жаңа жоба",
        "base": str(project_data.get("base", "192.168.1.0/24")).strip(),
        "method": str(project_data.get("method", "VLSM")).upper(),
        "gateway_policy": str(project_data.get("gateway_policy", "first")).lower(),
        "default_reserve": int(project_data.get("default_reserve", 20)),
        "departments": [
            {
                "name": str(d.get("name", "")).strip(),
                "vlan_id": None if d.get("vlan_id") in (None, "", "None") else int(d["vlan_id"]),
                "hosts": int(d.get("hosts", 1)),
                "reserve_pct": int(d.get("reserve_pct", 0)),
            }
            for d in project_data.get("departments", [])
        ],
        "reserved": [
            {
                "network": str(r.get("network", "")).strip(),
                "note": str(r.get("note", "")).strip(),
            }
            for r in project_data.get("reserved", [])
            if str(r.get("network", "")).strip()
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def import_project_json(raw_json: str) -> dict[str, Any]:
    """Parse and normalize project JSON strictly following Section 7.4."""
    data = json.loads(raw_json)
    if not isinstance(data, dict) or "base" not in data or "departments" not in data:
        raise ValueError("Invalid project JSON format: expected 'base' and 'departments'")
    return json.loads(export_project_json(data))


class ProjectStorage:
    """SQLite project store using exact schema from Section 7.3."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else resolve_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY,
                    name TEXT UNIQUE,
                    data TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def list_projects(self) -> list[dict[str, Any]]:
        """Return list of saved projects with id, name, updated_at, and parsed data."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, data, updated_at FROM projects ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return [
            {
                "id": int(r["id"]),
                "name": str(r["name"]),
                "data": json.loads(r["data"]),
                "updated_at": str(r["updated_at"]),
            }
            for r in rows
        ]

    def get_project(self, project_id: int) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, data, updated_at FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "data": json.loads(row["data"]),
            "updated_at": str(row["updated_at"]),
        }

    def get_by_name(self, name: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, data, updated_at FROM projects WHERE name = ?", (name.strip(),)
            ).fetchone()
        if not row:
            return None
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "data": json.loads(row["data"]),
            "updated_at": str(row["updated_at"]),
        }

    def save_project(self, project_data: dict[str, Any], project_id: Optional[int] = None) -> int:
        """Create or update a project in SQLite. Raises ValueError if name already taken by another project."""
        name = str(project_data.get("name", "")).strip() or "Жаңа жоба"
        payload = export_project_json({**project_data, "name": name})
        now = self._now()

        with self._connect() as conn:
            if project_id is not None:
                clash = conn.execute(
                    "SELECT id FROM projects WHERE name = ? AND id != ?", (name, project_id)
                ).fetchone()
                if clash:
                    raise ValueError("name_taken")
                conn.execute(
                    "UPDATE projects SET name = ?, data = ?, updated_at = ? WHERE id = ?",
                    (name, payload, now, project_id),
                )
                conn.commit()
                return project_id

            existing = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
            if existing:
                raise ValueError("name_taken")
            cur = conn.execute(
                "INSERT INTO projects (name, data, updated_at) VALUES (?, ?, ?)",
                (name, payload, now),
            )
            conn.commit()
            return int(cur.lastrowid)

    def rename_project(self, project_id: int, new_name: str) -> None:
        clean = new_name.strip()
        if not clean:
            raise ValueError("empty_name")
        proj = self.get_project(project_id)
        if not proj:
            raise ValueError("not_found")
        data = dict(proj["data"])
        data["name"] = clean
        self.save_project(data, project_id=project_id)

    def copy_project(self, project_id: int) -> Optional[int]:
        proj = self.get_project(project_id)
        if not proj:
            return None
        base_name = proj["name"]
        candidate = f"{base_name} (көшірме)"
        idx = 2
        while self.get_by_name(candidate) is not None:
            candidate = f"{base_name} (көшірме {idx})"
            idx += 1
        data = dict(proj["data"])
        data["name"] = candidate
        return self.save_project(data)

    def delete_project(self, project_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
            return cur.rowcount > 0
