"""실험 6 공용 형식 — 선택지 · 조합 목록 · 실행 기록. 관리자 소유(SESSIONS.md §인터페이스).

작업 세션은 이 형식을 기준으로 개발한다. 바꿔야 하면 관리자에게 알린다.

이 폴더의 모듈은 레포 루트를 `sys.path`에 넣고(`nikke_opt` 사용), 같은 폴더를 넣어 서로 import한다:

    HERE = Path(__file__).resolve().parent
    sys.path[:0] = [str(HERE), str(HERE.parent.parent)]
    import common, menu

테스트(레포 루트 `tests/`)는 `common.EXP_DIR`을 `sys.path`에 넣고 import한다 — `tests/test_exp06_skeleton.py` 참고.
표준 모듈과 이름이 겹치지 않게 한다(`select.py`는 `subprocess`가 쓰는 표준 `select`를 가려 `select_comps.py`로 했다).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal, Mapping, TypedDict

EXP_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXP_DIR.parent.parent
COMPOSITIONS = EXP_DIR / "compositions.json"

# 축. click·reload·cover·cancel·burst는 니케 단위(`chars.<니케>.control`), camera·tactic은 스쿼드 단위(`operation`)
Axis = Literal["click", "reload", "cover", "cancel", "burst", "camera", "tactic"]
AXES: tuple[str, ...] = ("click", "reload", "cover", "cancel", "burst", "camera", "tactic")
NIKKE_AXES = frozenset({"click", "reload", "cover", "cancel", "burst"})
SQUAD_AXES = frozenset({"camera", "tactic"})

# 실행 조건 (README §비교 조건과 탐색)
CONDITIONS: tuple[str, ...] = (
    "auto",               # operation.auto: true 한 번
    "layer",              # 운용 없음(평가기 기본 레이어) 한 번
    "search_from_layer",  # layer에서 출발한 좌표 하강
    "search_from_auto",   # auto에서 출발한 좌표 하강
    "reference",          # 무작위 재시작 · 추가 반복을 크게 쓴 참조 탐색
    "fixed_layer",        # sim.burst_gauge_mode: fixed + layer 한 번 (게이지 방식 비교)
)
START_OPTIONS: Mapping[str, Mapping[str, Any]] = {
    "layer": {},
    "auto": {"operation": {"auto": True}},
}
FIXED_GAUGE: Mapping[str, Any] = {"sim": {"burst_gauge_mode": "fixed"}}
BOSS = None  # 평가기 기본 적(허수아비, 방어력 31784). README §조건


class Variant(TypedDict):
    """선택지 하나. `menu.variants()`가 만든다.

    - `nikke`: 니케 정식 명칭. 스쿼드 단위 축(camera·tactic)은 None.
    - `axis`: AXES 중 하나.
    - `label`: 스쿼드 안에서 유일한 이름. 형식 `"<니케 또는 squad>:<axis>:<이름>"` (예: `"에이다:click:hold_own_fb"`).
      기록·분석은 label로 선택을 식별한다. 같은 니케·축·이름이면 조합이 달라도 같은 label이어야 한다(니케 고유성 분석).
    - `patch`: 요청 options 조각. `{"chars": {니케: {"control": {...}}}}` 또는 `{"operation": {...}}`.
    """

    nikke: str | None
    axis: str
    label: str
    patch: dict[str, Any]


class Composition(TypedDict):
    """`compositions.json`의 원소. W3가 만든다."""

    id: str                 # 예 "c01"
    squad: list[str]        # 배치 순서 그대로 (정식 명칭)
    skeleton: str           # 버스트 틀 "1-1-3" · "1-2-2" · "2-1-2" · "redhood" 등
    tags: list[str]         # 예 ["layer_target", "charge_heavy", "charger_candidate"]
    source: str             # 출처 (랭커 덱 id 등)
    default_damage: int     # 기본 레이어 + accumulate 총딜


class Record(TypedDict):
    """실행 기록 JSON Lines 한 줄. W4가 쓰고 W5가 읽는다.

    - `condition`: CONDITIONS 중 하나.
    - `start`: 출발점 이름 — "layer" · "auto" · 참조 탐색은 "random:<seed>".
    - `step`: 그 (조합, 조건, 출발점) 안에서의 평가 순번(0 = 출발점).
    - `variants`: 이 평가에 적용한 선택지 label 목록(정렬). 출발점은 [].
    - `request`: 평가기에 보낸 요청 줄 전문(`EvalRequest.to_line()`).
    - `total_damage`: 오류면 None. `control_detail`: 결과의 `control_detail` 그대로.
    - `cached`: 캐시 적중. `error`: 결과의 error 또는 None. `evaluator`: 평가기 version dict.
    - `sim_count`: 이 줄을 쓴 시점까지 그 실행(프로세스)에서 실제로 돈 시뮬 누계.
    """

    comp_id: str
    condition: str
    start: str
    step: int
    variants: list[str]
    request: dict[str, Any]
    total_damage: int | None
    control_detail: dict[str, Any] | None
    cached: bool
    error: dict[str, Any] | None
    evaluator: dict[str, Any]
    sim_count: int


RECORD_KEYS: tuple[str, ...] = tuple(Record.__annotations__)


def deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """dict는 재귀로 합치고, 그 밖의 값(list 포함)은 patch가 덮는다. 입력은 바꾸지 않는다."""
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = json.loads(json.dumps(v)) if isinstance(v, (dict, list)) else v
    return out


def load_compositions(path: Path = COMPOSITIONS) -> list[Composition]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_records(paths: Iterable[Path]) -> Iterator[Record]:
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


def append_record(path: Path, rec: Mapping[str, Any]) -> None:
    missing = [k for k in RECORD_KEYS if k not in rec]
    if missing:
        raise ValueError(f"기록에 빠진 칸: {missing}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
