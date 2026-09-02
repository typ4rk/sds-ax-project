"""저장된 매칭 기록을 SQLite에서 조건으로 걸러오는 단순 조회 헬퍼.

임베딩이나 의미 기반 검색(RAG)이 아니다 — SQL WHERE 절만 구성하는 조회 전용 모듈이며,
데이터를 변경하지 않는다.
"""

import json
from datetime import date, timedelta

from src import _storage


def find_matches(
    pattern_name: str | None = None,
    url_substring: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    scan_id: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """조건에 맞는 매칭 기록을 data/scan.db에서 그대로 조회해 반환한다.

    임베딩이나 의미 기반 검색을 하지 않는다 — 전달된 조건으로 SQL WHERE 절을 구성해
    filtering만 수행하는 단순 조회 함수다. 조건을 하나도 주지 않으면 최근 limit건을 반환한다.

    date_from/date_to는 matched_at(UTC ISO 8601 문자열)과 사전식으로 비교하므로
    "2026-09-01" 같은 날짜 접두사만 넘겨도 동작한다.
    """
    where: list[str] = []
    params: list = []

    if pattern_name:
        where.append("pattern_name = ?")
        params.append(pattern_name)
    if url_substring:
        where.append("url LIKE ?")
        params.append(f"%{url_substring}%")
    if date_from:
        where.append("matched_at >= ?")
        params.append(date_from)
    if date_to:
        # 'YYYY-MM-DD'처럼 날짜만 오면 그날 타임스탬프가 사전식으로 더 커서 전부 빠진다.
        # 그래서 날짜만 온 경우는 다음 날 0시 미만으로 비교해 그날 전체를 포함시킨다.
        if len(date_to) == 10:
            where.append("matched_at < ?")
            params.append((date.fromisoformat(date_to) + timedelta(days=1)).isoformat())
        else:
            where.append("matched_at <= ?")
            params.append(date_to)
    if scan_id is not None:
        where.append("scan_id = ?")
        params.append(scan_id)

    sql = (
        "SELECT id, scan_id, pattern_name, matched_value, location, url, detail_json, matched_at"
        " FROM matches"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY matched_at DESC, id DESC LIMIT ?"
    params.append(max(1, int(limit)))

    conn = _storage.connect()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    return [_to_dict(row) for row in rows]


def _to_dict(row) -> dict:
    """sqlite3.Row 한 줄을 dict로 바꾸고 detail_json을 다시 파싱한다."""
    record = dict(row)
    raw_detail = record.pop("detail_json", None)
    try:
        record["detail"] = json.loads(raw_detail) if raw_detail else {}
    except json.JSONDecodeError:
        record["detail"] = {"raw": raw_detail}
    return record
