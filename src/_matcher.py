"""(내부) 정규식 패턴을 컴파일하고 수집된 텍스트에서 매칭을 찾는다.

이 모듈은 오직 패턴 매칭만 담당한다 — 파일 입출력, 브라우저 제어, 저장은 하지 않는다.
"""

import re


class PatternError(ValueError):
    """patterns.json의 패턴 정의가 잘못되었을 때 발생한다."""


def compile_patterns(raw_patterns: list[dict]) -> list[tuple[str, re.Pattern]]:
    """patterns.json의 patterns 배열을 검증하고 (이름, 컴파일된 정규식) 목록으로 바꾼다.

    이름 중복과 컴파일 불가능한 정규식은 PatternError로 즉시 알린다
    (스캔을 시작한 뒤에 실패하지 않도록 로드 시점에 검증한다).
    """
    if not raw_patterns:
        raise PatternError("patterns가 비어 있습니다. 최소 1개의 패턴이 필요합니다.")

    compiled: list[tuple[str, re.Pattern]] = []
    seen: set[str] = set()

    for index, entry in enumerate(raw_patterns):
        name = entry.get("name")
        regex = entry.get("regex")
        if not name:
            raise PatternError(f"patterns[{index}]에 name이 없습니다.")
        if not regex:
            raise PatternError(f"패턴 '{name}'에 regex가 없습니다.")
        if name in seen:
            raise PatternError(f"패턴 이름이 중복되었습니다: '{name}'")
        try:
            compiled.append((name, re.compile(regex)))
        except re.error as exc:
            raise PatternError(f"패턴 '{name}'의 정규식을 컴파일할 수 없습니다: {exc}") from exc
        seen.add(name)

    return compiled


def scan_text(
    patterns: list[tuple[str, re.Pattern]],
    text: str,
    location: str,
    url: str,
    detail: dict,
) -> list[dict]:
    """텍스트 한 덩어리를 모든 패턴으로 훑어 매칭 기록 목록을 만든다.

    매칭된 값은 가공 없이 원본 그대로 담는다. 같은 위치에서 동일한 값이 여러 번
    나오면 1건으로 합친다(중복 저장 방지).
    """
    if not text:
        return []

    found: list[dict] = []
    for name, regex in patterns:
        seen_values: set[str] = set()
        for hit in regex.finditer(text):
            value = hit.group(0)
            if value in seen_values:
                continue
            seen_values.add(value)
            found.append(
                {
                    "pattern_name": name,
                    "matched_value": value,
                    "location": location,
                    "url": url,
                    "detail": detail,
                }
            )
    return found
