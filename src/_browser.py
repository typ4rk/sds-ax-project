"""(내부) Playwright로 창을 띄워 사용자가 둘러보는 동안의 관측 데이터를 수집한다.

이 모듈은 "수집"만 담당한다 — 패턴 매칭, 저장, 출력은 하지 않는다.
수집한 데이터는 emit 콜백으로 (위치, 텍스트, URL, 부가정보) 한 덩어리씩 넘긴다.
"""

import json
from typing import Callable

from playwright.sync_api import sync_playwright

NAVIGATION_TIMEOUT_MS = 30_000

# emit(location, text, url, detail) 형태로 수집 결과 한 덩어리를 넘긴다.
Emit = Callable[[str, str, str, dict], None]
# "이제 그만인가"를 반복해서 묻는 판정 콜백. 콘솔 입출력은 호출자가 맡는다.
StopSignal = Callable[[], bool]
# 판정 사이에 Playwright를 돌리는 간격. 짧을수록 새 탭이 빨리 풀리고 CPU를 조금 더 쓴다.
PUMP_INTERVAL_MS = 200


def record_session(
    should_stop: StopSignal,
    emit: Emit,
    targets: dict,
    start_url: str | None = None,
    chrome_path: str | None = None,
) -> int:
    """창을 띄워 사용자가 둘러보는 동안의 관측 데이터를 emit으로 넘긴다.

    수집 위치는 targets 설정이 정한다 — 요청/응답 헤더(header), 응답 바디(body),
    요청 페이로드(request_body), 쿠키(cookie), 콘솔·JS 에러(console).
    새 탭·팝업에서 오간 것도 함께 잡으며, 넘긴 덩어리 수를 돌려준다.

    응답 바디는 핸들러 안에서 읽지 않는다 — sync API가 교착될 수 있어, 응답 객체만
    쌓아 두고 대기 루프에서 꺼내 읽는다. 대신 요청의 url/method/headers/post_data는
    왕복이 없는 속성이라 핸들러 안에서 바로 읽어도 안전하다.

    로그인 세션은 저장하지 않는다. storage_state()는 컨텍스트의 모든 쿠키를 내보내므로
    점검 대상뿐 아니라 메일·금융 등 무관한 사이트의 세션까지 평문 파일 하나에 모이는데,
    점검 도구가 만들어 낼 위험으로는 과하다고 보아 기능에서 뺐다.

    언제 끝낼지는 should_stop 콜백이 정한다 — 이 모듈은 콘솔 입출력을 하지 않는다.
    이 콜백은 "한 번 기다리는" 것이 아니라 "이제 그만인가"를 반복해서 판정한다.
    사이사이 Playwright를 계속 돌려야 하기 때문이다 — 메인 흐름을 막으면 새 탭·팝업이
    "디버거 붙기 대기" 상태로 정지해 페이지가 로딩되지 않는다.
    """
    network = targets.get("network") or {}
    want_headers = bool(network.get("headers"))
    want_body = bool(network.get("body"))
    want_request_body = bool(network.get("requestBody"))
    want_cookies = bool(network.get("cookies"))
    want_console = bool(targets.get("console"))

    count = 0
    watched: set[int] = set()
    pending: list = []          # 바디를 아직 읽지 않은 응답 (대기 루프에서 꺼낸다)

    def hand_over(location: str, text: str, url: str, detail: dict) -> None:
        nonlocal count
        if not text:
            return
        emit(location, text, url, detail)
        count += 1

    def on_request(request) -> None:
        detail = {"direction": "request", "method": request.method}
        if want_headers:
            hand_over("header", headers_text(dict(request.headers)), request.url, detail)
        if want_request_body:
            hand_over("request_body", request.post_data or "", request.url, detail)

    def on_response(response) -> None:
        pending.append(response)

    def on_console(kind: str, text: str, url: str) -> None:
        hand_over("console", text, url, {"kind": kind})

    def drain() -> None:
        """쌓인 응답에서 헤더·바디를 읽어 넘긴다. 핸들러 밖에서만 호출한다."""
        while pending:
            response = pending.pop(0)
            detail = {"direction": "response", "status": response.status}
            if want_headers:
                hand_over("header", _safe_headers(response), response.url, detail)
            if want_body:
                hand_over("body", _safe_body(response), response.url, detail)

    def watch(page) -> None:
        # context.on("page")는 new_page()로 만든 첫 페이지에도 발생할 수 있어 중복을 막는다.
        if id(page) in watched:
            return
        watched.add(id(page))
        if want_headers or want_request_body:
            page.on("request", on_request)
        if want_headers or want_body:
            page.on("response", on_response)
        if want_console:
            page.on("console", lambda msg: on_console("console", msg.text, page.url))
            page.on(
                "pageerror",
                lambda err: on_console("pageerror", getattr(err, "message", str(err)), page.url),
            )

    with sync_playwright() as playwright:
        launch_options: dict = {"headless": False}
        if chrome_path:
            launch_options["executable_path"] = chrome_path
        browser = playwright.chromium.launch(**launch_options)
        try:
            context = browser.new_context()
            # 사용자가 창을 닫으면 대기 중이던 호출이 실패하는데, 기본 타임아웃(30초)을
            # 그대로 두면 그만큼 멈춘 뒤에야 알아챈다. 펌프 간격 기준으로 짧게 줄인다.
            context.set_default_timeout(PUMP_INTERVAL_MS * 5)
            context.on("page", watch)
            page = context.new_page()
            watch(page)
            if start_url:
                page.goto(start_url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)

            _pump_until(context, should_stop, drain)

            # 쿠키는 창이 살아 있는 마지막 시점에 한 번 읽는다.
            if want_cookies:
                cookies = context.cookies()
                if cookies:
                    hand_over(
                        "cookie",
                        json.dumps(cookies, ensure_ascii=False),
                        context.pages[0].url if context.pages else "",
                        {"count": len(cookies)},
                    )
        finally:
            browser.close()

    return count


def _pump_until(context, should_stop: StopSignal, drain=None) -> None:
    """should_stop이 참이 될 때까지 Playwright를 짧게 반복 대기시킨다.

    이 대기가 이벤트 루프를 돌려 새로 열린 탭의 정지를 풀어 준다. 살아 있는 페이지가
    있어야 대기할 수 있으므로, 사용자가 창을 모두 닫으면 그것도 종료 신호로 본다.

    drain을 주면 매 회차에 한 번 불러, 핸들러 안에서 읽으면 위험한 작업(응답 바디)을
    안전한 자리에서 처리하게 한다.
    """
    while not should_stop():
        if drain:
            drain()
        pages = [page for page in context.pages if not page.is_closed()]
        if not pages:
            return
        try:
            pages[0].wait_for_timeout(PUMP_INTERVAL_MS)
        except Exception:
            # 대기 중에 그 탭이 닫혔을 뿐일 수 있으므로 다음 회차에 다시 고른다.
            if all(page.is_closed() for page in context.pages):
                return


def headers_text(headers: dict) -> str:
    """헤더 dict를 "이름: 값" 줄 목록으로 만든다.

    브라우저에서 갓 수집한 헤더와 collect 테이블에 저장된 헤더가 같은 형식이어야
    한 정규식이 양쪽에서 똑같이 동작한다(예: `(?mi)^origin:`은 줄 시작에 의존한다).
    그래서 형식 정의를 이 한 곳에만 둔다.
    """
    return "\n".join(f"{name}: {value}" for name, value in headers.items())


def _safe_headers(target) -> str:
    """요청/응답 헤더를 "이름: 값" 줄 목록으로 만든다. 읽을 수 없으면 빈 문자열."""
    try:
        return headers_text(target.all_headers())
    except Exception:
        return ""


def _safe_body(response) -> str:
    """응답 본문을 텍스트로 읽는다.

    리다이렉트나 이미 사라진 응답은 본문을 읽을 수 없으므로 그 경우 빈 문자열을 돌려준다.
    바이너리 응답은 디코딩 오류를 무시하고 최대한 텍스트로 훑는다.
    """
    try:
        raw = response.body()
    except Exception:
        return ""
    return raw.decode("utf-8", errors="replace")


def _safe_post_data(request) -> str:
    """요청 페이로드(POST 본문)를 텍스트로 읽는다. 없거나 읽을 수 없으면 빈 문자열.

    GET처럼 본문이 없는 요청은 None이 오므로 빈 문자열로 바꿔 돌려준다.
    """
    try:
        return request.post_data or ""
    except Exception:
        return ""
