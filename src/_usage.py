"""(내부) LLM 호출의 토큰 사용량과 도구 결과 크기를 세어 한 줄로 요약한다.

에이전트 1회 실행 동안 콜백으로 사건을 모으고, 끝난 뒤 표준에러에 요약을 낸다.
표준출력은 [MATCH] 줄과 최종 응답의 몫이므로 건드리지 않는다.

도구 결과의 글자 수를 함께 세는 이유는, 그 결과가 다음 LLM 호출의 입력이 되기
때문이다. query_matches처럼 한 번에 많은 행을 돌려주는 도구가 입력 토큰을 밀어
올리는 인과를 한 줄에서 볼 수 있어야 한다.
"""

import sys

from langchain_core.callbacks import BaseCallbackHandler


class UsageTracer(BaseCallbackHandler):
    """LLM 호출별 토큰 사용량과 도구 결과 크기를 모은다.

    Bedrock은 호출 방식에 따라 usage_metadata를 안 실어 보낼 수 있으므로,
    없으면 0으로 세고 예외를 내지 않는다. 계측이 본 실행을 막으면 안 된다.
    """

    def __init__(self) -> None:
        self.llm_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        # [도구 이름, 결과 글자 수] 목록. 호출 순서를 그대로 유지한다.
        self.tools: list[list] = []

    def on_llm_end(self, response, **kwargs) -> None:
        """모델 응답 1건의 토큰 사용량을 누적한다."""
        self.llm_calls += 1
        generation = response.generations[0][0]
        message = getattr(generation, "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)

    def on_tool_start(self, serialized, input_str, **kwargs) -> None:
        """도구 호출 시작을 기록한다. 결과 크기는 on_tool_end에서 채운다."""
        self.tools.append([(serialized or {}).get("name", "?"), 0])

    def on_tool_end(self, output, **kwargs) -> None:
        """직전 도구의 결과 글자 수를 채운다."""
        if self.tools:
            self.tools[-1][1] = len(str(getattr(output, "content", output)))

    def summary(self) -> str:
        """실행 1회의 사용량을 한 줄로 만든다."""
        total = self.input_tokens + self.output_tokens
        parts = []
        for name, chars in self.tools:
            parts.append(f"{name}({chars:,}자)")
        tools = ", ".join(parts) if parts else "없음"
        return (
            f"[usage] llm={self.llm_calls} input={self.input_tokens:,}"
            f" output={self.output_tokens:,} total={total:,} | tools: {tools}"
        )

    def report(self) -> None:
        """요약을 표준에러에 즉시 출력한다."""
        print(self.summary(), file=sys.stderr, flush=True)
