"""평가 러너: test_queries.csv를 에이전트로 돌려 expected_tool과 대조한다.

    python evaluation/run_eval.py                # 전체 문항
    python evaluation/run_eval.py --ids 1,2,3    # 일부만 (토큰 쿼터 절약)
    python evaluation/run_eval.py --dry-run      # 에이전트 호출 없이 CSV와 계획만 점검

판정은 "기대한 도구를 실제로 불렀는가" 하나다. 답변 문장의 품질은 사람이 본다.
실제 호출한 도구 목록과 문항별 토큰 사용량을 함께 남겨, 중복 호출과 쿼터 소진 지점을
report.md에서 바로 짚을 수 있게 한다.

한 문항이 터져도 나머지를 계속 돌린다. 15문항 중 3번째에서 죽으면 나머지 12문항의
상태를 영영 모르기 때문이다.

출력은 두 가지다.
  - 표준출력: report.md 1절에 그대로 붙일 수 있는 마크다운 표
  - evaluation/eval_result.json: 답변 전문까지 담은 원본 기록
"""

import csv
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QUERIES_PATH = ROOT / "evaluation" / "test_queries.csv"
RESULT_PATH = ROOT / "evaluation" / "eval_result.json"
REQUIRED_COLUMNS = ("id", "question", "expected_tool")

PASS, FAIL, ERROR = "PASS", "FAIL", "ERROR"


def load_cases(only_ids: set[str] | None = None) -> list[dict]:
    """test_queries.csv를 읽어 문항 목록을 돌려준다. 필요한 컬럼이 없으면 알린다."""
    with QUERIES_PATH.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"문항이 없습니다: {QUERIES_PATH}")

    missing = []
    for column in REQUIRED_COLUMNS:
        if column not in rows[0]:
            missing.append(column)
    if missing:
        raise ValueError(f"CSV에 필요한 컬럼이 없습니다: {missing} (현재: {list(rows[0])})")

    if only_ids is None:
        return rows
    picked = []
    for row in rows:
        if str(row.get("id", "")).strip() in only_ids:
            picked.append(row)
    return picked


def run_one(agent, case: dict) -> dict:
    """문항 1건을 실행하고 판정 결과를 돌려준다. 예외는 여기서 삼킨다."""
    from src import _usage, main

    tracer = _usage.UsageTracer()
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": case["question"]}]},
            {"recursion_limit": main.RECURSION_LIMIT, "callbacks": [tracer]},
        )
        answer = main._text_of(result["messages"][-1])
    except Exception as exc:  # 한 문항의 실패가 전체를 멈추면 안 된다
        return _record(case, ERROR, [], "", tracer, f"{type(exc).__name__}: {exc}")

    called = []
    for name, _chars in tracer.tools:
        called.append(name)

    expected = (case.get("expected_tool") or "").strip()
    status = PASS if expected and expected in called else FAIL
    return _record(case, status, called, answer, tracer, _note(case, called, answer, tracer))


def _record(case: dict, status: str, called: list[str], answer: str, tracer, detail: str) -> dict:
    """판정 결과 1건을 기록 형태로 조립한다."""
    return {
        "id": str(case.get("id", "")).strip(),
        "question": case.get("question", ""),
        "expected_tool": (case.get("expected_tool") or "").strip(),
        "expected_pattern": (case.get("expected_pattern") or "").strip(),
        "called_tools": called,
        "status": status,
        "detail": detail,
        "answer": answer,
        "llm_calls": tracer.llm_calls,
        "input_tokens": tracer.input_tokens,
        "output_tokens": tracer.output_tokens,
    }


def _note(case: dict, called: list[str], answer: str, tracer) -> str:
    """비고 칸에 넣을 관찰 사항을 만든다. 중복 호출과 패턴 언급 여부를 짚는다."""
    parts = []
    total = tracer.input_tokens + tracer.output_tokens
    parts.append(f"도구 {len(called)}회, {total:,}토큰")

    if len(called) != len(set(called)):
        parts.append("같은 도구 중복 호출")

    pattern = (case.get("expected_pattern") or "").strip()
    if pattern:
        found = "언급함" if pattern in answer else "언급 없음"
        parts.append(f"{pattern} {found}")
    return " / ".join(parts)


def summarize(results: list[dict]) -> dict:
    """전체와 도구별 통과 수를 센다."""
    by_tool: dict[str, dict] = {}
    passed = 0
    for row in results:
        bucket = by_tool.setdefault(row["expected_tool"] or "(없음)", {"total": 0, "passed": 0})
        bucket["total"] += 1
        if row["status"] == PASS:
            bucket["passed"] += 1
            passed += 1
    return {"total": len(results), "passed": passed, "by_tool": by_tool}


def render_markdown(results: list[dict]) -> str:
    """report.md 1절에 그대로 붙일 표를 만든다."""
    lines = ["| id | question | expected_tool | 실제 호출 도구 | 판정 | 비고 |",
             "|---|---|---|---|---|---|"]
    for row in results:
        called = ", ".join(row["called_tools"]) if row["called_tools"] else "-"
        lines.append(
            f"| {row['id']} | {row['question']} | {row['expected_tool']}"
            f" | {called} | {row['status']} | {row['detail']} |"
        )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """CLI 인자를 해석해 평가를 돌리고 결과를 출력한다."""
    only_ids = None
    dry_run = False
    for index, arg in enumerate(argv):
        if arg == "--dry-run":
            dry_run = True
        elif arg == "--ids" and index + 1 < len(argv):
            only_ids = set()
            for token in argv[index + 1].split(","):
                if token.strip():
                    only_ids.add(token.strip())

    try:
        cases = load_cases(only_ids)
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    if not cases:
        print("[ERROR] 실행할 문항이 없습니다 (--ids 를 확인하세요).", file=sys.stderr)
        return 1

    if dry_run:
        print(f"[dry-run] {len(cases)}문항, 에이전트를 호출하지 않습니다.", file=sys.stderr)
        for case in cases:
            print(f"  {case['id']:>3}  {case['expected_tool']:16} {case['question'][:52]}")
        return 0

    load_dotenv()
    from src.agent import build_agent

    try:
        agent = build_agent()
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    results = []
    for case in cases:
        print(f"[{case['id']}] {case['question'][:48]}", file=sys.stderr, flush=True)
        results.append(run_one(agent, case))

    RESULT_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    stats = summarize(results)
    print(render_markdown(results))
    print()
    print(f"결과: {stats['passed']}/{stats['total']} 통과", file=sys.stderr)
    for tool, bucket in stats["by_tool"].items():
        print(f"  {tool:18} {bucket['passed']}/{bucket['total']}", file=sys.stderr)
    print(f"기록: {RESULT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
