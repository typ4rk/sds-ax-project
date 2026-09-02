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
    "요약에는 점검한 URL 수, 매칭 건수, 패턴별/위치별 분포, 건너뛴 URL을 포함합니다."
)


def build_agent():
    """Bedrock 모델과 도구를 연결한 패턴 탐지 에이전트를 생성한다."""
    from src.tools import query_matches, run_scan

    model = ChatBedrockConverse(
        model=_required_env("BEDROCK_MODEL_ID"),
        region_name=_required_env("AWS_REGION"),
    )

    return create_agent(
        model=model,
        tools=[run_scan, query_matches],
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
