"""에이전트에 노출되는 도메인 도구 정의.

이 파일의 역할은 "도구 함수의 정의와 고정된 실행 순서"뿐이다.
브라우저 제어/매칭/저장/알림/조회의 실제 구현은
_browser.py / _matcher.py / _storage.py / _notify.py / retriever.py에 위임한다.
"""

import json
import re
from collections import Counter
from pathlib import Path

from src import _browser, _induce, _matcher, _notify, _storage, retriever

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
# suggest_patterns가 한 패턴에 대해 돌려줄 최대 후보 수.
MAX_CANDIDATES = 5
PATTERNS_PATH = DATA_DIR / "patterns.json"


def detect_matches() -> dict:
    """collect 테이블에 모아 둔 트래픽에서 등록된 정규식 패턴을 탐지한다.

    collect_traffic이 수집해 둔 원본 관측 데이터를 대상으로 하므로 브라우저를 띄우지
    않고 네트워크도 쓰지 않는다. 수집 당시의 상태(로그인 후 페이지 포함)가 그대로
    검사되고, 같은 데이터로 몇 번 돌려도 결과가 같다.

    내부적으로 다음을 고정 순서로 실행한다:
    1) data/patterns.json 로드 및 검증
    2) collect 테이블을 저장 순서대로 읽어 filters를 통과한 것만 정규식으로 매칭
    3) 매칭 발생 즉시 콘솔에 출력
    4) scans/matches를 data/scan.db에 저장

    반환값은 scan_id, source, chunks_total, chunks_scanned, status,
    매칭 건수 요약, method_filter를 포함한다.
    """
    config = _load_config()
    patterns = _matcher.compile_patterns(config.get("patterns", []))
    methods = _method_filter(config.get("filters") or {})

    rows = retriever.find_collected()
    if not rows:
        raise ValueError(
            "collect 테이블이 비어 있어 탐지할 대상이 없습니다."
            " collect_traffic으로 트래픽을 먼저 수집하세요."
        )

    source = "data/scan.db#collect"
    conn = _storage.connect()
    scan_id = _storage.start_scan(conn, source, len(rows))

    tally = _new_tally()
    try:
        for row in rows:
            detail = {**row["detail"], "collect_id": row["id"]}
            _record_chunk(
                conn, scan_id, patterns, methods, tally,
                row["location"], row["content"], row["url"], detail,
            )
    finally:
        status = _finish(conn, scan_id, tally["chunks"])

    return _scan_result(scan_id, source, len(rows), tally["chunks"], status, methods, tally)


def _new_tally() -> dict:
    """두 탐지 경로가 공유하는 집계 상자를 만든다."""
    return {"chunks": 0, "filtered": 0, "hits": 0,
            "by_pattern": Counter(), "by_location": Counter()}


def _record_chunk(
    conn, scan_id: int, patterns: list, methods: set | None, tally: dict,
    location: str, text: str, url: str, detail: dict,
) -> None:
    """수집 덩어리 한 건을 필터 → 매칭 → 즉시 출력 → 저장까지 처리한다.

    브라우저 방문 경로와 collect 테이블 경로가 이 함수를 공유하므로, 두 경로의
    필터 적용과 저장 방식이 어긋날 수 없다.
    """
    tally["chunks"] += 1
    if methods is not None and detail.get("method") not in methods:
        # filters.methods에 걸리지 않은 덩어리는 매칭 대상에서 뺀다.
        # method가 없는 수집 항목(응답 헤더/바디/쿠키/콘솔)도 여기서 제외된다.
        tally["filtered"] += 1
        return
    found = _matcher.scan_text(patterns, text, location, url, detail)
    tally["hits"] += len(found)
    # 수집 원본을 먼저 보여준다 (SCAN_TRACE=1일 때만).
    _notify.notify_collected(location, text, url, detail, len(found))
    for match in found:
        # 알림이 저장보다 먼저다 — 매칭 시점과 출력 시점 사이를 벌리지 않는다.
        _notify.notify_match(match)
        _storage.save_match(conn, scan_id, match)
        tally["by_pattern"][match["pattern_name"]] += 1
        tally["by_location"][match["location"]] += 1


def _finish(conn, scan_id: int, processed: int) -> str:
    """scans 행을 마무리하고 커넥션을 닫는다. 예외 중에도 running으로 남기지 않는다."""
    status = "completed" if processed > 0 else "failed"
    try:
        _storage.finish_scan(conn, scan_id, processed, status)
    finally:
        # 상태 기록이 실패해도 커넥션은 반드시 닫는다.
        conn.close()
    return status


def _scan_result(
    scan_id: int, source: str, total: int, processed: int, status: str,
    methods: set | None, tally: dict,
) -> dict:
    """탐지 결과를 에이전트가 요약하기 좋은 모양으로 조립한다."""
    return {
        "scan_id": scan_id,
        "source": source,
        "chunks_total": total,
        "chunks_scanned": processed,
        "status": status,
        "matches_total": sum(tally["by_pattern"].values()),
        "matches_by_pattern": dict(tally["by_pattern"]),
        "matches_by_location": dict(tally["by_location"]),
        "method_filter": sorted(methods) if methods is not None else None,
    }


def query_matches(
    pattern_name: str | None = None,
    url_substring: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    scan_id: int | None = None,
    limit: int = 100,
) -> list[dict]:
    """저장된 매칭 기록을 조건에 맞게 조회한다 (src.retriever.find_matches를 그대로 호출).

    pattern_name/url_substring/date_from/date_to/scan_id는 모두 선택 조건이며,
    지정하지 않으면 해당 조건은 적용하지 않는다.
    """
    return retriever.find_matches(
        pattern_name=pattern_name,
        url_substring=url_substring,
        date_from=date_from,
        date_to=date_to,
        scan_id=scan_id,
        limit=limit,
    )


def collect_traffic(start_url: str | None = None) -> dict:
    """브라우저를 띄워 사용자가 직접 둘러보는 동안 오간 요청 트래픽을 수집해 저장한다.

    내부적으로 다음을 고정 순서로 실행한다:
    1) 창을 띄우고(start_url이 있으면 그 페이지로) 오가는 데이터를 관찰
    2) 사용자가 터미널에서 Enter를 누를 때까지 대기
    3) 관측 덩어리마다 위치/텍스트/URL/부가정보를 collect 테이블에 즉시 저장

    수집 위치는 patterns.json의 targets 설정이 정한다 — 요청·응답 헤더(header),
    응답 바디(body), 요청 페이로드(request_body), 쿠키(cookie), 콘솔(console).

    정규식 매칭을 거치지 않은 원본을 그대로 남긴다 — matches 테이블이 "패턴에 걸린
    것"이라면 collect 테이블은 "오간 것 전부"다. 이후 detect_matches가 이 데이터를 대상으로
    탐지하므로, 수집 당시 상태(로그인 후 페이지 포함)가 그대로 검사된다.

    로그인 세션은 저장하지 않는다.
    """
    config = _load_config()
    conn = _storage.connect()
    try:

        def sink(location: str, text: str, url: str, detail: dict) -> None:
            _storage.save_collected(conn, location, text, url, detail)

        captured = _browser.record_session(
            should_stop=_notify.recording_stopper(),
            emit=sink,
            targets=config.get("targets") or {},
            start_url=start_url,
            chrome_path=(config.get("browser") or {}).get("chromePath"),
        )
        by_location = dict(
            conn.execute("SELECT location, COUNT(*) FROM collect GROUP BY location")
        )
    finally:
        conn.close()

    _notify.notify_recorded(captured)
    return {
        "chunks_collected": captured,
        "saved_to": "data/scan.db (collect 테이블)",
        "collect_by_location": by_location,
        "note": (
            "정규식 매칭을 거치지 않은 원본입니다. 헤더·본문·쿠키에 인증 토큰이"
            " 그대로 담길 수 있습니다."
        ),
    }


def suggest_patterns(
    pattern_name: str | None = None,
    scan_id: int | None = None,
    min_cluster: int = 3,
    limit: int = 1000,
    source: str = "matches",
    column: str | None = None,
    json_key: str | None = None,
) -> dict:
    """정규식 후보를 제안한다. 분석 대상은 source로 고른다.

    - source="matches"(기본): 이미 패턴에 걸린 값들을 분석해 더 좁은 후보를 만든다.
    - source="collect": collect 테이블을 분석해 새 후보를 만든다.
      아직 어떤 패턴에도 안 걸린 값에서 패턴을 찾을 때 쓴다.

    요청이 컬럼(column)이나 JSON 키(json_key)를 지목하면 그것을 조건으로 collect
    테이블을 **먼저 SQL로 조회하고, 돌아온 행에만** 귀납을 돌린다. 둘 중 하나라도
    주어지면 source는 "collect"로 본다 — 두 값 모두 collect 테이블의 이야기다.

    - column: 분석할 텍스트 컬럼 ("content" | "detail_json"). 생략하면 요청
      본문(request_body)의 content만 본다(기존 동작).
    - json_key: 찾을 JSON 키 이름(예: "sectionId"). 그 키를 포함한 행만 조회하고
      그 키의 값만 귀납하며, 후보를 상위 몇 개로 자르지 않는다.

    data/patterns.json을 변경하지 않는다 — 제안만 돌려주고 채택은 사람이 판단한다.
    """
    if column or json_key:
        source = "collect"
    if source == "collect":
        return _suggest_from_collect(min_cluster, limit, column, json_key)
    if source != "matches":
        raise ValueError(f"source는 'matches' 또는 'collect'여야 합니다: {source!r}")
    return _suggest_from_matches(pattern_name, scan_id, min_cluster, limit)


def _suggest_from_collect(
    min_cluster: int,
    limit: int,
    column: str | None = None,
    json_key: str | None = None,
) -> dict:
    """collect 테이블을 조건대로 조회한 뒤, 돌아온 데이터에서 정규식 후보를 도출한다.

    요청이 컬럼이나 키를 지목하면 그것을 WHERE 절로 옮겨 SQL로 먼저 걸러 온다.
    파이썬에서 걸러내면 limit이 먼저 잘려 원하는 행을 놓치고, 조회 결과가 0건이라는
    사실("그 컬럼엔 없다")도 후보 목록에 묻혀 드러나지 않는다.

    컬럼을 지목하지 않으면 기존대로 요청 본문(request_body)의 content만 본다.
    지목하면 위치를 제한하지 않는다 — detail_json에는 요청 본문이 아닌 행도 있다.

    본문을 통째로 귀납에 넣으면 의미 있는 정규식이 나오지 않으므로, JSON에서
    같은 키끼리 값을 모아(예: 여러 요청의 bizCd) 키별로 귀납한다. 서로 다른 값이
    min_cluster 미만인 키는 과적합하므로 건너뛴다.

    matches 경로와 달리 기준이 될 기존 정규식이 없어 회귀(lost) 판정을 할 수 없다.
    그래서 채택 게이트는 컴파일 가능·ReDoS 없음·커버리지만 본다.
    """
    target = column or "content"
    # 컬럼을 지목하지 않은 요청만 요청 본문으로 좁힌다 (기존 동작 유지).
    location = None if column else "request_body"
    rows = retriever.find_collect_column(
        target, contains=json_key, location=location, limit=limit
    )
    if not rows:
        return _collect_query_empty(target, location, json_key)

    buckets = _induce.values_by_key([row["text"] for row in rows])
    if json_key:
        # 키를 지목했으면 그 키의 값만 귀납한다. 나머지 키는 요청 대상이 아니다.
        buckets = {json_key: buckets[json_key]} if json_key in buckets else {}

    candidates = []
    skipped_keys = []
    rejected = 0
    _notify.notify_induce(
        f"source=collect column={target} 행 {len(rows)}개 키 {len(buckets)}종")
    for key, values in sorted(buckets.items()):
        if len(values) < min_cluster:
            skipped_keys.append(key)
            _notify.notify_induce(
                f"key={key} 건너뜀 (서로 다른 값 {len(values)}개 < {min_cluster})", depth=1)
            continue
        _notify.notify_induce(f"key={key} 값 {len(values)}개", depth=1)
        for cand in _induce.induce_regex(values, min_cluster=min_cluster):
            score = _induce.evaluate_candidate(cand["regex"], values)
            if not score["compiles"] or score["redos_risk"]:
                rejected += 1
                _notify.notify_induce(
                    f"{cand['variant']:8} 탈락: {_reject_reason(score)}"
                    f"  regex={cand['regex']}", depth=2)
                continue
            _notify.notify_induce(
                f"{cand['variant']:8} 채택: coverage {score['coverage']}", depth=2)
            candidates.append(
                {
                    "json_key": key,
                    "variant": cand["variant"],
                    "regex": cand["regex"],
                    "support": cand["support"],
                    "coverage": score["coverage"],
                    "tightness": cand["tightness"],
                    "samples": cand["samples"],
                }
            )
    candidates.sort(key=lambda c: (-c["support"], c["tightness"], len(c["regex"])))
    _notify.notify_induce(
        f"채택 {len(candidates)} / 탈락 {rejected} / 키 건너뜀 {len(skipped_keys)}", depth=1)

    return {
        "source": "collect",
        "column": target,
        "json_key": json_key,
        "location_filter": location,
        "rows_analyzed": len(rows),
        "json_keys_found": len(buckets),
        "keys_too_few_values": len(skipped_keys),
        # 키를 지목한 요청은 후보가 몇 개든 다 돌려준다. 값 종류가 적어 support가
        # 낮은 키는 상위 몇 개로 자르면 정작 요청받은 키가 잘려 나간다.
        "candidates": candidates if json_key else candidates[:MAX_CANDIDATES * 4],
        "note": _collect_note(target, json_key, buckets, min_cluster),
    }


def _collect_query_empty(column: str, location: str | None, json_key: str | None) -> dict:
    """조회 결과가 0건일 때, 왜 없는지와 어디에 있는지를 찾아 돌려준다.

    컬럼을 잘못 지목한 요청이 조용히 0건으로 끝나면 "그런 값이 없다"로 오해된다.
    지목한 키가 다른 텍스트 컬럼에 있으면 그 사실을 세어 함께 알린다.
    """
    if not json_key:
        raise ValueError(
            f"collect 테이블의 {column} 컬럼에 분석할 행이 없습니다"
            f"{f' (location={location})' if location else ''}."
            " collect_traffic으로 트래픽을 먼저 수집하세요."
        )

    elsewhere = {
        other: retriever.count_collect_column(other, json_key)
        for other in retriever.COLLECT_TEXT_COLUMNS
        if other != column
    }
    found_in = {name: hits for name, hits in elsewhere.items() if hits}
    note = f"collect 테이블의 {column} 컬럼에 '{json_key}'을(를) 포함한 행이 없습니다."
    if found_in:
        where = ", ".join(f"{name} 컬럼에 {hits}행" for name, hits in found_in.items())
        note += f" 대신 {where} 있습니다 — column을 바꿔 다시 요청하세요."
    else:
        note += " 어느 텍스트 컬럼에도 없어, 수집된 적이 없는 값으로 보입니다."

    return {
        "source": "collect",
        "column": column,
        "json_key": json_key,
        "location_filter": location,
        "rows_analyzed": 0,
        "candidates": [],
        "found_in_other_columns": found_in,
        "note": note,
    }


def _collect_note(column: str, json_key: str | None, buckets: dict, min_cluster: int) -> str:
    """collect 경로의 결과에 붙일 설명을 만든다. 회귀 판정을 못 한다는 한계를 항상 밝힌다."""
    base = " 기존 패턴이 없어 회귀 판정은 하지 않았으며, patterns.json은 변경되지 않았습니다."
    if json_key and not buckets:
        return (
            f"'{json_key}'을(를) 포함한 행은 {column} 컬럼에 있지만, JSON 키로는"
            " 나오지 않았습니다. 값이 아니라 텍스트 일부이거나 본문이 JSON이 아닙니다."
        )
    if json_key and len(next(iter(buckets.values()))) < min_cluster:
        return (
            f"'{json_key}'의 서로 다른 값이 {len(next(iter(buckets.values())))}개뿐이라"
            f" 일반화할 수 없습니다 (최소 {min_cluster}개 필요). 더 모은 뒤 다시 시도하세요."
        )
    scope = (
        f"{column} 컬럼의 '{json_key}' 키에서"
        if json_key
        else f"{column} 컬럼에서 JSON 키별로"
    )
    return f"collect 테이블 {scope} 도출한 후보입니다.{base}"


def _suggest_from_matches(
    pattern_name: str | None,
    scan_id: int | None,
    min_cluster: int,
    limit: int,
) -> dict:
    """저장된 매칭 값의 문자 구조를 분석해 더 정확한 정규식 후보를 제안한다.

    임베딩을 쓰지 않는다 — 값을 문자 클래스 시그니처로 정규화해 군집화하고, 군집의
    공통 접두/접미를 앵커로 고정한 뒤 가변부만 일반화해 후보를 조립한다. 그런 다음
    정규식이 적용된 적 없는 부수 텍스트(url, detail)에 돌려 추가 탐지와 회귀를 센다.

    매칭이 0건인 엄격한 패턴에는 완화 사다리를 돌려 어느 축(수량자/문자클래스/구분자/
    리터럴/스킴)이 병목인지 함께 보고한다.

    data/patterns.json을 변경하지 않는다 — 제안만 돌려주고 채택은 사람이 판단한다.
    """
    config = _load_config()
    patterns = _matcher.compile_patterns(config.get("patterns", []))
    corpus = retriever.find_context_texts(scan_id)

    targets = [(n, rx) for n, rx in patterns if not pattern_name or n == pattern_name]
    if not targets:
        raise ValueError(f"patterns.json에 없는 패턴 이름입니다: {pattern_name}")

    report = []
    for name, regex in targets:
        rows = retriever.find_distinct_values(
            pattern_name=name, scan_id=scan_id, limit=limit
        )
        values = [row["matched_value"] for row in rows]
        _notify.notify_induce(
            f"pattern={name} 값 {len(values)}개 corpus={len(corpus)}")
        others = [rx for other, rx in patterns if other != name]
        entry = {
            "pattern_name": name,
            "current_regex": regex.pattern,
            "distinct_values": len(values),
            "total_hits": sum(row["hits"] for row in rows),
            "candidates": [],
            "relaxations": [],
            "only_this_pattern_catches": [],
        }

        if values:
            # 다른 패턴이 하나도 잡지 못한 값 = 이 패턴을 지우면 놓치게 될 값.
            # (이 패턴이 "놓친" 값이 아니다 — 이름을 헷갈리면 정반대로 읽힌다.)
            entry["only_this_pattern_catches"] = [
                value for value in values if not any(o.search(value) for o in others)
            ]
            entry["candidates"], rejected = _build_candidates(
                values, regex.pattern, corpus, min_cluster
            )
            if not entry["candidates"]:
                entry["note"] = _no_candidate_note(values, rejected, min_cluster)
        else:
            entry["relaxations"] = _build_relaxations(regex.pattern, corpus)
            entry["note"] = (
                "매칭이 0건이라 귀납할 표본이 없어 정규식을 축별로 완화해 보았습니다."
                if entry["relaxations"]
                else "매칭이 0건이며, 어느 축을 풀어도 코퍼스에서 매칭이 생기지 않았습니다."
                " 이 패턴이 노리는 값이 실제로 없거나, 수집 대상(targets)이 좁은 것입니다."
            )
        report.append(entry)

    return {
        "source": "matches",
        "patterns": report,
        "corpus_size": len(corpus),
        "note": (
            "matches 테이블(이미 패턴에 걸린 값)을 분석한 결과입니다."
            " corpus_size는 검증에 쓴 부수 텍스트 수이며 collect 테이블과 무관합니다."
            " 제안만 반환하며 data/patterns.json은 변경되지 않았습니다."
        ),
    }


def _no_candidate_note(values: list[str], rejected: int, min_cluster: int) -> str:
    """후보가 하나도 안 남은 이유를 표본 부족과 게이트 탈락으로 구분해 설명한다."""
    if rejected:
        return (
            f"후보 {rejected}개를 만들었지만 모두 탈락했습니다. 서로 다른 값이"
            f" {len(values)}개뿐이라 과적합한 정규식이 나왔고, 기존 패턴이 잡던 값을"
            " 놓치기 때문입니다(회귀). 값을 더 모은 뒤 다시 시도하세요."
        )
    return (
        f"서로 다른 값이 {len(values)}개뿐이라 일반화할 수 없습니다"
        f" (군집당 최소 {min_cluster}개 필요). 더 모은 뒤 다시 시도하세요."
    )


def _build_candidates(
    values: list[str], baseline: str, corpus: list[str], min_cluster: int
) -> tuple[list[dict], int]:
    """군집별로 후보를 만들고 채택 게이트를 통과한 것만 정렬해 돌려준다.

    게이트: 기존 패턴이 잡던 것을 놓치지 않을 것(lost 없음), 컴파일될 것,
    중첩 수량자가 없을 것(ReDoS 위험). 통과 목록과 탈락 개수를 함께 돌려준다.
    """
    accepted: list[dict] = []
    rejected = 0
    for signature, members in _induce.cluster_by_shape(values).items():
        _notify.notify_induce(f"cluster sig={signature} 멤버 {len(members)}개", depth=1)
        for cand in _induce.induce_regex(members, min_cluster=min_cluster):
            negatives = _induce.synthetic_negatives(cand["prefix"], cand["suffix"])
            score = _induce.evaluate_candidate(
                cand["regex"], members, corpus, baseline, negatives
            )
            if not score["compiles"] or score["lost"] or score["redos_risk"]:
                rejected += 1
                _notify.notify_induce(
                    f"{cand['variant']:8} 탈락: {_reject_reason(score)}"
                    f"  regex={cand['regex']}", depth=2)
                continue
            _notify.notify_induce(
                f"{cand['variant']:8} 채택: gained {len(score['gained'])},"
                f" 음성차단 {score['negative_block_rate']}", depth=2)
            accepted.append(
                {
                    "variant": cand["variant"],
                    "regex": cand["regex"],
                    "signature": signature,
                    "support": cand["support"],
                    "lcs_len": cand["lcs_len"],
                    "tightness": cand["tightness"],
                    "samples": cand["samples"],
                    "coverage": score["coverage"],
                    "gained": score["gained"],
                    "negative_block_rate": score["negative_block_rate"],
                }
            )
    accepted.sort(
        key=lambda c: (
            -len(c["gained"]),
            -(c["negative_block_rate"] or 0),
            len(c["regex"]),
        )
    )
    _notify.notify_induce(
        f"채택 {len(accepted)} / 탈락 {rejected}"
        f" / 잘림 {max(0, len(accepted) - MAX_CANDIDATES)}", depth=1)
    return accepted[:MAX_CANDIDATES], rejected


def _reject_reason(score: dict) -> str:
    """후보가 채택 게이트에서 탈락한 사유를 한 줄로 만든다."""
    if not score.get("compiles", True):
        return "컴파일 실패"
    # collect 경로에는 기준 정규식이 없어 lost 판정 자체가 없다.
    lost = score.get("lost") or []
    if lost:
        return f"기존 패턴이 잡던 값 {len(lost)}건을 놓침"
    return "중첩 수량자 (ReDoS 위험)"


def _build_relaxations(baseline: str, corpus: list[str]) -> list[dict]:
    """매칭 0건인 패턴을 축별로 완화해, 매칭이 생기는 축을 병목으로 지목한다."""
    found = []
    for variant in _induce.relax_regex(baseline):
        hits = [text for text in corpus if re.search(variant["regex"], text)]
        if hits:
            found.append(
                {
                    "axes": variant["axes"],
                    "regex": variant["regex"],
                    "unlocked_count": len(hits),
                    "unlocked": hits[:3],
                }
            )
    # 축을 적게 풀고도 매칭이 생긴 쪽이 더 정확한 원인 지목이다.
    found.sort(key=lambda v: (len(v["axes"]), -v["unlocked_count"]))
    return found[:MAX_CANDIDATES]


def _load_config() -> dict:
    """data/patterns.json을 읽어 dict로 돌려주고, 실행 설정을 검증한다."""
    if not PATTERNS_PATH.exists():
        raise FileNotFoundError(f"설정 파일이 없습니다: {PATTERNS_PATH}")
    with PATTERNS_PATH.open(encoding="utf-8") as handle:
        config = json.load(handle)
    _check_targets(config.get("targets") or {})
    _check_delay(config.get("delayMs"))
    return config


def _check_targets(targets: dict) -> None:
    """수집 대상이 하나도 켜져 있지 않으면 스캔을 시작하기 전에 알린다.

    설정 실수로 매칭이 0건인 것을 "유출 없음"으로 오해하지 않게 하려는 검증이다.
    일부만 끈 경우는 정상 설정이므로 통과시킨다.
    """
    network = targets.get("network") or {}
    if not any(
        (
            network.get("headers"),
            network.get("body"),
            network.get("requestBody"),
            network.get("cookies"),
            targets.get("console"),
        )
    ):
        raise ValueError(
            "targets에 켜진 수집 대상이 없습니다 (network.headers/body/requestBody/cookies,"
            f" console 중 최소 1개 필요): {PATTERNS_PATH}"
        )


def _method_filter(filters: dict) -> set[str] | None:
    """filters.methods를 대문자 집합으로 돌려준다. 값을 지정하지 않으면 None(필터 없음).

    None이면 수집된 모든 항목을 매칭한다. 집합이면 detail.method가 그 안에 있는 항목만
    매칭하므로, method가 없는 수집 항목(응답 헤더/바디/쿠키/콘솔)은 함께 제외된다.

    "값을 지정하지 않은" 경우는 셋 다 같은 뜻으로 본다 — filters 키 자체가 없거나,
    methods 키가 없거나, methods가 빈 배열(`[]`)이거나. 셋 다 전체를 검사한다.
    필터를 잠시 끄려고 `[]`로 비우는 것이 키를 지웠다 되살리는 것보다 편하기 때문이다.
    """
    raw = filters.get("methods")
    if raw is None:
        return None
    if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
        raise ValueError(f"filters.methods는 문자열 배열이어야 합니다: {raw!r}")
    methods = {str(item).strip().upper() for item in raw if str(item).strip()}
    # 빈 배열은 "제한 없음"으로 읽는다 (빈 문자열만 든 배열도 마찬가지).
    return methods or None


def _check_delay(delay_ms) -> None:
    """delayMs가 숫자로 해석 가능한지 스캔 시작 전에 확인한다."""
    if delay_ms is None:
        return
    try:
        value = int(delay_ms)
    except (TypeError, ValueError):
        raise ValueError(f"delayMs는 숫자여야 합니다: {delay_ms!r}") from None
    if value < 0:
        raise ValueError(f"delayMs는 0 이상이어야 합니다: {value}")
