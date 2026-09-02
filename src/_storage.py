"""(내부) SQLite 연결과 스키마, 스캔/매칭 기록의 저장을 담당한다.

읽기(조회)는 retriever.py가 담당하며, 이 모듈은 연결 생성과 쓰기를 맡는다.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "scan.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source        TEXT NOT NULL,
  started_at    TEXT NOT NULL,
  finished_at   TEXT,
  urls_total    INTEGER NOT NULL,
  urls_visited  INTEGER NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS matches (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id       INTEGER NOT NULL REFERENCES scans(id),
  pattern_name  TEXT NOT NULL,
  matched_value TEXT NOT NULL,
  location      TEXT NOT NULL,
  url           TEXT NOT NULL,
  detail_json   TEXT,
  matched_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_matches_scan_id      ON matches(scan_id);
CREATE INDEX IF NOT EXISTS idx_matches_pattern_name ON matches(pattern_name);
CREATE INDEX IF NOT EXISTS idx_matches_url          ON matches(url);
CREATE INDEX IF NOT EXISTS idx_matches_matched_at   ON matches(matched_at);
"""


def now_iso() -> str:
    """저장·조회에 공통으로 쓰는 UTC ISO 8601 타임스탬프를 만든다."""
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    """data/scan.db에 연결하고 스키마를 보장한 커넥션을 돌려준다.

    data 디렉토리와 테이블이 없으면 만든다. 행은 dict처럼 접근할 수 있게
    sqlite3.Row로 반환하도록 설정한다.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def start_scan(conn: sqlite3.Connection, source: str, urls_total: int) -> int:
    """스캔 시작을 scans 테이블에 기록하고 새 scan_id를 돌려준다."""
    cursor = conn.execute(
        "INSERT INTO scans (source, started_at, urls_total, urls_visited, status)"
        " VALUES (?, ?, ?, 0, 'running')",
        (source, now_iso(), urls_total),
    )
    conn.commit()
    return int(cursor.lastrowid)


def finish_scan(
    conn: sqlite3.Connection, scan_id: int, urls_visited: int, status: str
) -> None:
    """스캔 종료 시각과 방문 성공 건수, 최종 상태를 기록한다.

    status는 'completed'(1건 이상 방문 성공) 또는 'failed'(전부 실패)다.
    """
    conn.execute(
        "UPDATE scans SET finished_at = ?, urls_visited = ?, status = ? WHERE id = ?",
        (now_iso(), urls_visited, status, scan_id),
    )
    conn.commit()


def save_match(conn: sqlite3.Connection, scan_id: int, match: dict) -> None:
    """매칭 1건을 matches 테이블에 저장한다.

    matched_value는 가공 없이 원본 그대로 저장한다. detail은 JSON 문자열로 직렬화한다.
    """
    conn.execute(
        "INSERT INTO matches"
        " (scan_id, pattern_name, matched_value, location, url, detail_json, matched_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            scan_id,
            match["pattern_name"],
            match["matched_value"],
            match["location"],
            match["url"],
            json.dumps(match.get("detail") or {}, ensure_ascii=False),
            match.get("matched_at") or now_iso(),
        ),
    )
    conn.commit()
