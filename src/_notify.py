"""(내부) 스캔 진행 중 발생하는 사건을 콘솔에 즉시 출력한다.

에이전트(LLM)의 최종 응답과는 별개로, 도구 실행 중에 발생하는 부수 효과다.
"즉시성" 기준을 지키기 위해 모든 출력은 버퍼링 없이 flush한다.

수집 덩어리를 그대로 보여주는 추적 출력(notify_collected/notify_visit)도 여기에 둔다.
원본 값이 노출되므로 기본은 꺼져 있고 SCAN_TRACE=1일 때만 표준에러로 나간다.
"""

import os
import sys
import threading
from typing import Callable

TRACE_ENV = "SCAN_TRACE"
PREVIEW_CHARS = 300
# [MATCH] 줄에 싣는 detail의 최대 길이 (verification.md 6-2)
DETAIL_CHARS = 200
# [MATCH] 줄에 싣는 context의 최대 길이. _matcher가 앞뒤 40자씩 남기므로 넉넉히 잡는다.
CONTEXT_CHARS = 200


def notify_match(match: dict) -> None:
    """매칭 1건을 발견 즉시 표준출력에 출력한다.

    다음 URL 처리로 넘어가기 전에 출력되어야 하므로 즉시 flush한다.
    matched_value는 자르지 않고 원본 그대로 싣는다(값 노출 정책, verification.md 6-6).
    context는 매칭된 값이 실제로 어떤 문장 안에 있었는지 보여주며, detail에서 꺼내
    별도 필드로 낸다 — detail 안에 두면 page_url이 길 때 DETAIL_CHARS에 잘려 사라진다.
    url은 매칭된 값이 아니라 값이 발견된 리소스 URL이다(verification.md 3-2).
    """
    detail = dict(match.get("detail") or {})
    context = detail.pop("context", "")
    print(
        f"[MATCH] pattern={match['pattern_name']}"
        f"|location={match['location']}"
        f"|matched_value={_one_line(match['matched_value'])}"
        f"|url={match['url']}"
        f"|context={_clip(context, CONTEXT_CHARS)}"
        f"|detail={_clip(detail, DETAIL_CHARS)}",
        flush=True,
    )


def recording_stopper() -> Callable[[], bool]:
    """Enter를 백그라운드에서 기다리고, 눌렸는지 알려주는 판정 함수를 돌려준다.

    호출한 쪽이 이 판정을 반복해서 물어보며 그 사이에 Playwright를 계속 돌려야 한다.
    input()으로 메인 흐름을 막으면 Playwright가 이벤트를 처리하지 못해, 새 탭·팝업이
    "디버거 붙기 대기" 상태로 정지한 채 페이지가 로딩되지 않는다.

    표준입력이 닫혀 있으면(EOF) 곧바로 종료로 판정한다 — 비대화형 실행에서 무한정
    멈추지 않게 하기 위한 것이며, 그 경우 수집된 URL이 거의 없을 수 있다.
    안내는 최종 응답(표준출력)과 섞이지 않도록 표준에러로 보낸다.
    """
    print(
        "[RECORD] 브라우저에서 점검하고 싶은 페이지를 둘러보세요.\n"
        "[RECORD] 로그인 세션은 저장하지 않으므로, 로그인 후에만 보이는 페이지는"
        " 나중에 재현되지 않습니다.\n"
        "[RECORD] 다 끝나면 이 터미널에서 Enter를 누르세요.",
        file=sys.stderr,
        flush=True,
    )
    done = threading.Event()

    def wait_for_enter() -> None:
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            print("[RECORD] 입력이 없어 수집을 끝냅니다.", file=sys.stderr, flush=True)
        done.set()

    threading.Thread(target=wait_for_enter, daemon=True).start()
    return done.is_set


def notify_recorded(request_count: int) -> None:
    """수집 결과를 사람이 확인할 수 있게 표준에러로 요약한다."""
    print(
        f"[RECORD] 요청 {request_count}건을 collect 테이블에 저장했습니다.",
        file=sys.stderr,
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


def notify_visit(
    url: str, chunk_count: int, match_count: int, filtered_count: int = 0
) -> None:
    """URL 1건 방문이 끝났을 때 수집·필터·매칭 건수를 알린다.

    어느 단계에서 0이 되었는지로 원인을 좁힌다:
    덩어리 0건이면 수집 단계, 필터로 전부 빠졌으면 filters 설정, 그 다음이 패턴 문제다.
    """
    if not trace_enabled():
        return
    print(
        f"[VISIT] {url} - 수집 덩어리 {chunk_count}건,"
        f" 필터 제외 {filtered_count}건, 매칭 {match_count}건",
        file=sys.stderr,
        flush=True,
    )
