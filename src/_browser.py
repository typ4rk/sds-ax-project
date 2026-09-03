"""(내부) Playwright로 Chromium 세션을 열고 페이지 1개분의 관측 데이터를 수집한다.

이 모듈은 "수집"만 담당한다 — 패턴 매칭, 저장, 출력은 하지 않는다.
수집한 데이터는 emit 콜백으로 한 덩어리씩 넘긴다.
"""

import json
from contextlib import contextmanager
from typing import Callable, Iterator

from playwright.sync_api import Browser, sync_playwright

NAVIGATION_TIMEOUT_MS = 30_000

# emit(location, text, url, detail) 형태로 수집 결과 한 덩어리를 넘긴다.
Emit = Callable[[str, str, str, dict], None]
# "이제 그만인가"를 반복해서 묻는 판정 콜백. 콘솔 입출력은 호출자가 맡는다.
StopSignal = Callable[[], bool]
# on_request(url, method, headers, body) 형태로 오간 요청 한 건을 넘긴다.
RequestSink = Callable[[str, str, dict, "str | None"], None]
# 판정 사이에 Playwright를 돌리는 간격. 짧을수록 새 탭이 빨리 풀리고 CPU를 조금 더 쓴다.
PUMP_INTERVAL_MS = 200


@contextmanager
def browser_session(chrome_path: str | None = None) -> Iterator[Browser]:
    """Chromium 브라우저를 열고, 블록을 벗어나면 반드시 닫는다.

    chrome_path가 None이면 Playwright가 관리하는 Chromium을,
    문자열이면 그 경로의 실행 파일을 executable_path로 사용한다.
    """
    with sync_playwright() as playwright:
        launch_options: dict = {"headless": True}
        if chrome_path:
            launch_options["executable_path"] = chrome_path
        browser = playwright.chromium.launch(**launch_options)
        try:
            yield browser
        finally:
            browser.close()


def record_session(
    should_stop: StopSignal,
    on_request: RequestSink,
    start_url: str | None = None,
    chrome_path: str | None = None,
) -> int:
    """창을 띄워 사용자가 직접 둘러보는 동안 오간 요청 트래픽을 그대로 넘긴다.

    사람이 클릭으로 이동하는 동안 브라우저가 보낸 모든 요청을 on_request로 한 건씩
    넘기고, 넘긴 건수를 돌려준다. 새 탭·팝업에서 나간 요청도 함께 잡는다.

    로그인 세션은 저장하지 않는다. storage_state()는 컨텍스트의 모든 쿠키를 내보내므로
    점검 대상뿐 아니라 메일·금융 등 무관한 사이트의 세션까지 평문 파일 하나에 모이는데,
    점검 도구가 만들어 낼 위험으로는 과하다고 보아 기능에서 뺐다.

    언제 끝낼지는 should_stop 콜백이 정한다 — 이 모듈은 콘솔 입출력을 하지 않는다.
    이 콜백은 "한 번 기다리는" 것이 아니라 "이제 그만인가"를 반복해서 판정한다.
    사이사이 Playwright를 계속 돌려야 하기 때문이다 — 메인 흐름을 막으면 새 탭·팝업이
    "디버거 붙기 대기" 상태로 정지해 페이지가 로딩되지 않는다.
    """
    captured = 0
    watched: set[int] = set()

    def capture(request) -> None:
        nonlocal captured
        # url/method/headers/post_data는 왕복이 없는 속성이라 핸들러 안에서 안전하다.
        # all_headers() 같은 메서드를 부르면 sync API가 교착될 수 있다.
        on_request(request.url, request.method, dict(request.headers), request.post_data)
        captured += 1

    def watch(page) -> None:
        # context.on("page")는 new_page()로 만든 첫 페이지에도 발생할 수 있어 중복을 막는다.
        if id(page) in watched:
            return
        watched.add(id(page))
        page.on("request", capture)

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

            _pump_until(context, should_stop)
        finally:
            browser.close()

    return captured


def _pump_until(context, should_stop: StopSignal) -> None:
    """should_stop이 참이 될 때까지 Playwright를 짧게 반복 대기시킨다.

    이 대기가 이벤트 루프를 돌려 새로 열린 탭의 정지를 풀어 준다. 살아 있는 페이지가
    있어야 대기할 수 있으므로, 사용자가 창을 모두 닫으면 그것도 종료 신호로 본다.
    """
    while not should_stop():
        pages = [page for page in context.pages if not page.is_closed()]
        if not pages:
            return
        try:
            pages[0].wait_for_timeout(PUMP_INTERVAL_MS)
        except Exception:
            # 대기 중에 그 탭이 닫혔을 뿐일 수 있으므로 다음 회차에 다시 고른다.
            if all(page.is_closed() for page in context.pages):
                return


def visit(
    browser: Browser,
    url: str,
    targets: dict,
    delay_ms: int,
    emit: Emit,
) -> None:
    """URL 한 개를 방문해 네트워크/쿠키/콘솔 데이터를 수집하고 emit으로 넘긴다.

    매 방문마다 새 컨텍스트를 만들어 이전 페이지의 쿠키·상태가 섞이지 않게 한다.
    방문 자체가 실패하면 예외를 그대로 올려 호출자(run_scan)가 건너뛰기를 결정한다.
    """
    network = targets.get("network") or {}
    want_headers = bool(network.get("headers"))
    want_body = bool(network.get("body"))
    want_request_body = bool(network.get("requestBody"))
    want_cookies = bool(network.get("cookies"))
    want_console = bool(targets.get("console"))

    context = browser.new_context()
    page = context.new_page()

    requests: list = []
    responses: list = []
    console_lines: list[tuple[str, str]] = []

    # 핸들러는 반드시 람다/함수로 넘긴다. list.append 같은 내장 메서드를 그대로 주면
    # Playwright가 핸들러에 속성을 붙이려다 AttributeError로 실패한다.
    if want_headers or want_request_body:
        page.on("request", lambda request: requests.append(request))
    if want_headers or want_body:
        page.on("response", lambda response: responses.append(response))
    if want_console:
        page.on("console", lambda msg: console_lines.append(("console", msg.text)))
        page.on(
            "pageerror",
            lambda err: console_lines.append(("pageerror", getattr(err, "message", str(err)))),
        )

    try:
        page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
        if delay_ms > 0:
            page.wait_for_timeout(delay_ms)

        # 본문/헤더는 페이지 로드가 끝난 뒤에 읽는다.
        # 이벤트 핸들러 안에서 body()를 부르면 sync API가 교착될 수 있다.
        if want_headers:
            for request in requests:
                headers = _safe_headers(request)
                if headers:
                    emit(
                        "header",
                        headers,
                        request.url,
                        {"page_url": url, "direction": "request", "method": request.method},
                    )
            for response in responses:
                headers = _safe_headers(response)
                if headers:
                    emit(
                        "header",
                        headers,
                        response.url,
                        {"page_url": url, "direction": "response", "status": response.status},
                    )

        if want_request_body:
            # 브라우저가 내보낸 요청 페이로드. 응답 바디(body)와 달리 "나가는 데이터"다.
            for request in requests:
                payload = _safe_post_data(request)
                if payload:
                    emit(
                        "request_body",
                        payload,
                        request.url,
                        {
                            "page_url": url,
                            "direction": "request",
                            "method": request.method,
                        },
                    )

        if want_body:
            for response in responses:
                body = _safe_body(response)
                if body:
                    emit(
                        "body",
                        body,
                        response.url,
                        {"page_url": url, "status": response.status},
                    )

        if want_cookies:
            cookies = context.cookies()
            if cookies:
                emit(
                    "cookie",
                    json.dumps(cookies, ensure_ascii=False),
                    url,
                    {"page_url": url, "count": len(cookies)},
                )

        if want_console:
            for kind, line in console_lines:
                emit("console", line, url, {"page_url": url, "kind": kind})
    finally:
        context.close()


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
