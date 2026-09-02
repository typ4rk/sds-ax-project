"""에이전트에 노출되는 도메인 도구 정의.

이 파일의 역할은 "도구 함수의 정의와 고정된 실행 순서"뿐이다.
브라우저 제어/매칭/저장/알림/조회의 실제 구현은
_browser.py / _matcher.py / _storage.py / _notify.py / retriever.py에 위임한다.
"""

import json
from collections import Counter
from pathlib import Path

from src import _browser, _matcher, _notify, _storage, retriever

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
URLS_PATH = DATA_DIR / "urls.txt"
PATTERNS_PATH = DATA_DIR / "patterns.json"


def run_scan() -> dict:
    """data/urls.txt에 저장된 URL을 순서대로 방문하며 등록된 정규식 패턴을 탐지한다.

    내부적으로 다음을 고정 순서로 실행한다:
    1) data/patterns.json 로드 및 검증
    2) data/urls.txt의 각 URL을 순서대로 방문 (실패한 URL은 건너뛰고 계속)
    3) 방문마다 네트워크/콘솔 데이터를 수집하고, filters를 통과한 것만 정규식으로 매칭
    4) 매칭 발생 즉시 콘솔에 출력
    5) scans/matches를 data/scan.db에 저장

    반환값은 에이전트가 요약에 쓸 수 있는 구조화된 결과(dict)이며,
    scan_id, urls_total, urls_visited, status, 매칭 건수 요약을 포함한다.
    """
    config = _load_config()
    patterns = _matcher.compile_patterns(config.get("patterns", []))
    targets = config.get("targets") or {}
    methods = _method_filter(config.get("filters") or {})
    delay_ms = int(config.get("delayMs") or 0)
    chrome_path = (config.get("browser") or {}).get("chromePath")

    urls = _load_urls()
    conn = _storage.connect()
    scan_id = _storage.start_scan(conn, str(URLS_PATH.relative_to(DATA_DIR.parent)), len(urls))

    visited = 0
    skipped: list[dict] = []
    by_pattern: Counter = Counter()
    by_location: Counter = Counter()

    try:
        with _browser.browser_session(chrome_path) as browser:
            for url in urls:
                # visit은 반환값이 없고 emit 콜백으로만 수집 결과를 넘긴다.
                # 이 URL에서 덩어리/매칭이 각각 몇 건이었는지 세어 방문 끝에 알린다.
                chunks = 0
                filtered = 0
                hits = 0

                def emit(location: str, text: str, source_url: str, detail: dict) -> None:
                    nonlocal chunks, filtered, hits
                    chunks += 1
                    if methods is not None and detail.get("method") not in methods:
                        # filters.methods에 걸리지 않은 덩어리는 매칭 대상에서 뺀다.
                        # method가 없는 수집 항목(응답 헤더/바디/쿠키/콘솔)도 여기서 제외된다.
                        filtered += 1
                        return
                    found = _matcher.scan_text(patterns, text, location, source_url, detail)
                    hits += len(found)
                    # 수집 원본을 먼저 보여준다 (SCAN_TRACE=1일 때만).
                    _notify.notify_collected(location, text, source_url, detail, len(found))
                    for match in found:
                        # 알림이 저장보다 먼저다 — 매칭 시점과 출력 시점 사이를 벌리지 않는다.
                        _notify.notify_match(match)
                        _storage.save_match(conn, scan_id, match)
                        by_pattern[match["pattern_name"]] += 1
                        by_location[match["location"]] += 1

                try:
                    _browser.visit(browser, url, targets, delay_ms, emit)
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}".splitlines()[0]
                    _notify.notify_skip(url, reason)
                    skipped.append({"url": url, "reason": reason})
                    continue
                _notify.notify_visit(url, chunks, hits, filtered)
                visited += 1
    finally:
        # 도중에 예외가 나더라도 scans 행을 running 상태로 남기지 않는다.
        status = "completed" if visited > 0 else "failed"
        try:
            _storage.finish_scan(conn, scan_id, visited, status)
        finally:
            # 상태 기록이 실패해도 커넥션은 반드시 닫는다.
            conn.close()

    return {
        "scan_id": scan_id,
        "urls_total": len(urls),
        "urls_visited": visited,
        "status": status,
        "matches_total": sum(by_pattern.values()),
        "matches_by_pattern": dict(by_pattern),
        "matches_by_location": dict(by_location),
        "method_filter": sorted(methods) if methods is not None else None,
        "skipped": skipped,
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
    """filters.methods를 대문자 집합으로 돌려준다. 지정이 없으면 None(필터 없음).

    None이면 수집된 모든 항목을 매칭한다. 집합이면 detail.method가 그 안에 있는 항목만
    매칭하므로, method가 없는 수집 항목(응답 헤더/바디/쿠키/콘솔)은 함께 제외된다.
    """
    raw = filters.get("methods")
    if raw is None:
        return None
    if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
        raise ValueError(f"filters.methods는 문자열 배열이어야 합니다: {raw!r}")
    methods = {str(item).strip().upper() for item in raw if str(item).strip()}
    if not methods:
        raise ValueError(
            "filters.methods가 비어 있습니다. 필터를 쓰지 않으려면 키를 지우세요:"
            f" {PATTERNS_PATH}"
        )
    return methods


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


def _load_urls() -> list[str]:
    """data/urls.txt를 읽어 점검 대상 URL 목록을 순서대로 돌려준다.

    빈 줄과 '#'로 시작하는 주석 줄은 무시한다.
    """
    if not URLS_PATH.exists():
        raise FileNotFoundError(f"URL 목록 파일이 없습니다: {URLS_PATH}")
    urls = []
    for line in URLS_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            urls.append(stripped)
    if not urls:
        raise ValueError(f"점검할 URL이 없습니다: {URLS_PATH}")
    return urls
