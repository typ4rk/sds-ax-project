"""(내부) LLM 호출의 토큰 사용량과 도구 결과 크기를 세어 한 줄로 요약한다.

에이전트 1회 실행 동안 콜백으로 사건을 모으고, 끝난 뒤 표준에러에 요약을 낸다.
표준출력은 [MATCH] 줄과 최종 응답의 몫이므로 건드리지 않는다.

도구 결과의 글자 수를 함께 세는 이유는, 그 결과가 다음 LLM 호출의 입력이 되기
때문이다. query_matches처럼 한 번에 많은 행을 돌려주는 도구가 입력 토큰을 밀어
올리는 인과를 한 줄에서 볼 수 있어야 한다.

합계만으로는 "어느 호출이 비쌌는지"를 알 수 없으므로 이벤트도 함께 남긴다.
dump()로 JSON Lines에 떨구면 호출별 지연 시간과 토큰이 한 줄씩 남는다.
start/end 짝은 콜백이 주는 run_id로 맞춘다.
"""

import json
import sys
import time
from pathlib import Path

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
        # 호출 단위 기록. dump()로 JSON Lines에 남긴다.
        self.events: list[dict] = []
        self._starts: dict = {}

    # ---- 시작 콜백: 지연 시간을 재기 위해 시작 시각만 잡아 둔다 ----

    def on_chat_model_start(self, serialized, messages, **kwargs) -> None:
        """모델 호출 시작 시각을 기록한다."""
        self._starts[kwargs.get("run_id")] = time.perf_counter()

    def on_tool_start(self, serialized, input_str, **kwargs) -> None:
        """도구 호출 시작을 기록한다. 결과 크기는 on_tool_end에서 채운다."""
        self._starts[kwargs.get("run_id")] = time.perf_counter()
        self.tools.append([(serialized or {}).get("name", "?"), 0])

    # ---- 종료 콜백: 합계를 누적하고 이벤트를 남긴다 ----

    def on_llm_end(self, response, **kwargs) -> None:
        """모델 응답 1건의 토큰 사용량을 누적한다."""
        self.llm_calls += 1
        generation = response.generations[0][0]
        message = getattr(generation, "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self._add_event("llm", "chat_model", kwargs,
                        input_tokens=input_tokens, output_tokens=output_tokens)

    def on_tool_end(self, output, **kwargs) -> None:
        """직전 도구의 결과 글자 수를 채운다."""
        # 도구 결과는 다음 LLM 호출의 입력이 되므로 크기를 함께 센다.
        chars = len(str(getattr(output, "content", output)))
        if self.tools:
            self.tools[-1][1] = chars
        self._add_event("tool", self._last_tool(), kwargs, result_chars=chars)

    # ---- 오류 콜백: 실패 지점이야말로 기록에서 가장 보고 싶은 것이다 ----

    def on_llm_error(self, error, **kwargs) -> None:
        """모델 호출 실패를 남긴다."""
        self._add_event("llm_error", "chat_model", kwargs, error=str(error)[:200])

    def on_tool_error(self, error, **kwargs) -> None:
        """도구 실행 실패를 남긴다."""
        self._add_event("tool_error", self._last_tool(), kwargs, error=str(error)[:200])

    # ---- 내부 ----

    def _last_tool(self) -> str:
        """가장 최근에 시작한 도구 이름."""
        return self.tools[-1][0] if self.tools else "?"

    def _add_event(self, event: str, name: str, kwargs: dict, **fields) -> None:
        """이벤트 1건을 순번·지연 시간과 함께 남긴다."""
        started = self._starts.pop(kwargs.get("run_id"), None)
        record = {
            "seq": len(self.events),
            "event": event,
            "name": name,
            "latency_s": round(time.perf_counter() - started, 3) if started else None,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for key, value in fields.items():
            record[key] = value
        self.events.append(record)

    # ---- 출력 ----

    def summary(self) -> str:
        """실행 1회의 사용량을 한 줄로 만든다."""
        total = self.input_tokens + self.output_tokens
        parts = []
        for name, chars in self.tools:
            parts.append(f"{name}({chars:,}자)")
        tools = ", ".join(parts) if parts else "없음"
        return (
            f"[USAGE] llm={self.llm_calls} input={self.input_tokens:,}\n"
            f" output={self.output_tokens:,} total={total:,} | tools: {tools}"
        )

    def report(self) -> None:
        """요약을 표준에러에 즉시 출력한다."""
        print(self.summary(), file=sys.stderr, flush=True)

    def dump(self, path: str | Path, case_id: str | None = None) -> None:
        """이벤트를 JSON Lines로 이어 쓴다. 한 줄에 한 이벤트.

        여러 실행의 기록을 한 파일에 모으므로 이어쓰기("a")다.
        case_id를 주면 어느 문항의 기록인지 각 줄에 붙는다.
        """
        target = Path(path)
        if target.parent and not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            for record in self.events:
                row = {"case_id": case_id, **record} if case_id else dict(record)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
