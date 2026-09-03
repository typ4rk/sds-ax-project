"""메인 에이전트 그래프 (LangGraph ReAct 루프).

create_agent가 ReAct 루프를 LangGraph 그래프로 컴파일한다. LLM은 어떤 도구를
몇 번 호출할지만 판단하고, 도구 내부의 수집→탐지→저장 순서는 tools.py에 고정되어 있다.
"""

import os

from langchain.agents import create_agent
from langchain_aws import ChatBedrockConverse

SYSTEM_PROMPT = (
    "당신은 브라우저 패턴 탐지 도구의 실행 결과를 사람이 이해하기 쉽게 "
    "요약해 설명하는 보조자입니다. 사용자의 요청을 보고 새로 점검이 필요하면 "
    "run_scan을, 기존 결과 확인이면 query_matches를 호출하세요. 실제 수집·탐지· "
    "저장 로직은 도구 내부에서 고정된 순서로 실행되므로 임의로 추측해 설명하지 마세요. "
    "요약에는 점검한 URL 수, 매칭 건수, 패턴별/위치별 분포, 건너뛴 URL을 포함합니다. "
    "패턴이 너무 넓게/좁게 잡힌다거나 놓치는 게 있는지 묻는 요청이면 suggest_patterns를 "
    "호출하세요. 이때 도구가 돌려준 candidates 목록 밖의 정규식을 새로 지어내지 말고, "
    "그중에서 고르고 이름을 붙이고 위험도를 설명하는 일만 하세요. 이 도구는 제안만 하며 "
    "설정을 바꾸지 않는다는 점을 반드시 밝히세요. "
    "run_scan은 브라우저를 새로 띄워 외부 사이트에 접속하는 무거운 작업입니다. "
    "사용자가 새 점검을 명시적으로 요청할 때만 호출하세요. 이미 저장된 결과를 분석하는 "
    "요청(왜 안 잡히는지, 패턴이 적절한지, 무엇이 발견됐는지)에는 run_scan을 부르지 말고 "
    "query_matches나 suggest_patterns로 답하세요. 저장된 데이터가 부족하면 스스로 "
    "재점검하지 말고, 재점검이 필요하다는 사실을 사용자에게 알리고 판단을 맡기세요. "
    "\"url 수집\"처럼 직접 둘러보며 트래픽을 모으겠다는 요청이면 collect_traffic을 "
    "호출하세요. 이 도구는 창을 띄우고 사용자가 Enter를 누를 때까지 기다리므로 "
    "시간이 걸립니다. 끝나면 수집한 요청 건수와 저장 위치(scan.db의 collect 테이블)를 "
    "알리고, 헤더·본문에 인증 토큰이 그대로 담길 수 있다는 점도 함께 알려주세요."
)


def build_agent():
    """Bedrock 모델과 도구를 연결한 패턴 탐지 에이전트를 생성한다."""
    from src.tools import collect_traffic, query_matches, run_scan, suggest_patterns

    model = ChatBedrockConverse(
        model=_required_env("BEDROCK_MODEL_ID"),
        region_name=_required_env("AWS_REGION"),
    )

    return create_agent(
        model=model,
        tools=[run_scan, query_matches, suggest_patterns, collect_traffic],
        system_prompt=SYSTEM_PROMPT,
    )


def _required_env(name: str) -> str:
    """.env 또는 환경변수에서 필수 설정 값을 읽는다. 없으면 무엇이 빠졌는지 알린다."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"환경변수 {name}이(가) 설정되지 않았습니다. .env.example을 .env로 복사해 채우세요."
        )
    return value
