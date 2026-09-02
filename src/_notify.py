"""(내부) 스캔 진행 중 발생하는 사건을 콘솔에 즉시 출력한다.

에이전트(LLM)의 최종 응답과는 별개로, 도구 실행 중에 발생하는 부수 효과다.
"즉시성" 기준을 지키기 위해 모든 출력은 버퍼링 없이 flush한다.

수집 덩어리를 그대로 보여주는 추적 출력(notify_collected/notify_visit)도 여기에 둔다.
원본 값이 노출되므로 기본은 꺼져 있고 SCAN_TRACE=1일 때만 표준에러로 나간다.
"""

import os
import sys

TRACE_ENV = "SCAN_TRACE"
PREVIEW_CHARS = 300
# [MATCH] 줄에 싣는 detail의 최대 길이 (verification.md 6-2)
DETAIL_CHARS = 200


def notify_match(match: dict) -> None:
    """매칭 1건을 발견 즉시 표준출력에 출력한다.

    다음 URL 처리로 넘어가기 전에 출력되어야 하므로 즉시 flush한다.
    matched_value는 자르지 않고 원본 그대로 싣는다(값 노출 정책, verification.md 6-6).
    detail은 길어질 수 있어 DETAIL_CHARS까지만 싣는다.
    url은 매칭된 값이 아니라 값이 발견된 리소스 URL이다(verification.md 3-2).
    """
    print(
        f"[MATCH] pattern={match['pattern_name']}"
        f"|matched_value={_one_line(match['matched_value'])}"
        f"|location={match['location']}"
        f"|url={match['url']}"        
        f"|detail={_clip(match.get('detail') or {}, DETAIL_CHARS)}",
        flush=True,
    )


def _one_line(value) -> str:
    """콘솔 한 줄 형식을 유지하려고 줄바꿈과 연속 공백을 공백 하나로 접는다.

    DB에는 원본이 그대로 저장되므로(verification.md 3-1) 출력에만 적용된다.
    """
    return " ".join(str(value).split())


def _clip(value, limit: int) -> str:
    """값을 한 줄로 만들고 limit자를 넘으면 잘라 '...'을 붙인다."""
    text = _one_line(value)
    return text if len(text) <= limit else text[:limit] + "..."


def notify_skip(url: str, reason: str) -> None:
    """방문에 실패해 건너뛴 URL을 표준에러로 출력한다.

    최종 응답(표준출력)과 섞이지 않도록 표준에러로 보낸다.
    """
    print(f"[SKIP] {url} - {reason}", file=sys.stderr, flush=True)


def trace_enabled() -> bool:
    """수집 데이터 추적 출력이 켜져 있는지 알려준다 (환경변수 SCAN_TRACE)."""
    return os.environ.get(TRACE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def notify_collected(
    location: str, text: str, url: str, detail: dict, match_count: int
) -> None:
    """visit이 넘겨준 수집 덩어리 1건을 추적 출력한다.

    매칭이 0건일 때 "수집이 안 된 것"인지 "패턴이 안 맞은 것"인지 구분하려는 디버깅용이다.
    수집 원본이 그대로 찍히므로 SCAN_TRACE=1일 때만 동작하고, 최종 응답(표준출력)과
    섞이지 않도록 표준에러로 보낸다.
    """
    if not trace_enabled():
        return
    print(
        f"[DATA] location={location} len={len(text)} matched={match_count} url={url}",
        file=sys.stderr,
        flush=True,
    )
    print(f"       detail={_clip(detail, DETAIL_CHARS)}", file=sys.stderr, flush=True)
    print(f"       {_clip(text, PREVIEW_CHARS)}", file=sys.stderr, flush=True)


def notify_visit(url: str, chunk_count: int, match_count: int) -> None:
    """URL 1건 방문이 끝났을 때 수집 덩어리와 매칭이 각각 몇 건이었는지 알린다.

    덩어리가 0건이면 수집 단계에서, 덩어리는 있는데 매칭이 0건이면 패턴에서 막힌 것이다.
    """
    if not trace_enabled():
        return
    print(
        f"[VISIT] {url} - 수집 덩어리 {chunk_count}건, 매칭 {match_count}건",
        file=sys.stderr,
        flush=True,
    )
