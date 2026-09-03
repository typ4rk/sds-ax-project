"""(내부) 저장된 매칭 값의 문자 구조를 분석해 정규식 후보를 만들어 낸다.

_matcher.py가 "정규식 → 값"(매칭)이라면 이 모듈은 "값 → 정규식"(귀납)으로 역방향이다.
DB·파일·네트워크에 접근하지 않는 순수 함수만 두므로 오프라인에서 그대로 검증할 수 있다.

임베딩을 쓰지 않는다. 정규식에 필요한 정보는 문자 클래스·길이·구분자 위치·리터럴
앵커인데, 이는 텍스트 임베딩이 인코딩하지 못하는 구조적 정보이기 때문이다.
"""

import json
import math
import os
import re
from collections import Counter, defaultdict

# 군집을 만들 때 필요한 최소 표본 수. 이보다 적으면 값 하나를 그대로 베낀 정규식이 나온다.
MIN_CLUSTER = 3
# 문자 클래스 크기를 추정할 때 '+'나 '*'를 몇 회 반복으로 볼지. tightness 비교용 근사값이다.
UNBOUNDED_REPEAT = 8

# 영숫자와 함께 한 덩어리로 볼 문자. 서브도메인·식별자에 흔히 섞인다.
_WORD_EXTRA = "-_"


def shape_signature(value: str, coarse: bool = False) -> str:
    """문자열을 문자 클래스 시그니처로 바꾼다.

    coarse=False(fine)는 소문자 L / 대문자 U / 숫자 D 를 구분해 이어붙인다.
    coarse=True는 영숫자와 '-_' 덩어리를 전부 W로 접는다.

    fine은 'blog2'를 LD로, 'search-api'를 L-L로 만들어 군집을 과도하게 쪼개므로
    군집 키로는 coarse를 쓰고, fine은 문자 클래스를 추론하는 근거로만 쓴다.
    """
    out: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if coarse:
            kind = "W" if (char.isalnum() or char in _WORD_EXTRA) else None
        elif char.islower():
            kind = "L"
        elif char.isupper():
            kind = "U"
        elif char.isdigit():
            kind = "D"
        else:
            kind = None

        if kind is None:
            out.append(char)
            index += 1
            continue

        # 같은 종류가 이어지는 동안 한 덩어리로 묶는다.
        while index < len(value) and _same_kind(value[index], kind, coarse):
            index += 1
        out.append(kind)
    return "".join(out)


def _same_kind(char: str, kind: str, coarse: bool) -> bool:
    """문자가 시그니처 종류(kind)에 속하는지 판단한다."""
    if coarse:
        return char.isalnum() or char in _WORD_EXTRA
    if kind == "L":
        return char.islower()
    if kind == "U":
        return char.isupper()
    if kind == "D":
        return char.isdigit()
    return False


def collapse_repeats(signature: str) -> str:
    """깊이만 다른 시그니처를 하나로 접는다.

    'W://W.W.W'와 'W://W.W.W.W'는 서브도메인 깊이만 다를 뿐 같은 계열이므로
    둘 다 'W://(W.)+W'로 만들어 같은 군집에 들어가게 한다.
    """
    return re.sub(r"(?:W\.)+W", "(W.)+W", signature)


def cluster_by_shape(values: list[str]) -> dict[str, list[str]]:
    """값을 coarse 시그니처로 묶고 반복 구조를 축약해 군집을 만든다.

    반환값은 {축약된 시그니처: 그 시그니처를 가진 값 목록}이며, 값은 중복을 제거한다.
    """
    clusters: dict[str, list[str]] = defaultdict(list)
    for value in sorted(set(v for v in values if v)):
        clusters[collapse_repeats(shape_signature(value, coarse=True))].append(value)
    return dict(clusters)


def values_by_key(texts: list[str]) -> dict[str, list[str]]:
    """JSON 본문 여러 건에서 같은 키의 값끼리 모아 돌려준다.

    본문 하나를 통째로 귀납에 넣으면 의미 있는 정규식이 나오지 않는다. 반면 같은 키의
    값들(예: 여러 요청의 bizCd)은 같은 형식일 가능성이 높아 귀납 입력으로 적합하다.
    중첩된 dict·list를 따라 내려가며 잎 값만 모으고, 값은 중복을 제거한다.

    JSON이 아닌 본문은 건너뛴다 — 형식을 알 수 없는 텍스트에서 키를 나눌 수 없다.
    """
    buckets: dict[str, set[str]] = defaultdict(set)

    def walk(node, key: str | None) -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                walk(value, name)
        elif isinstance(node, list):
            for value in node:
                walk(value, key)
        elif node is not None and key:
            buckets[key].add(str(node))

    for text in texts:
        try:
            walk(json.loads(text), None)
        except (json.JSONDecodeError, TypeError):
            continue
    return {key: sorted(values) for key, values in buckets.items()}


def induce_regex(values: list[str], min_cluster: int = MIN_CLUSTER) -> list[dict]:
    """한 군집의 값들에서 공통 접두/접미를 뽑고 가변부를 일반화해 후보를 만든다.

    공통 접두사(LCP)와 공통 접미사(LCS)는 고정 리터럴(앵커)로 두고, 그 사이 가변부만
    관측된 문자로 문자 클래스를 만들어 일반화한다. LCS가 '.naver.com'처럼 길게 나오면
    그 자체가 "이 군집은 무엇인가"를 데이터에서 유도한 것이다.

    strict(관측 범위 그대로) / open(반복 무제한) / bounded(우측 경계 추가) 세 변형을
    각각의 근거와 함께 돌려준다. 컴파일에 실패하는 후보는 제외한다.
    """
    uniq = sorted(set(v for v in values if v))
    if len(uniq) < min_cluster:
        return []

    prefix = os.path.commonprefix(uniq)
    suffix = _common_suffix(uniq)
    # 짧은 값 하나가 통째로 접두+접미에 먹히면 가변부가 사라지므로 접미를 줄인다.
    while suffix and any(len(prefix) + len(suffix) >= len(v) for v in uniq):
        suffix = suffix[1:]

    mids = [_middle(v, prefix, suffix) for v in uniq]
    separator = _dominant_separator(mids)

    if separator and suffix.startswith(separator):
        # 구분자를 가변부 쪽으로 옮겨 '(?:CC\.){lo,hi}' 형태로 접을 수 있게 한다.
        suffix = suffix[len(separator):]
        mids = [_middle(v, prefix, suffix) for v in uniq]

    if separator:
        body_variants = _repeating_body(mids, separator)
    else:
        body_variants = _blob_body(mids)
    if not body_variants:
        return []

    head, tail = re.escape(prefix), re.escape(suffix)
    candidates = []
    for variant, body in body_variants.items():
        regex = head + body + tail
        if variant == "bounded":
            regex += r"(?![\w.-])"
        if not _compiles(regex):
            continue
        candidates.append(
            {
                "variant": variant,
                "regex": regex,
                "support": len(uniq),
                "prefix": prefix,
                "suffix": suffix,
                "lcs_len": len(suffix),
                "samples": uniq[:5],
                "tightness": estimate_tightness(regex),
            }
        )
    return candidates


def _middle(value: str, prefix: str, suffix: str) -> str:
    """값에서 공통 접두/접미를 뺀 가변부를 잘라낸다."""
    end = len(value) - len(suffix) if suffix else len(value)
    return value[len(prefix):end]


def _common_suffix(values: list[str]) -> str:
    """값들의 최장 공통 접미사를 구한다."""
    return os.path.commonprefix([v[::-1] for v in values])[::-1]


def _dominant_separator(mids: list[str]) -> str | None:
    """가변부에서 가장 자주 쓰인 구분자를 고른다. 없으면 None."""
    counts = Counter(
        char
        for mid in mids
        for char in mid
        if not char.isalnum() and char not in _WORD_EXTRA
    )
    return counts.most_common(1)[0][0] if counts else None


def _repeating_body(mids: list[str], separator: str) -> dict[str, str]:
    """구분자로 쪼갠 세그먼트를 문자 클래스와 반복 범위로 일반화한다."""
    segment_lists = [[s for s in mid.split(separator) if s] for mid in mids]
    if not any(segment_lists):
        return {}
    chars = {c for segments in segment_lists for s in segments for c in s}
    if not chars:
        return {}
    klass = _char_class(chars)
    low = min(len(s) for s in segment_lists)
    high = max(len(s) for s in segment_lists)
    unit = f"(?:{klass}+{re.escape(separator)})"
    return {
        "strict": f"{unit}{_repeat_spec(low, high)}",
        "open": f"{unit}+",
        "bounded": f"{unit}+",
    }


def _blob_body(mids: list[str]) -> dict[str, str]:
    """구분자가 없는 가변부를 문자 클래스와 길이 범위로 일반화한다."""
    chars = {c for mid in mids for c in mid}
    if not chars:
        return {}
    klass = _char_class(chars)
    low, high = min(len(m) for m in mids), max(len(m) for m in mids)
    if low == 0:
        return {}
    return {
        "strict": f"{klass}{_repeat_spec(low, high)}",
        "open": f"{klass}{{{low},}}",
        "bounded": f"{klass}{{{low},}}",
    }


def _repeat_spec(low: int, high: int) -> str:
    """반복 횟수를 정규식 수량자로 적는다. 하한과 상한이 같으면 {n,n} 대신 {n}으로 쓴다."""
    return f"{{{low}}}" if low == high else f"{{{low},{high}}}"


def _char_class(chars: set[str]) -> str:
    """관측된 문자들의 합집합으로 문자 클래스를 만든다.

    소문자/대문자/숫자는 범위로 접고, 나머지는 그대로 나열한다.
    '-'는 클래스 안에서 범위 기호이므로 항상 맨 뒤에 둔다.
    """
    rest = set(chars)
    parts = []
    for label, test in (("a-z", str.islower), ("A-Z", str.isupper), ("0-9", str.isdigit)):
        hits = {c for c in rest if test(c)}
        if hits:
            parts.append(label)
            rest -= hits
    extras = "".join(
        ("\\" + c if c in "]^\\" else c) for c in sorted(rest) if c != "-"
    )
    return "[" + "".join(parts) + extras + ("-" if "-" in chars else "") + "]"


def synthetic_negatives(prefix: str, suffix: str) -> list[str]:
    """공통 접두/접미를 규칙적으로 훼손해 과일반화 점검용 음성 표본을 만든다.

    앵커가 제 역할을 한다면 후보 정규식은 이 값들을 잡지 않아야 한다.
    음성 코퍼스가 따로 없는 상황에서 정밀도를 근사하는 값싼 방법이다.
    """
    body = "sample"
    core = suffix.lstrip(".") or "anchor"
    negatives = [
        f"{prefix}{body}{suffix}.attacker.io",   # 접미 확장
        f"{prefix}{body}{suffix[:-1]}",          # 접미 절단
        f"{prefix}not{core}",                    # 접두 침식
        f"{prefix}{body}{suffix}.co.kr",         # 우측 경계
    ]
    if prefix.startswith("https://"):
        negatives.append("http://" + prefix[len("https://"):] + body + suffix)
        negatives.append(f"{prefix}{body}.daum.net")
    return [n for n in negatives if n]


def evaluate_candidate(
    candidate: str,
    positives: list[str],
    corpus: list[str] | None = None,
    baseline: str | None = None,
    negatives: list[str] | None = None,
) -> dict:
    """후보 정규식을 저장된 값과 코퍼스에 돌려 점수를 매긴다.

    positives는 후보가 반드시 잡아야 할 값(원본 패턴이 이미 잡은 값)이므로,
    여기서 나오는 coverage는 참 재현율이 아니라 회귀 테스트로 읽어야 한다.
    corpus는 정규식이 적용된 적 없는 부수 텍스트라 추가 탐지(gained)를 세는 데 쓴다.

    반환 항목: compiles, coverage, gained, lost, negative_block_rate,
    tightness, redos_risk
    """
    result = {
        "regex": candidate,
        "compiles": _compiles(candidate),
        "coverage": 0.0,
        "gained": [],
        "lost": [],
        "negative_block_rate": None,
        "tightness": estimate_tightness(candidate),
        "redos_risk": has_nested_quantifier(candidate),
    }
    if not result["compiles"]:
        return result

    rx = re.compile(candidate)
    if positives:
        hits = [v for v in positives if rx.fullmatch(v)]
        result["coverage"] = len(hits) / len(positives)

    if corpus and baseline and _compiles(baseline):
        base = re.compile(baseline)
        new_hits = {t for t in corpus if rx.search(t)}
        old_hits = {t for t in corpus if base.search(t)}
        result["gained"] = sorted(new_hits - old_hits)
        result["lost"] = sorted(old_hits - new_hits)

    if negatives:
        blocked = sum(1 for n in negatives if not rx.search(n))
        result["negative_block_rate"] = blocked / len(negatives)
    return result


def relax_regex(regex: str, depth: int = 2) -> list[dict]:
    """엄격한 정규식을 축별로 한 단계씩 완화한 변형을 만든다.

    매칭이 0건인 tight 패턴은 귀납할 씨앗이 없으므로, 반대로 정규식 자체를 풀어
    어느 축에서 매칭이 생기는지로 병목을 특정한다. depth=2면 축 두 개를 조합한
    변형까지 만든다. 컴파일되지 않는 변형은 버린다.
    """
    axes = {
        "quantifier": _relax_quantifier,
        "charclass": _relax_charclass,
        "separator": _relax_separator,
        "literal": _relax_literal,
        "scheme": _relax_scheme,
    }
    variants: dict[str, dict] = {}
    names = list(axes)

    for name in names:
        changed = axes[name](regex)
        if changed != regex and _compiles(changed):
            variants[changed] = {"regex": changed, "axes": [name]}

    if depth >= 2:
        for first in names:
            once = axes[first](regex)
            if once == regex:
                continue
            for second in names:
                if second == first:
                    continue
                twice = axes[second](once)
                if twice != once and twice not in variants and _compiles(twice):
                    variants[twice] = {"regex": twice, "axes": [first, second]}

    return list(variants.values())


def _relax_quantifier(regex: str) -> str:
    """{n,} 와 {n,m} 의 하한을 절반으로, 상한을 두 배로 넓힌다."""

    def widen(match: re.Match) -> str:
        low = max(1, int(match.group(1)) // 2)
        high = match.group(2)
        if high is None:
            return "{%d,}" % low
        return "{%d,%d}" % (low, int(high) * 2)

    return re.sub(r"\{(\d+),(\d+)?\}", widen, regex)


def _relax_charclass(regex: str) -> str:
    """문자 클래스에 밑줄과 하이픈을 더해 허용 범위를 넓힌다."""
    return regex.replace("[A-Za-z0-9]", "[A-Za-z0-9_-]").replace("[a-z]", "[a-z0-9-]")


def _relax_separator(regex: str) -> str:
    """리터럴 구분자 '_'를 [-_.] 로 바꿔 표기 차이를 흡수한다."""
    return regex.replace("_", "[-_.]") if "_" in regex else regex


def _relax_literal(regex: str) -> str:
    """환경을 가리키는 리터럴 토큰을 흔한 대안들로 열어 준다."""
    for token in ("live", "prod", "test", "dev", "stage"):
        if token in regex:
            return regex.replace(token, "(?:live|test|prod|dev|stage)", 1)
    return regex


def _relax_scheme(regex: str) -> str:
    """https 고정을 http 까지 허용하도록 바꾼다."""
    return regex.replace("https://", "https?://") if "https://" in regex else regex


def estimate_tightness(regex: str) -> float:
    """정규식이 허용하는 문자열 공간의 크기를 로그 스케일로 근사한다.

    작을수록 좁다(tight). 리터럴은 0, 문자 클래스는 크기의 로그에 반복 횟수를 곱하며,
    그룹에 붙은 수량자는 그 안쪽 전체에 곱해진다.

    비교는 **같은 귀납 계열 안에서만** 유효하다(strict < bounded < open). 구조가 다른
    정규식끼리 비교하면 오해를 부른다 — 무한 반복을 상수로 근사하기 때문에, 실제로는
    더 느슨한 패턴이 더 작은 값을 받을 수 있다. 후보 채택 판단은 coverage와 합성 음성
    차단율로 하고, 이 값은 한 계열의 변형을 늘어놓는 데만 쓴다.

    전방·후방 탐색은 문자열을 만들어내지 않고 오히려 제약하므로, 크기 계산에서 빼고
    대신 제약 하나당 소폭 감점한다(경계를 붙인 후보가 더 tight하게 정렬되도록).
    """
    body, assertions = _strip_assertions(regex)
    total = 0.0

    # 그룹에 붙은 수량자는 안쪽 문자 클래스 전체에 곱해지므로 먼저 처리하고 걷어낸다.
    def take_group(match: re.Match) -> str:
        inner, repeat = match.group(1), match.group(2)
        nonlocal total
        total += _scan_classes(inner) * _repeat_count(repeat)
        return ""

    remainder = re.sub(r"\((?:\?:)?([^()]*)\)(\{\d+(?:,\d*)?\}|[+*?])?", take_group, body)
    total += _scan_classes(remainder)
    return round(max(total - 0.5 * assertions, 0.0), 2)


def _strip_assertions(regex: str) -> tuple[str, int]:
    """전방·후방 탐색을 떼어내고 그 개수를 함께 돌려준다."""
    pattern = r"\(\?(?:=|!|<=|<!)[^()]*\)"
    return re.sub(pattern, "", regex), len(re.findall(pattern, regex))


def _scan_classes(fragment: str) -> float:
    """조각 안의 문자 클래스들이 만들어내는 공간 크기를 더한다."""
    total = 0.0
    for klass, repeat in re.findall(
        r"(\[[^\]]+\]|\\w|\\d)(\{\d+(?:,\d*)?\}|[+*?])?", fragment
    ):
        total += math.log10(max(_class_size(klass), 2)) * _repeat_count(repeat)
    return total


def _class_size(klass: str) -> int:
    """문자 클래스가 허용하는 문자 개수를 센다."""
    if klass == r"\w":
        return 63
    if klass == r"\d":
        return 10
    size = 0
    body = klass[1:-1]
    for label, count in (("a-z", 26), ("A-Z", 26), ("0-9", 10)):
        if label in body:
            size += count
            body = body.replace(label, "")
    return size + len(body)


def _repeat_count(repeat: str) -> int:
    """반복 수량자에서 대표 반복 횟수를 뽑는다. 무한 반복은 상수로 근사한다."""
    if not repeat or repeat == "?":
        return 1
    if repeat in ("+", "*"):
        return UNBOUNDED_REPEAT
    inner = repeat.strip("{}")
    low, _, high = inner.partition(",")
    if high:
        return int(high)
    if _:
        return max(int(low), UNBOUNDED_REPEAT)
    return int(low)


def has_nested_quantifier(regex: str) -> bool:
    """중첩 수량자를 찾아 폭발적 백트래킹(ReDoS) 위험을 정적으로 점검한다."""
    return bool(re.search(r"\([^)]*[+*]\)[+*]", regex))


def _compiles(regex: str) -> bool:
    """정규식이 컴파일되는지 확인한다."""
    try:
        re.compile(regex)
    except re.error:
        return False
    return True
