"""(내부) 도구 결과에 섞여 온 지시문을 탐지해 알린다. 내용은 바꾸지 않는다.

collect 테이블에 담긴 것은 임의의 웹사이트가 만든 텍스트다. 그 안에
"이전 지시는 모두 무시하고 ..." 같은 문장이 심겨 있으면, query_matches나
suggest_patterns의 결과를 타고 모델 컨텍스트로 들어간다. 간접 프롬프트 주입이다.

이 모듈은 **탐지와 기록만** 한다. 도구 결과를 고치지 않는다.
관측한 트래픽을 보고 경로에서 변형하면 분석 도구로서의 충실도가 깨지고,
"무엇이 실제로 오갔는가"를 사람이 확인할 수 없게 되기 때문이다.

그래서 남는 위험이 있다 — 탐지해도 그 문자열은 모델에게 그대로 전달된다.
[GUARD] 줄은 사람이 보고 판단하라는 신호다.

패턴은 day5 실습(d1_guards_input.py)의 INJECTION_PATTERNS를 그대로 쓴다.
수집 데이터 2,082행에 돌려 오탐 0건, 주입 표본 6종 전부 탐지를 확인했다.
"""

import re

from langchain.agents.middleware import AgentMiddleware

from src import _notify

INJECTION_PATTERNS = [
    r"ignore (the |all )?(previous|above|prior) (instructions?|prompts?)",
    r"you are now a different",
    r"(위의?|이전|기존|지금까지) ?(모든 )?(지시|명령|규칙|프롬프트)[은는를]? ?.{0,8}(무시|잊|버려)",
    r"규칙 ?(이|가) ?없는 (AI|인공지능|모드)",
    r"system\s*:\s*",
    r"</?(system|admin|root)>",
    r"(시스템 프롬프트|숨겨진 (지시|프롬프트)|첫 ?(번째)? ?지시문?).{0,10}(공개|출력|알려)",
    r"개발자 모드",
]

# 제3자 텍스트가 실려 오는 도구만 검사한다.
# detect_matches와 collect_traffic은 개수 집계만 돌려주므로 대상이 아니다.
GUARDED_TOOLS = frozenset({"query_matches", "suggest_patterns"})

# 한 번의 도구 호출에서 알릴 최대 건수. 같은 문자열이 수백 행에 반복되면
# 콘솔이 묻히므로 상한을 둔다.
MAX_REPORTS = 5


def find_injections(text: str) -> list[tuple[str, str]]:
    """주입 의심 구간을 (패턴, 걸린 문자열) 목록으로 돌려준다.

    같은 문자열이 여러 번 나와도 한 번만 센다. 몇 번 반복됐는지가 아니라
    "무엇이 심겨 있었는가"가 사람이 판단할 정보이기 때문이다.
    """
    found = []
    seen = set()
    for pattern in INJECTION_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            matched = match.group(0)
            if matched in seen:
                continue
            seen.add(matched)
            found.append((pattern, matched))
            if len(found) >= MAX_REPORTS:
                return found
    return found


class ToolResultGuard(AgentMiddleware):
    """도구 결과에서 주입 의심 문자열을 찾아 알린다. 결과는 그대로 통과시킨다."""

    def wrap_tool_call(self, request, handler):
        """도구를 실행한 뒤 결과를 검사만 하고 원본을 그대로 돌려준다."""
        result = handler(request)

        tool_name = request.tool_call.get("name")
        if tool_name not in GUARDED_TOOLS:
            return result
        content = getattr(result, "content", None)
        if not isinstance(content, str):
            return result

        for pattern, matched in find_injections(content):
            _notify.notify_guard(tool_name, matched, pattern)
        return result
