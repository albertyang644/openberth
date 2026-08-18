from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from openberth.models import DiscoveredTarget, TargetRow

SCHEMA = """
CREATE TABLE IF NOT EXISTS berths (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    color TEXT,
    sort_order INTEGER DEFAULT 0,
    wezterm_window_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS targets (
    id INTEGER PRIMARY KEY,
    berth_id INTEGER,
    display_name TEXT,
    tmux_session TEXT NOT NULL,
    tmux_window INTEGER NOT NULL,
    tmux_pane INTEGER NOT NULL,
    tmux_target TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'alive',
    last_seen DATETIME,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tmux_session, tmux_window, tmux_pane),
    FOREIGN KEY (berth_id) REFERENCES berths(id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS closed_tvs (
    id INTEGER PRIMARY KEY,
    target_id INTEGER NOT NULL,
    closed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (target_id) REFERENCES targets(id)
);

CREATE TABLE IF NOT EXISTS target_previews (
    target_id INTEGER PRIMARY KEY,
    preview_text TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (target_id) REFERENCES targets(id)
);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def init(self) -> None:
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(targets)").fetchall()}
        if "hidden" not in cols:
            self.conn.execute("ALTER TABLE targets ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
        berth_cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(berths)").fetchall()}
        if "wezterm_window_id" not in berth_cols:
            self.conn.execute("ALTER TABLE berths ADD COLUMN wezterm_window_id TEXT")

    def create_berth(self, name: str, color: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO berths(name, color) VALUES(?, ?)",
            (name, color),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def rename_berth(self, berth_id: int, name: str) -> None:
        self.conn.execute("UPDATE berths SET name = ? WHERE id = ?", (name, berth_id))
        self.conn.commit()

    def get_berth(self, berth_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT id, name, color FROM berths WHERE id = ?", (berth_id,)
        ).fetchone()

    def delete_berth(self, berth_id: int) -> None:
        self.conn.execute("UPDATE targets SET berth_id = NULL WHERE berth_id = ?", (berth_id,))
        self.conn.execute("DELETE FROM berths WHERE id = ?", (berth_id,))
        self.conn.commit()

    def purge_all(self) -> None:
        """Drop every TV and berth, leaving settings intact.

        Discovery repopulates targets from tmux, so deleting rows here is the
        only thing that actually clears out dead ones -- upsert_discovered_targets
        marks a vanished target 'dead' but never removes it, so tombstones
        otherwise accumulate forever.
        """
        self.conn.execute("DELETE FROM target_previews")
        self.conn.execute("DELETE FROM closed_tvs")
        self.conn.execute("DELETE FROM targets")
        self.conn.execute("DELETE FROM berths")
        self.conn.commit()

    def list_berths(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT id, name, color, sort_order FROM berths ORDER BY sort_order, id"
        ).fetchall()

    def set_berth_sort_orders(self, ordered_berth_ids: list[int]) -> None:
        self.conn.executemany(
            "UPDATE berths SET sort_order = ? WHERE id = ?",
            [(i, bid) for i, bid in enumerate(ordered_berth_ids)],
        )
        self.conn.commit()

    def set_berth_color(self, berth_id: int, color: str) -> None:
        self.conn.execute("UPDATE berths SET color = ? WHERE id = ?", (color, berth_id))
        self.conn.commit()

    def get_berth_window(self, berth_id: int) -> str | None:
        row = self.conn.execute(
            "SELECT wezterm_window_id FROM berths WHERE id = ?", (berth_id,)
        ).fetchone()
        return str(row["wezterm_window_id"]) if row and row["wezterm_window_id"] else None

    def set_berth_window(self, berth_id: int, window_id: str | None) -> None:
        self.conn.execute(
            "UPDATE berths SET wezterm_window_id = ? WHERE id = ?", (window_id, berth_id)
        )
        self.conn.commit()

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def get_setting(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def set_target_berth(self, target_id: int, berth_id: int | None) -> None:
        self.conn.execute(
            "UPDATE targets SET berth_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (berth_id, target_id),
        )
        self.conn.commit()

    def set_sort_orders(self, ordered_target_ids: list[int]) -> None:
        self.conn.executemany(
            "UPDATE targets SET sort_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            [(i, tid) for i, tid in enumerate(ordered_target_ids)],
        )
        self.conn.commit()

    def rename_target(self, target_id: int, display_name: str) -> None:
        self.conn.execute(
            "UPDATE targets SET display_name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (display_name, target_id),
        )
        self.conn.commit()

    def close_tv(self, target_id: int) -> None:
        self.conn.execute("UPDATE targets SET hidden = 1 WHERE id = ?", (target_id,))
        self.conn.execute("INSERT INTO closed_tvs(target_id) VALUES(?)", (target_id,))
        self.conn.commit()

    def hide_target(self, target_id: int) -> None:
        self.conn.execute("UPDATE targets SET hidden = 1 WHERE id = ?", (target_id,))
        self.conn.commit()

    def restore_last_closed_tv(self) -> int | None:
        row = self.conn.execute(
            "SELECT id, target_id FROM closed_tvs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        target_id = int(row["target_id"])
        self.conn.execute("UPDATE targets SET hidden = 0 WHERE id = ?", (target_id,))
        self.conn.execute("DELETE FROM closed_tvs WHERE id = ?", (int(row["id"]),))
        self.conn.commit()
        return target_id

    def set_target_notes(self, target_id: int, notes: str | None) -> None:
        self.conn.execute(
            "UPDATE targets SET notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (notes, target_id),
        )
        self.conn.commit()

    def upsert_discovered_targets(self, discovered: list[DiscoveredTarget]) -> None:
        now = datetime.now(UTC).isoformat()
        keys = {(d.tmux_session, d.tmux_window, d.tmux_pane) for d in discovered}

        for d in discovered:
            self.conn.execute(
                "INSERT INTO targets("
                "display_name, tmux_session, tmux_window, tmux_pane, tmux_target, status, last_seen"
                ") VALUES (?, ?, ?, ?, ?, 'alive', ?) "
                "ON CONFLICT(tmux_session, tmux_window, tmux_pane) DO UPDATE SET "
                "tmux_target=excluded.tmux_target, status='alive', last_seen=excluded.last_seen, "
                "updated_at=CURRENT_TIMESTAMP",
                (None, d.tmux_session, d.tmux_window, d.tmux_pane, d.tmux_target, now),
            )

        rows = self.conn.execute(
            "SELECT tmux_session, tmux_window, tmux_pane FROM targets"
        ).fetchall()
        for row in rows:
            key = (row["tmux_session"], row["tmux_window"], row["tmux_pane"])
            if key not in keys:
                self.conn.execute(
                    "UPDATE targets SET status='dead', updated_at=CURRENT_TIMESTAMP WHERE "
                    "tmux_session = ? AND tmux_window = ? AND tmux_pane = ?",
                    key,
                )
        self.conn.commit()

    def search_targets(self, query: str) -> list[sqlite3.Row]:
        q = f"%{query.lower()}%"
        return self.conn.execute(
            "SELECT t.*, b.name AS berth_name FROM targets t "
            "LEFT JOIN berths b ON b.id = t.berth_id "
            "WHERE lower(COALESCE(t.display_name, '')) LIKE ? "
            "OR lower(t.tmux_target) LIKE ? "
            "OR lower(COALESCE(b.name, 'ungrouped')) LIKE ? "
            "ORDER BY t.status DESC, t.last_seen DESC",
            (q, q, q),
        ).fetchall()

    def list_targets(self, include_hidden: bool = True) -> list[TargetRow]:
        where = "" if include_hidden else "WHERE hidden = 0"
        rows = self.conn.execute(
            f"SELECT * FROM targets {where} ORDER BY berth_id IS NULL DESC, berth_id, sort_order, id"
        ).fetchall()
        out: list[TargetRow] = []
        for row in rows:
            last_seen = None
            if row["last_seen"]:
                last_seen = datetime.fromisoformat(str(row["last_seen"]))
            out.append(
                TargetRow(
                    id=int(row["id"]),
                    berth_id=row["berth_id"],
                    display_name=row["display_name"],
                    tmux_session=str(row["tmux_session"]),
                    tmux_window=int(row["tmux_window"]),
                    tmux_pane=int(row["tmux_pane"]),
                    tmux_target=str(row["tmux_target"]),
                    sort_order=int(row["sort_order"]),
                    hidden=bool(row["hidden"]),
                    status=str(row["status"]),
                    last_seen=last_seen,
                    notes=row["notes"],
                )
            )
        return out

    def berth_health(self) -> dict[int | None, tuple[int, int]]:
        rows = self.conn.execute(
            "SELECT berth_id, "
            "SUM(CASE WHEN status='alive' THEN 1 ELSE 0 END) AS alive_count, "
            "COUNT(*) AS total_count "
            "FROM targets GROUP BY berth_id"
        ).fetchall()
        return {
            row["berth_id"]: (int(row["alive_count"]), int(row["total_count"]))
            for row in rows
        }

    def target_activity_map(self, target_id: int, width: int = 16, height: int = 1) -> str:
        row = self.conn.execute(
            "SELECT status, last_seen FROM targets WHERE id = ?", (target_id,)
        ).fetchone()
        if row is None:
            return _activity_fill(".", width, height)
        if row["status"] == "dead":
            return _activity_fill(".", width, height)
        preview = self.conn.execute(
            "SELECT preview_text FROM target_previews WHERE target_id = ?",
            (target_id,),
        ).fetchone()
        if preview is not None:
            return _activity_map_from_text(str(preview["preview_text"]), width, height)
        if row["last_seen"] is None:
            return _activity_fill("-", width, height)
        return _activity_fill("#", width, height)

    def set_preview(self, target_id: int, text: str) -> None:
        self.conn.execute(
            "INSERT INTO target_previews(target_id, preview_text, updated_at) VALUES(?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(target_id) DO UPDATE SET preview_text=excluded.preview_text, updated_at=CURRENT_TIMESTAMP",
            (target_id, text),
        )
        self.conn.commit()

    def get_preview(self, target_id: int) -> tuple[str | None, datetime | None]:
        row = self.conn.execute(
            "SELECT preview_text, updated_at FROM target_previews WHERE target_id = ?",
            (target_id,),
        ).fetchone()
        if row is None:
            return None, None
        updated_at = None
        if row["updated_at"]:
            updated_at = datetime.fromisoformat(str(row["updated_at"]).replace(" ", "T"))
        return str(row["preview_text"]), updated_at


def _activity_fill(char: str, width: int, height: int = 1) -> str:
    width = max(1, width)
    height = max(1, height)
    return "\n".join(char * width for _ in range(height))


def _activity_map_from_text(text: str, width: int, height: int = 1) -> str:
    width = max(1, width)
    height = max(1, height)
    source_lines = text.splitlines()[-height:]
    rows: list[str] = []
    for line in source_lines:
        clipped = line[-width:]
        cells = ["#" if not ch.isspace() else "." for ch in clipped]
        rows.append(("." * (width - len(cells))) + "".join(cells))
    while len(rows) < height:
        rows.insert(0, "." * width)
    return "\n".join(rows)
