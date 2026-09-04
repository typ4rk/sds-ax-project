"""메인 에이전트 그래프 (LangGraph ReAct 루프).

create_agent가 ReAct 루프를 LangGraph 그래프로 컴파일한다. LLM은 어떤 도구를
몇 번 호출할지만 판단하고, 도구 내부의 수집→탐지→저장 순서는 tools.py에 고정되어 있다.
"""

import os

from langchain.agents import create_agent
from langchain_aws import ChatBedrockConverse

SYSTEM_PROMPT = (
    "당신은 브라우저 패턴 탐지 도구의 실행 결과를 사람이 이해하기 쉽게 "
    "요약해 설명하는 보조자입니다. 수집·탐지·저장 로직은 도구 내부에서 고정된 순서로 "
    "실행되므로 임의로 추측해 설명하지 마세요. "
    "요청은 세 유형입니다 — 수집(collect_traffic), 탐지(detect_matches, query_matches), "
    "분석(suggest_patterns). "
    "탐지: 저장된 트래픽을 패턴으로 다시 검사하는 요청이면 detect_matches를, 이미 걸린 결과를 "
    "확인하는 요청이면 query_matches를 호출하세요. patterns.json을 고치지 않았다면 다시 "
    "돌려도 결과가 같으므로 detect_matches를 스스로 재실행하지 마세요. 요약에는 검사한 덩어리 "
    "수와 매칭 건수, 패턴별·위치별 분포를 넣고, method_filter가 걸려 있으면 검사 범위가 "
    "좁았다는 사실을 함께 밝히세요. "
    "분석: 패턴이 너무 넓게/좁게 잡히거나 놓치는 게 있는지 묻는 요청, 새 패턴을 만들어 "
    "달라는 요청이면 suggest_patterns를 호출하세요. 요청이 컬럼 이름(content, "
    "detail_json)이나 JSON 키 이름(예: sectionId)을 지목하면 column, json_key로 그대로 "
    "넘기고 임의로 바꾸지 마세요. 결과가 0건이면 found_in_other_columns를 그대로 "
    "전하세요. 컬럼·키를 지목하지 않고 수집된 트래픽 전체에서 새 패턴을 찾는 요청이면 "
    "source=\"collect\"로 호출하세요. 도구가 돌려준 candidates 밖의 정규식을 새로 "
    "지어내지 말고, 그중에서 고르고 이름을 붙이고 위험도를 설명하는 일만 하세요. "
    "이 도구는 제안만 하며 설정을 바꾸지 않는다는 점을 밝히세요. "
    "수집: 직접 둘러보며 트래픽을 모으겠다는 요청이면 collect_traffic을 호출하세요. "
    "창을 띄우고 사용자가 Enter를 누를 때까지 기다립니다. 끝나면 수집 건수와 저장 "
    "위치(scan.db의 collect 테이블)를 알리고, 헤더·본문에 인증 토큰이 그대로 담길 수 "
    "있다는 점도 함께 알려주세요."
)


def build_agent():
    """Bedrock 모델과 도구를 연결한 패턴 탐지 에이전트를 생성한다."""
    from src.tools import collect_traffic, detect_matches, query_matches, suggest_patterns

    model = ChatBedrockConverse(
        model=_required_env("BEDROCK_MODEL_ID"),
        region_name=_required_env("AWS_REGION"),
    )

    return create_agent(
        model=model,
        tools=[detect_matches, query_matches, suggest_patterns, collect_traffic],
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
