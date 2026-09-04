"""저장된 매칭 기록을 SQLite에서 조건으로 걸러오는 단순 조회 헬퍼.

임베딩이나 의미 기반 검색(RAG)이 아니다 — SQL WHERE 절만 구성하는 조회 전용 모듈이며,
데이터를 변경하지 않는다.
"""

import json
from datetime import date, timedelta

from src import _storage

# collect 테이블에서 직접 조회할 수 있는 텍스트 컬럼.
# 컬럼명은 SQL 파라미터로 넘길 수 없어 문자열로 끼워 넣으므로 화이트리스트로 제한한다.
COLLECT_TEXT_COLUMNS = ("content", "detail_json")


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


def find_distinct_values(
    pattern_name: str | None = None,
    scan_id: int | None = None,
    location: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """저장된 matched_value를 중복 없이 모아 빈도와 함께 돌려준다.

    임베딩이나 의미 기반 검색을 하지 않는다 — GROUP BY로 같은 값을 묶어 등장 횟수와
    서로 다른 리소스 수, 처음·마지막 발견 시각을 세는 집계 조회다.

    정규식 후보를 도출할 때 중요한 것은 같은 값이 몇 번 반복됐는지가 아니라 서로 다른
    값이 몇 종류인지이므로, 빈도로 가중하지 않고 중복을 제거한 목록을 양성 표본으로 쓴다.

    반환 항목: {"matched_value", "hits", "urls", "first_seen", "last_seen"}
    """
    where: list[str] = []
    params: list = []

    if pattern_name:
        where.append("pattern_name = ?")
        params.append(pattern_name)
    if scan_id is not None:
        where.append("scan_id = ?")
        params.append(scan_id)
    if location:
        where.append("location = ?")
        params.append(location)

    sql = (
        "SELECT matched_value, COUNT(*) AS hits, COUNT(DISTINCT url) AS urls,"
        " MIN(matched_at) AS first_seen, MAX(matched_at) AS last_seen"
        " FROM matches"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY matched_value ORDER BY hits DESC, matched_value LIMIT ?"
    params.append(max(1, int(limit)))

    conn = _storage.connect()
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def find_context_texts(scan_id: int | None = None, limit: int = 2000) -> list[str]:
    """정규식이 적용된 적 없는 부수 텍스트를 코퍼스로 모은다.

    수집 원문은 저장하지 않으므로, 후보 정규식의 추가 탐지력을 편향 없이 재려면
    "패턴이 만들어낸 값이 아닌" 텍스트가 필요하다. matches.url과 detail_json 안의
    문자열 값(page_url 등)이 여기 해당한다 — 둘 다 매칭의 산출물이 아니라 부수 기록이다.

    matched_value는 일부러 넣지 않는다. 패턴이 이미 잡은 값이라 편향되기 때문이다.
    """
    sql = "SELECT url, detail_json FROM matches"
    params: list = []
    if scan_id is not None:
        sql += " WHERE scan_id = ?"
        params.append(scan_id)
    sql += " LIMIT ?"
    params.append(max(1, int(limit)))

    conn = _storage.connect()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    texts: set[str] = set()
    for row in rows:
        if row["url"]:
            texts.add(row["url"])
        texts.update(_leaf_strings(row["detail_json"]))
    return sorted(texts)


def find_collected(limit: int = 5000, location: str | None = None) -> list[dict]:
    """collect 테이블에 저장된 관측 데이터를 저장 순서대로 돌려준다.

    collect_traffic이 모아 둔 원본이며 detect_matches의 탐지 대상이 된다. detail_json은
    dict로 파싱해 detail 키로 바꿔 넘긴다(파싱 실패 시 빈 dict).

    location을 주면 그 위치만 SQL 단계에서 걸러 온다. 특정 위치(예: request_body)는
    전체의 일부이므로, 파이썬에서 걸러내면 limit이 먼저 잘려 원하는 행을 놓친다.

    반환 항목: {"id", "url", "location", "content", "detail", "collected_at"}
    """
    sql = "SELECT id, url, location, content, detail_json, collected_at FROM collect"
    params: list = []
    if location:
        sql += " WHERE location = ?"
        params.append(location)
    sql += " ORDER BY id LIMIT ?"
    params.append(max(1, int(limit)))

    conn = _storage.connect()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    collected = []
    for row in rows:
        record = dict(row)
        raw = record.pop("detail_json", None)
        try:
            record["detail"] = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            record["detail"] = {}
        collected.append(record)
    return collected


def find_collect_column(
    column: str,
    contains: str | None = None,
    location: str | None = None,
    limit: int = 5000,
) -> list[dict]:
    """collect 테이블에서 지정한 텍스트 컬럼만 SQL로 걸러 가져온다.

    분석 요청이 컬럼을 지목하면(예: "detail_json 컬럼에서 sectionId") 그 컬럼을 먼저
    조회하고 돌아온 결과에만 귀납을 돌리기 위한 조회 함수다. detail_json을 dict로
    파싱해 detail 키로 넘기는 find_collected와 달리, 여기서는 컬럼 원문을 그대로 준다.

    contains를 주면 그 문자열을 포함한 행만, location을 주면 그 위치의 행만 SQL
    단계에서 걸러 온다. 파이썬에서 걸러내면 limit이 먼저 잘려 원하는 행을 놓친다.

    반환 항목: {"id", "url", "location", "text"}
    """
    where, params = _collect_column_where(column, contains, location)
    sql = (
        f"SELECT id, url, location, {column} AS text FROM collect"
        f"{where} ORDER BY id LIMIT ?"
    )
    params.append(max(1, int(limit)))

    conn = _storage.connect()
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def count_collect_column(column: str, contains: str) -> int:
    """지정한 컬럼에 그 문자열이 들어 있는 collect 행 수를 센다.

    지목한 컬럼에서 결과가 0건일 때 "다른 컬럼에는 있는가"를 확인해 알려주기 위한
    집계다. limit에 잘리지 않도록 조회가 아니라 COUNT로 센다.
    """
    where, params = _collect_column_where(column, contains, None)
    conn = _storage.connect()
    try:
        return conn.execute(f"SELECT COUNT(*) FROM collect{where}", params).fetchone()[0]
    finally:
        conn.close()


def _collect_column_where(
    column: str, contains: str | None, location: str | None
) -> tuple[str, list]:
    """컬럼 이름을 검증하고 WHERE 절과 파라미터를 만든다.

    컬럼명은 SQL에 그대로 끼워 넣어야 하므로, 화이트리스트에 없으면 조회 전에 막는다.
    """
    if column not in COLLECT_TEXT_COLUMNS:
        raise ValueError(
            f"collect 테이블에서 조회할 수 있는 텍스트 컬럼이 아닙니다: {column!r}"
            f" (가능: {', '.join(COLLECT_TEXT_COLUMNS)})"
        )

    where = [f"{column} IS NOT NULL", f"{column} != ''"]
    params: list = []
    if contains:
        where.append(f"{column} LIKE ?")
        params.append(f"%{contains}%")
    if location:
        where.append("location = ?")
        params.append(location)
    return " WHERE " + " AND ".join(where), params


def _leaf_strings(raw_detail) -> list[str]:
    """detail_json 안에 들어 있는 문자열 값만 평평하게 뽑아낸다."""
    if not raw_detail:
        return []
    try:
        detail = json.loads(raw_detail)
    except json.JSONDecodeError:
        return []
    if not isinstance(detail, dict):
        return []
    return [value for value in detail.values() if isinstance(value, str) and value]


def _to_dict(row) -> dict:
    """sqlite3.Row 한 줄을 dict로 바꾸고 detail_json을 다시 파싱한다."""
    record = dict(row)
    raw_detail = record.pop("detail_json", None)
    try:
        record["detail"] = json.loads(raw_detail) if raw_detail else {}
    except json.JSONDecodeError:
        record["detail"] = {"raw": raw_detail}
    return record
