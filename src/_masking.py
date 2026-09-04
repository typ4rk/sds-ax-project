"""(내부) 도구 결과의 매칭 값을 모델에게 보내기 전에 형식만 남기고 가린다.

이 도구가 탐지하는 대상은 유출된 토큰과 개인정보다. 그 값을 요약시키려고
외부 모델에 평문으로 보내면 탐지의 취지가 무너진다. DB 원본 보존(verification 3-1)과
콘솔 출력(verification 6-5)은 그대로 두고, LLM으로 나가는 채널만 가린다.

가릴지 말지는 data/patterns.json의 패턴별 "masking" 플래그가 정한다.
키가 없으면 가린다 — 모르는 패턴을 노출하는 쪽이 더 위험하기 때문이다.

    { "name": "jwt-token",   "regex": "...", "masking": true  }   가림
    { "name": "origin-body", "regex": "...", "masking": false }   그대로

가리는 방식은 형식 보존 치환이다. 숫자는 0, 글자는 X로 바꾸고 구분자는 그대로 둔다.
길이와 구분자 위치가 남아 있어 모델이 값의 생김새를 확인할 수 있다.

    eyJhbGciOiJIUzI1NiJ9.eyJzdWIi  ->  XXXXXXXXXXXXXXX0XXX0.XXXXXXXXX
    010-1234-5678                  ->  000-0000-0000

한계 두 가지를 알고 쓴다.
  - eyJ, sk_live_ 같은 리터럴 앵커가 사라지므로 원본 정규식으로는 다시 매칭되지 않는다.
    구조(구분자 배치와 길이)만 확인할 수 있다.
  - 길이가 같은 서로 다른 값은 같은 문자열이 된다. 몇 종류가 샜는지는
    pattern_name과 행 수로 판단해야 한다.
"""

import json
from pathlib import Path

from langchain.agents.middleware import AgentMiddleware

PATTERNS_PATH = Path(__file__).resolve().parents[1] / "data" / "patterns.json"

# 원본 값을 그대로 돌려주는 도구. suggest_patterns는 samples/lost가 후보 판단의
# 근거라서 제외한다. detect_matches와 collect_traffic은 개수 집계만 돌려준다.
MASKED_TOOLS = frozenset({"query_matches"})


def mask_value(value: str) -> str:
    """숫자는 0, 글자는 X로 바꾸고 그 밖의 문자는 그대로 둔다."""
    chars = []
    for char in value:
        if char.isdigit():
            chars.append("0")
        elif char.isalpha():
            chars.append("X")
        else:
            chars.append(char)
    return "".join(chars)


def load_masking_policy() -> dict:
    """patterns.json에서 패턴 이름 -> masking 여부를 읽는다.

    설정을 못 읽어도 예외를 내지 않는다. 마스킹이 본 실행을 막으면 안 되고,
    정책을 모르는 상태에서는 전부 가리는 쪽(빈 dict + 기본 True)이 안전하다.
    """
    try:
        with PATTERNS_PATH.open(encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, ValueError):
        return {}

    policy = {}
    for pattern in config.get("patterns") or []:
        if not isinstance(pattern, dict):
            continue
        name = pattern.get("name")
        if name:
            policy[name] = bool(pattern.get("masking", True))
    return policy


def _mask_detail(row: dict, raw: str, masked: str) -> None:
    """행의 부가정보에 박힌 같은 값을 함께 가린다.

    retriever._to_dict 가 detail_json 을 파싱해 detail(dict) 로 바꿔 돌려주므로
    실제로 오는 것은 dict 다. _matcher 가 매칭된 값을 context 에 문맥째로 담기
    때문에, matched_value 만 가리면 같은 값이 context 로 그대로 새어 나간다.
    """
    detail = row.get("detail")
    if isinstance(detail, dict):
        for key, value in detail.items():
            if isinstance(value, str) and raw in value:
                detail[key] = value.replace(raw, masked)

    # 파싱 전 형태로 오는 경로가 생겨도 새지 않도록 함께 본다.
    legacy = row.get("detail_json")
    if isinstance(legacy, str) and raw in legacy:
        row["detail_json"] = legacy.replace(raw, masked)


class MaskMatchedValues(AgentMiddleware):
    """도구 결과에 실린 매칭 값을 모델에게 넘기기 전에 가린다.

    가리는 것은 matched_value와 detail 안에 박힌 같은 값뿐이다.
    url, location, pattern_name, matched_at은 모델이 요약에 쓰는 차원이라 남긴다.
    """

    def __init__(self) -> None:
        super().__init__()
        # CLI 1회 실행 동안 patterns.json은 바뀌지 않으므로 한 번만 읽는다.
        self.policy = load_masking_policy()

    def should_mask(self, pattern_name: str) -> bool:
        """이 패턴의 값을 가릴지 정한다. 설정에 없는 이름은 가린다."""
        return self.policy.get(pattern_name, True)

    def wrap_tool_call(self, request, handler):
        """도구를 실행한 뒤 결과 문자열을 가린 값으로 바꿔 돌려준다."""
        result = handler(request)
        if request.tool_call.get("name") not in MASKED_TOOLS:
            return result

        content = getattr(result, "content", None)
        if not isinstance(content, str):
            return result
        try:
            rows = json.loads(content)
        except (TypeError, ValueError):
            # 모양이 예상과 다르면 손대지 않는다.
            return result
        if not isinstance(rows, list):
            return result

        changed = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw = row.get("matched_value")
            if not raw or not isinstance(raw, str):
                continue
            if not self.should_mask(row.get("pattern_name", "")):
                continue
            masked = mask_value(raw)
            row["matched_value"] = masked
            _mask_detail(row, raw, masked)
            changed = True

        if changed:
            result.content = json.dumps(rows, ensure_ascii=False)
        return result
