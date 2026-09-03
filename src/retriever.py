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


def find_collected(limit: int = 5000, with_body: bool = False) -> list[dict]:
    """collect 테이블에 저장된 요청 트래픽을 저장 순서대로 돌려준다.

    collect_traffic이 모아 둔 원본 요청이며, urls.txt 없이 탐지할 때 입력이 된다.
    headers_json 컬럼은 dict로 파싱해 headers 키로 바꿔 넘긴다(파싱 실패 시 빈 dict).
    호출하는 쪽은 headers_json이 아니라 headers를 봐야 한다.

    with_body=True면 본문이 있는 행만 SQL 단계에서 걸러 온다. 본문 있는 행은 전체의
    일부이므로(대부분 GET), 파이썬에서 걸러내면 limit이 먼저 잘려 본문 행을 놓친다.

    반환 항목: {"id", "url", "method", "headers", "body", "time"}
    """
    sql = "SELECT id, url, method, headers_json, body, time FROM collect"
    if with_body:
        sql += " WHERE body IS NOT NULL AND body <> ''"
    sql += " ORDER BY id LIMIT ?"

    conn = _storage.connect()
    try:
        rows = conn.execute(sql, (max(1, int(limit)),)).fetchall()
    finally:
        conn.close()

    collected = []
    for row in rows:
        record = dict(row)
        raw = record.pop("headers_json", None)
        try:
            record["headers"] = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            record["headers"] = {}
        collected.append(record)
    return collected


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
