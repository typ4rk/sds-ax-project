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
  chunks_total   INTEGER NOT NULL,
  chunks_scanned INTEGER NOT NULL DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS collect (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  url           TEXT NOT NULL,
  location      TEXT NOT NULL,
  content       TEXT NOT NULL,
  detail_json   TEXT,
  collected_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_matches_scan_id      ON matches(scan_id);
CREATE INDEX IF NOT EXISTS idx_matches_pattern_name ON matches(pattern_name);
CREATE INDEX IF NOT EXISTS idx_matches_url          ON matches(url);
CREATE INDEX IF NOT EXISTS idx_matches_matched_at   ON matches(matched_at);

CREATE INDEX IF NOT EXISTS idx_collect_url          ON collect(url);
CREATE INDEX IF NOT EXISTS idx_collect_location     ON collect(location);
CREATE INDEX IF NOT EXISTS idx_collect_collected_at ON collect(collected_at);
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


def start_scan(conn: sqlite3.Connection, source: str, chunks_total: int) -> int:
    """스캔 시작을 scans 테이블에 기록하고 새 scan_id를 돌려준다."""
    cursor = conn.execute(
        "INSERT INTO scans (source, started_at, chunks_total, chunks_scanned, status)"
        " VALUES (?, ?, ?, 0, 'running')",
        (source, now_iso(), chunks_total),
    )
    conn.commit()
    return int(cursor.lastrowid)


def finish_scan(
    conn: sqlite3.Connection, scan_id: int, chunks_scanned: int, status: str
) -> None:
    """스캔 종료 시각과 검사한 덩어리 수, 최종 상태를 기록한다.

    status는 'completed'(1건 이상 검사) 또는 'failed'(하나도 못 함)다.
    """
    conn.execute(
        "UPDATE scans SET finished_at = ?, chunks_scanned = ?, status = ? WHERE id = ?",
        (now_iso(), chunks_scanned, status, scan_id),
    )
    conn.commit()


def save_collected(
    conn: sqlite3.Connection,
    location: str,
    content: str,
    url: str,
    detail: dict,
) -> None:
    """수집 덩어리 1건을 collect 테이블에 저장한다.

    _browser의 emit(위치, 텍스트, URL, 부가정보)과 같은 모양으로 받는다. 그래서
    수집 경로와 저장 형식이 어긋날 수 없고, 나중에 run_scan이 그대로 되돌려 검사한다.

    matches와 달리 정규식 매칭을 거치지 않은 원본이다. location은 matches와 같은
    어휘를 쓴다: header / body / request_body / cookie / console.
    """
    conn.execute(
        "INSERT INTO collect (url, location, content, detail_json, collected_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (url, location, content, json.dumps(detail or {}, ensure_ascii=False), now_iso()),
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
