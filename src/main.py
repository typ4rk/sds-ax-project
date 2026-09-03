"""실행 진입점: 자연어 요청 1개를 받아 에이전트를 호출하고 최종 응답을 출력한다.

    python -m src.main "<자연어 요청>"

인자를 주지 않으면 대화형(REPL) 모드로 진입한다.
서버를 띄우지 않는 단발성 CLI 프로세스다.
"""

import sys

from dotenv import load_dotenv


def main(argv: list[str]) -> int:
    """CLI 인자를 해석해 1회 실행 또는 REPL 모드로 에이전트를 돌린다."""
    load_dotenv()

    # .env를 읽은 뒤에 임포트해야 모델 설정이 채워진 상태로 에이전트를 만들 수 있다.
    from src.agent import build_agent

    try:
        agent = build_agent()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    request = " ".join(argv).strip()
    if request:
        return _print_answer(agent, request)

    return _chat_loop(agent)


def _print_answer(agent, request: str) -> int:
    """요청 1건을 실행해 응답을 표준출력에 쓴다. 실패하면 사유만 알리고 1을 돌려준다."""
    try:
        print(_ask(agent, request))
    except Exception as exc:
        # 모델·도구 호출 실패를 파이썬 트레이스백 대신 한 줄로 알린다.
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


def _ask(agent, request: str) -> str:
    """자연어 요청 1개를 에이전트에 넘기고 최종 응답 텍스트를 돌려준다."""
    result = agent.invoke({"messages": [{"role": "user", "content": request}]})
    return _text_of(result["messages"][-1])


def _chat_loop(agent) -> int:
    """인자 없이 실행했을 때의 대화형 모드. 빈 줄이나 EOF로 종료한다."""
    print('대화형 모드입니다. 빈 줄을 입력하면 종료합니다.', file=sys.stderr)
    while True:
        try:
            request = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            return 0
        if not request:
            return 0
        # 한 요청이 실패해도 대화를 끊지 않고 다음 입력을 받는다.
        _print_answer(agent, request)


def _text_of(message) -> str:
    """모델 응답 메시지에서 사람이 읽을 텍스트만 뽑는다.

    Bedrock Converse는 content를 문자열이 아니라 블록 목록으로 돌려줄 수 있으므로
    두 형태를 모두 처리한다.
    """
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(part for part in parts if part)
    return str(content)


if __name__ == "__main__":
    # python -m src.main "수집된 트래픽 본문에서 정규식 후보 찾아줘"
    # python -c "from src import retriever; [print(r['matched_value'], '<-', r['url']) for r in retriever.find_matches(pattern_name='test-any-url', limit=20)]"
    raise SystemExit(main(sys.argv[1:]))
