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


def visit(browser: Browser, url: str, targets: dict, delay_ms: int, emit: Emit) -> None:
    """URL 한 개를 방문해 네트워크/쿠키/콘솔 데이터를 수집하고 emit으로 넘긴다.

    매 방문마다 새 컨텍스트를 만들어 이전 페이지의 쿠키·상태가 섞이지 않게 한다.
    방문 자체가 실패하면 예외를 그대로 올려 호출자(run_scan)가 건너뛰기를 결정한다.
    """
    network = targets.get("network") or {}
    want_headers = bool(network.get("headers"))
    want_body = bool(network.get("body"))
    want_cookies = bool(network.get("cookies"))
    want_console = bool(targets.get("console"))

    context = browser.new_context()
    page = context.new_page()

    requests: list = []
    responses: list = []
    console_lines: list[tuple[str, str]] = []

    # 핸들러는 반드시 람다/함수로 넘긴다. list.append 같은 내장 메서드를 그대로 주면
    # Playwright가 핸들러에 속성을 붙이려다 AttributeError로 실패한다.
    if want_headers:
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


def _safe_headers(target) -> str:
    """요청/응답 헤더를 "이름: 값" 줄 목록으로 만든다. 읽을 수 없으면 빈 문자열."""
    try:
        headers = target.all_headers()
    except Exception:
        return ""
    return "\n".join(f"{name}: {value}" for name, value in headers.items())


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
