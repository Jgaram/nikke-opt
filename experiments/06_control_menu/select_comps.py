"""실험 6 W3 — 조합 약 30개 선정 → compositions.json · selection.md. (골격: 관리자. 구현: W3)

규칙은 README §평가 문제. 규칙을 코드로 고정하고, 컨트롤 결과를 보기 전에 고른다.
출력 형식은 common.Composition. 과정·니케별 등장 조합 수·사용한 시뮬 수는 selection.md에 남긴다.
(`select.py`가 아닌 이유: 표준 모듈 `select`를 가린다 — common.py 참고)

두 단계로 나눈다(평가기는 둘째 단계에만 필요하다):

    python experiments/06_control_menu/select_comps.py candidates [--out 후보.json]
        규칙으로 후보를 만든다(평가기 불필요). selection.md에 방법과 후보 요약을 쓴다.
    python experiments/06_control_menu/select_comps.py extract /home/user/jgaram/nikke-calc
        (재현 확인) nikke-calc 데이터에서 NIKKE_INFO를 다시 뽑아 내장 값과 비교한다(다르면 종료 코드 1).
    source .cache/evaluators.env && python experiments/06_control_menu/select_comps.py pick
        후보를 기본 레이어 + accumulate(어댑터 기본 sim, 기본 적)로 평가해 성능 구간을 정하고,
        고정 규칙(시드 고정)으로 약 30개를 골라 compositions.json과 selection.md를 쓴다.

후보 (`candidates()`, 결정론적):
1. **랭커 구성** — 실험 2 `ranker_squads.json`의 구성(순서 무시) 66개. 배치 순서는 그 구성의 랭커 최빈 순서
   (ranker_squads는 빈도 내림차순이라 처음 나온 순서).
2. **한 명 교체** — 랭커 구성(빈도순)의 한 자리를 같은 버스트 단계의 풀 니케로 바꾼다. 바뀐 니케는 그 자리에 둔다
   (나머지 순서는 랭커 최빈 순서 그대로). 니케마다 만드는 수에 상한을 둔다 — 기본 레이어 대상 9명은 `CAP_FOCUS`,
   레드 후드는 `CAP_REDHOOD`(그 틀은 교체로만 생긴다 — 랭커가 쓰지 않았다), 나머지는 `CAP_OTHER`. 랭커 구성 하나에서 니케 하나는 한 번만 넣고, 넣을 자리는 돌아가며 고른다.
   레드 후드(전 단계)는 B2·B3 자리에 넣어 (1,1,2)+A · (2,1,1)+A 틀만 만든다(실험 2와 같은 틀).
   에이다의 기본 레이어는 미란다와 함께일 때만 붙으므로 에이다는 미란다가 든 구성부터 넣는다.

선정 (`select()`, 평가 결과만 입력):
1. 오류 후보를 뺀다. 버스트 틀마다 기본 레이어 딜 순으로 3등분해 상·중·하를 매기고 하를 뺀다.
   틀마다 나누는 이유: 레드 후드 틀은 전체 분포에서 약하다(실험 2 §3). 한 줄로 자르면 그 틀이 통째로 빠진다.
2. 씨앗 — 레이어 대상 9명(정해진 순서)마다 그 니케가 든 후보를 아래 점수로 골라 3개 조합까지 넣는다.
   탐욕 선정 — 틀별 할당(`QUOTA`)을 넘지 않는 후보 중 점수가 가장 높은 것을 하나씩 더한다. 동점은 시드 고정 순서.
   점수: 이미 1~2번 나온 니케(3번 채우기) 가산, 처음 나오는 니케 감산, 기본 레이어 대상 가산,
   틀 안 상·중 균형, 틀 안 레이어 대상 포함·미포함 균형, 랭커 구성 가산, 차지형 수 · base 충전 추정 구간의 다양성.
3. 수리 — 등장 1~2회인 니케가 남으면 그 니케가 들고 새 니케를 들이지 않는 후보를 더하거나(전체 `MAX_N`까지),
   안 되면 같은 틀의 조합 하나와 맞바꾸거나(빼도 3회 이상이던 니케가 3회 밑으로 내려가지 않을 때), 그래도 안 되면
   그 니케가 든 조합을 뺀다. 끝나고 `MIN_N`보다 적으면 새 니케 없는 후보로 채운다.

니케 정보(`NIKKE_INFO`)는 공개 원본 nikke-calc `23164e4`의 `data/parsed_nikke.json` · `data/weapon_delays.json`에서
읽기 전용으로 뽑아 이 파일에 넣었다(평가기 코드 import 없음, 런타임에 그 체크아웃이 필요 없다).
`gauge_rate`는 무기 사격만으로 낸 **정적 추정** 게이지 속도(%/초, 탄창 + 재장전 주기 평균, 스킬 충전 · 풀차지 배율 ·
카메라 제외)다. 조합의 base 충전 추정 = 100 / Σ gauge_rate. 실제 base 충전 시간(nikke-calc CONTROL.md §버충 컨트롤,
3.2초 기준)은 시뮬 결과라 평가기 결과에 나오지 않는다 — 여기서는 후보 사이의 상대 순위(3등분)로만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent)]
import common  # noqa: E402

EXP2 = common.REPO_ROOT / "experiments" / "02_score_distribution"
POOL_JSON = EXP2 / "pool.json"
RANKER_JSON = EXP2 / "ranker_squads.json"
SELECTION_MD = HERE / "selection.md"
CALC_SOURCE = "Jgaram/nikke-calc 23164e4 (data/parsed_nikke.json · data/weapon_delays.json)"

SEED = 20261029
REDHOOD = "레드 후드"
# 평가기 기본 레이어 대상 중 풀에 있는 9명 (README §평가 문제, nikke-calc CONTROL.md §캐릭터별 기본 컨트롤)
LAYER_TARGETS: tuple[str, ...] = ("앨리스", "에이다", "미하라 : 본딩 체인", "홍련 : 흑영", "마스트 : 로망틱 메이드",
                                  "미란다", "츠바이", "토브", "프리카")
MIRANDA_RULE = ("에이다", "미하라 : 본딩 체인")  # 미란다와 함께일 때만 레이어가 붙는다
SKELETONS: tuple[str, ...] = ("1-1-3", "1-2-2", "2-1-2", "redhood")
REDHOOD_FRAMES = {(1, 1, 2), (2, 1, 1)}  # 레드 후드를 뺀 B1·B2·B3 인원
QUOTA = {"1-1-3": 9, "1-2-2": 8, "2-1-2": 7, "redhood": 6}  # 합 30. 랭커 빈도순, 레드 후드 틀도 비교가 되게
TARGET_N, MIN_N, MAX_N = 30, 28, 32
MIN_APPEAR = 3  # 같은 니케가 서로 다른 동료와 나오는 최소 조합 수
CAP_FOCUS, CAP_REDHOOD, CAP_OTHER = 12, 24, 3  # 한 명 교체 후보 상한 (레이어 대상 9명 / 레드 후드 / 그 밖)

# 니케 → (무기, 차지형, 입력 방식, 풀차지 전용, 정적 게이지 속도 %/초). 출처 CALC_SOURCE. 풀 60명
NIKKE_INFO: dict[str, tuple[str, bool, str, bool, float]] = {
    '2B': ('AR', False, 'DOWN', False, 4.235),
    'D : 킬러 와이프': ('SR', True, 'UP', False, 3.268),
    '그레이브': ('AR', False, 'DOWN', False, 9.0),
    '나가': ('SG', False, 'DOWN', False, 4.8),
    '나유타': ('SMG', False, 'DOWN', False, 3.692),
    '도라': ('SR', True, 'UP', False, 3.268),
    '도로시 : 세렌디피티': ('SG', False, 'DOWN', False, 4.8),
    '드레이크': ('SG', False, 'DOWN', False, 12.462),
    '디젤 : 윈터 스위츠': ('RL', True, 'UP', False, 1.634),
    '라피 : 레드 후드': ('MG', False, 'DOWN', False, 4.0),
    '레드 후드': ('SR', True, 'UP', False, 3.268),
    '레이': ('MG', False, 'DOWN', False, 4.0),
    '레이 (가칭)': ('AR', False, 'DOWN', False, 4.615),
    '레이븐': ('RL', True, 'UP', True, 1.175),
    '루드밀라 : 윈터 오너': ('MG', False, 'DOWN', False, 3.75),
    '루주': ('SR', True, 'UP', False, 3.28),
    '리버렐리오': ('SR', True, 'DOWN_Charge', True, 2.922),
    '리타': ('SMG', False, 'DOWN', False, 3.692),
    '리틀 머메이드': ('SMG', False, 'DOWN', False, 4.0),
    '마르차나 : 마린 스터디': ('AR', False, 'DOWN', False, 4.0),
    '마스트 : 로망틱 메이드': ('MG', False, 'DOWN', False, 4.0),
    '맥스웰': ('SR', True, 'UP', False, 3.268),
    '모더니아': ('MG', False, 'DOWN', False, 4.11),
    '목단': ('AR', False, 'DOWN', False, 4.615),
    '미란다': ('SMG', False, 'DOWN', False, 3.733),
    '미하라 : 본딩 체인': ('MG', False, 'DOWN', False, 4.0),
    '민트': ('RL', True, 'UP', False, 1.634),
    '벨벳': ('SR', True, 'UP', False, 3.268),
    '볼륨': ('SMG', False, 'DOWN', False, 3.692),
    '브래디': ('SR', True, 'UP', False, 3.268),
    '브리드 : 사일런트 트랙': ('SG', False, 'DOWN', False, 4.8),
    '솔린 : 프로스트 티켓': ('SG', False, 'DOWN', False, 4.8),
    '슈가': ('SG', False, 'DOWN', False, 12.144),
    '스노우 화이트 : 헤비암즈': ('SR', True, 'UP', False, 2.927),
    '신데렐라': ('RL', True, 'DOWN_Charge', True, 0.415),
    '신데렐라 : 크리스탈 웨이브': ('MG', False, 'DOWN', False, 4.0),
    '아니스 : 스타': ('RL', True, 'DOWN_Charge', True, 1.976),
    '아르카나 : 포츈 메이트': ('SG', False, 'DOWN', False, 4.322),
    '아스카': ('AR', False, 'DOWN', False, 4.5),
    '아스카 : WILLE': ('MG', False, 'DOWN', False, 4.093),
    '아크레인저 블랙': ('AR', False, 'DOWN', False, 4.0),
    '앨리스': ('SR', True, 'UP', False, 2.53),
    '앵커 : 이노센트 메이드': ('RL', True, 'UP', False, 1.634),
    '에이다': ('RL', True, 'UP', False, 1.634),
    '유키코': ('MG', False, 'DOWN', False, 4.0),
    '이브': ('AR', False, 'DOWN', False, 4.0),
    '일레그 : 붐 앤 쇼크': ('MG', False, 'DOWN', False, 4.0),
    '츠바이': ('SG', False, 'DOWN', False, 8.4),
    '치사토': ('SMG', False, 'DOWN', False, 4.0),
    '퀀시 : 이스케이프 퀸': ('SMG', False, 'DOWN', False, 5.92),
    '퀸(마코토)': ('SG', False, 'DOWN', False, 4.8),
    '크라운': ('MG', False, 'DOWN', False, 4.0),
    '타키나': ('SR', True, 'UP', False, 3.268),
    '토브': ('AR', False, 'DOWN', False, 4.0),
    '프리바티': ('AR', False, 'DOWN', False, 4.0),
    '프리카': ('SR', True, 'UP', False, 3.268),
    '플로라': ('MG', False, 'DOWN', False, 4.0),
    '헬름': ('SR', True, 'UP', False, 3.268),
    '헬름 : 아쿠아마린': ('AR', False, 'DOWN', False, 4.0),
    '홍련 : 흑영': ('RL', True, 'UP', True, 2.571),
}


# ---------------------------------------------------------------- 니케 정보 추출 (재현용)

def extract_info(calc_dir: Path, names: Sequence[str]) -> dict[str, tuple[str, bool, str, bool, float]]:
    """nikke-calc 체크아웃의 데이터 파일(읽기 전용)에서 NIKKE_INFO를 다시 만든다. 평가기 코드는 import하지 않는다.

    게이지 속도 = burst_energy × 펠릿 × 총구 × 탄창 / (탄창 × 발사 주기 + 재장전 + 재장전 후 딜레이).
    발사 주기: 비차지 1/연사(MG는 예열 끝 60발/초), 차지 = 차지 시간 + 발사 후 딜레이
    (UP: 0.22 + max(0.16, fire_stance_hold), DOWN_Charge: 0 — weapon_delays.json _comment의 유도식).
    """
    data = calc_dir / "data"
    nikke = json.loads((data / "parsed_nikke.json").read_text(encoding="utf-8"))
    exc = json.loads((data / "weapon_delays.json").read_text(encoding="utf-8"))["_exceptions"]
    out = {}
    for name in sorted(names):
        v = dict(nikke[name])
        v.update({k: x for k, x in exc.get(name, {}).items() if not k.startswith("_")})
        if v["is_charge"]:
            pfd = 0.0 if v["input_type"] == "DOWN_Charge" else 0.22 + max(0.16, v.get("fire_stance_hold") or 0)
            period = v["charge_time"] + v.get("post_fire_delay", pfd)
        else:
            period = 1 / (60.0 if v["weapon_type"] == "MG" else v["fire_rate"])
        cyc = v["max_ammo"] * period + v["reload_time"] + v.get("post_reload_delay", 0)
        rate = v["burst_energy"] * v["pellets"] * v["muzzles"] * v["max_ammo"] / cyc
        out[name] = (v["weapon_type"], bool(v["is_charge"]), v["input_type"], bool(v["full_charge_only"]),
                     round(rate, 3))
    return out


# ---------------------------------------------------------------- 출처와 정적 특징

def load_sources(pool_path: Path = POOL_JSON, ranker_path: Path = RANKER_JSON) -> tuple[dict[str, str], list[dict]]:
    """(니케 → 버스트 단계 "1"·"2"·"3"·"A", ranker_squads의 squads 목록)."""
    pool = json.loads(pool_path.read_text(encoding="utf-8"))["pool"]
    ranker = json.loads(ranker_path.read_text(encoding="utf-8"))["squads"]
    return {k: v["burst"] for k, v in pool.items()}, ranker


def stage_counts(squad: Sequence[str], burst: Mapping[str, str]) -> tuple[int, int, int, int]:
    b = [burst[m] for m in squad]
    return b.count("1"), b.count("2"), b.count("3"), b.count("A")


def skeleton(squad: Sequence[str], burst: Mapping[str, str]) -> str:
    """버스트 틀. 레드 후드(전 단계)가 있으면 "redhood", 아니면 "B1-B2-B3" 인원."""
    b1, b2, b3, a = stage_counts(squad, burst)
    return "redhood" if a else f"{b1}-{b2}-{b3}"


def charge_count(squad: Sequence[str]) -> int:
    return sum(NIKKE_INFO[m][1] for m in squad)


def charger_candidates(squad: Sequence[str]) -> list[str]:
    """버충 담당이 될 수 있는 니케 — 차지형이고 톡톡이가 되는(UP 입력, 풀차지 전용 아님) 니케."""
    return [m for m in squad if NIKKE_INFO[m][1] and NIKKE_INFO[m][2] == "UP" and not NIKKE_INFO[m][3]]


def est_charge_time(squad: Sequence[str]) -> float:
    """base 충전 추정(초) = 100 / Σ 정적 게이지 속도. 상대 비교용(모듈 docstring)."""
    return 100.0 / sum(NIKKE_INFO[m][4] for m in squad)


def charge_bucket(squad: Sequence[str]) -> str:
    """차지형 수 구간: 0 · 1 · 2 · 3명 이상."""
    return ("charge_none", "charge_light", "charge_mid", "charge_heavy")[min(charge_count(squad), 3)]


def layer_members(squad: Sequence[str]) -> list[str]:
    return [m for m in squad if m in LAYER_TARGETS]


def miranda_rule(squad: Sequence[str]) -> bool:
    return "미란다" in squad and any(m in squad for m in MIRANDA_RULE)


# ---------------------------------------------------------------- 1단계: 후보

def base_compositions(ranker: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """랭커 구성(순서 무시)마다 최빈 순서와 덱 수. 덱 수 내림차순(동률은 처음 나온 순서)."""
    seen: dict[frozenset, dict[str, Any]] = {}
    for i, s in enumerate(ranker):
        k = frozenset(s["squad"])
        if k not in seen:  # ranker_squads는 순서 구분 스쿼드를 빈도 내림차순으로 둔다 → 처음 것이 최빈 순서
            seen[k] = {"squad": list(s["squad"]), "decks": 0, "ranker_index": i}
        seen[k]["decks"] += s["count"]
    return sorted(seen.values(), key=lambda b: (-b["decks"], b["ranker_index"]))


def _swap_slots(base: Sequence[str], x: str, burst: Mapping[str, str]) -> list[int]:
    if x in base:
        return []
    if burst[x] != "A":
        return [i for i, m in enumerate(base) if burst[m] == burst[x]]
    out = []
    for i, m in enumerate(base):
        if burst[m] in ("2", "3"):
            rest = [n for j, n in enumerate(base) if j != i]
            if stage_counts(rest, burst)[:3] in REDHOOD_FRAMES and REDHOOD not in rest:
                out.append(i)
    return out


def candidates(burst: Mapping[str, str] | None = None, ranker: Sequence[Mapping[str, Any]] | None = None
               ) -> list[dict[str, Any]]:
    """규칙으로 만든 후보 목록. 원소 = {id, squad, skeleton, source, base}. 같은 구성(순서 무시)은 한 번만."""
    if burst is None or ranker is None:
        burst, ranker = load_sources()
    bases = base_compositions(ranker)
    out: list[dict[str, Any]] = []
    seen: set[frozenset] = set()

    def add(squad: list[str], source: str, base: int) -> bool:
        k = frozenset(squad)
        if k in seen or len(k) != 5:
            return False
        seen.add(k)
        out.append({"id": f"k{len(out) + 1:03d}", "squad": squad, "skeleton": skeleton(squad, burst),
                    "source": source, "base": base})
        return True

    for bi, b in enumerate(bases):
        add(list(b["squad"]), f"ranker:{b['ranker_index']} (덱 {b['decks']})", bi)
    for x in sorted(burst):  # 니케 이름순 — 결정론
        cap = CAP_REDHOOD if x == REDHOOD else (CAP_FOCUS if x in LAYER_TARGETS else CAP_OTHER)
        order = list(range(len(bases)))
        if x == "에이다":  # 레이어가 미란다와 함께일 때만 붙는다 → 미란다 구성부터
            order.sort(key=lambda bi: ("미란다" not in bases[bi]["squad"], bi))
        made = 0
        for bi in order:
            if made >= cap:
                break
            base = bases[bi]["squad"]
            slots = _swap_slots(base, x, burst)
            if not slots:
                continue
            i = slots[made % len(slots)]  # 자리를 돌아가며
            sq = list(base)
            out_name, sq[i] = sq[i], x
            if add(sq, f"swap:ranker:{bases[bi]['ranker_index']} {out_name}→{x}", bi):
                made += 1
    return out


def static_tags(squad: Sequence[str], est_tertile: str) -> list[str]:
    lm = layer_members(squad)
    tags = (["layer_target"] + [f"layer:{m}" for m in lm]) if lm else ["no_layer_target"]
    if miranda_rule(squad):
        tags.append("miranda_rule")
    tags += [charge_bucket(squad), f"charge_n:{charge_count(squad)}", est_tertile]
    if charger_candidates(squad):
        tags.append("charger_candidate")
    return tags


def est_tertiles(cands: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """후보 id → gauge_fast · gauge_mid · gauge_slow (base 충전 추정의 후보 전체 3등분)."""
    vals = sorted(est_charge_time(c["squad"]) for c in cands)
    lo, hi = vals[len(vals) // 3], vals[2 * len(vals) // 3]
    out = {}
    for c in cands:
        t = est_charge_time(c["squad"])
        out[c["id"]] = "gauge_fast" if t < lo else ("gauge_mid" if t < hi else "gauge_slow")
    return out


# ---------------------------------------------------------------- 2단계: 평가와 선정

def evaluate(cands: Sequence[Mapping[str, Any]], evaluator: Any) -> dict[str, dict[str, Any]]:
    """후보 id → {damage, error}. 기본 레이어(options 없음) + 어댑터 기본 sim(accumulate) + 기본 적."""
    from nikke_opt.evaluator import EvalRequest
    reqs = [EvalRequest(tuple(c["squad"]), boss=common.BOSS, options={}) for c in cands]
    res = evaluator.evaluate(reqs)
    return {c["id"]: {"damage": r.total_damage, "error": r.error} for c, r in zip(cands, res)}


def bands(cands: Sequence[Mapping[str, Any]], damage: Mapping[str, int | None]) -> dict[str, str]:
    """후보 id → "high" · "mid" · "low". 틀마다 딜 내림차순 3등분(앞 ⌈n/3⌉ 상, 다음 ⌈n/3⌉ 중)."""
    out: dict[str, str] = {}
    for sk in sorted({c["skeleton"] for c in cands}):
        ids = sorted((c["id"] for c in cands if c["skeleton"] == sk and damage.get(c["id"]) is not None),
                     key=lambda i: (-damage[i], i))
        third = math.ceil(len(ids) / 3)
        for r, i in enumerate(ids):
            out[i] = "high" if r < third else ("mid" if r < 2 * third else "low")
    return out


class _State:
    def __init__(self) -> None:
        self.sel: list[dict[str, Any]] = []
        self.count: Counter[str] = Counter()
        self.skel: Counter[str] = Counter()
        self.band: Counter[tuple[str, str]] = Counter()
        self.target: Counter[tuple[str, bool]] = Counter()
        self.charge: Counter[str] = Counter()
        self.gauge: Counter[str] = Counter()

    def _upd(self, c: Mapping[str, Any], d: int) -> None:
        for m in c["squad"]:
            self.count[m] += d
            if self.count[m] == 0:
                del self.count[m]
        self.skel[c["skeleton"]] += d
        self.band[(c["skeleton"], c["band"])] += d
        self.target[(c["skeleton"], bool(layer_members(c["squad"])))] += d
        self.charge[charge_bucket(c["squad"])] += d
        self.gauge[c["gauge"]] += d

    def add(self, c: dict[str, Any]) -> None:
        self.sel.append(c)
        self._upd(c, +1)

    def remove(self, c: dict[str, Any]) -> None:
        self.sel.remove(c)
        self._upd(c, -1)

    def keys(self) -> set[frozenset]:
        return {frozenset(c["squad"]) for c in self.sel}


def _score(c: Mapping[str, Any], st: _State) -> float:
    s = 0.0
    for m in c["squad"]:
        n = st.count.get(m, 0)
        if n == 0:
            s -= 1.0
        elif n < MIN_APPEAR:
            s += 2.0
        if m in LAYER_TARGETS and n < MIN_APPEAR:
            s += 3.0
    if miranda_rule(c["squad"]) and not any(miranda_rule(x["squad"]) for x in st.sel):
        s += 3.0
    sk, q = c["skeleton"], QUOTA[c["skeleton"]]
    if st.band[(sk, c["band"])] < math.ceil(q / 2):
        s += 1.5
    side = st.target[(sk, bool(layer_members(c["squad"])))]
    if side < math.ceil(q / 2):
        s += 1.5
    else:  # 그 틀에서 이 쪽(레이어 대상 포함 또는 미포함)이 이미 절반 — 반대쪽을 남긴다
        s -= 4.0
    if c["source"].startswith("ranker"):
        s += 1.0
    s += 1.0 / (1 + st.charge[charge_bucket(c["squad"])])
    s += 1.0 / (1 + st.gauge[c["gauge"]])
    return s


def _best(pool: Sequence[dict[str, Any]], st: _State, ok: Callable[[dict[str, Any]], bool]
          ) -> tuple[dict[str, Any] | None, float]:
    keys = st.keys()
    best, best_s = None, -math.inf
    for c in pool:  # pool은 시드 고정 순서 — 같은 점수면 앞의 것
        if frozenset(c["squad"]) in keys or not ok(c):
            continue
        s = _score(c, st)
        if s > best_s:
            best, best_s = c, s
    return best, best_s


def _swap(pool: Sequence[dict[str, Any]], st: _State, m: str, no_new: Callable[[dict[str, Any]], bool]
          ) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """m이 든 후보 c를 넣고 같은 틀의 조합 x를 뺀다 — 빼도 3회 이상이던 니케가 3회 밑으로 내려가지 않고,
    이미 모자란 니케가 더 줄지 않는 x만."""
    keys = st.keys()
    best, best_s = None, -math.inf
    for c in pool:
        if m not in c["squad"] or frozenset(c["squad"]) in keys or not no_new(c):
            continue
        for x in st.sel:
            if x["skeleton"] != c["skeleton"] or m in x["squad"]:
                continue
            after = Counter(st.count)
            after.subtract(x["squad"])
            after.update(c["squad"])
            if any(after[n] < min(st.count[n], MIN_APPEAR) for n in x["squad"]):  # 3회 밑으로 · 모자란 니케를 더 줄임
                continue
            s = _score(c, st)
            if s > best_s:
                best, best_s = (c, x), s
    return best


def select(cands: Sequence[Mapping[str, Any]], damage: Mapping[str, int | None], seed: int = SEED
           ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """평가된 후보에서 고른 조합(후보 dict 복사 + band · gauge · damage)과 과정 기록."""
    tert = est_tertiles(cands)
    band = bands(cands, damage)
    pool = [{**c, "band": band[c["id"]], "gauge": tert[c["id"]], "damage": damage[c["id"]]}
            for c in cands if c["id"] in band and c["skeleton"] in QUOTA]
    eligible = [c for c in pool if c["band"] != "low"]
    random.Random(seed).shuffle(eligible)
    log: dict[str, Any] = {"steps": [], "repair": [], "candidates": len(cands),
                           "evaluated_ok": len(band), "eligible": len(eligible),
                           "outside_frames": sum(1 for c in cands if c["skeleton"] not in QUOTA)}
    st = _State()
    quota_ok = lambda c: st.skel[c["skeleton"]] < QUOTA[c["skeleton"]]  # noqa: E731
    for t in LAYER_TARGETS:  # 씨앗: 레이어 대상마다 먼저 MIN_APPEAR개
        while st.count.get(t, 0) < MIN_APPEAR:
            c, s = _best(eligible, st, lambda c: t in c["squad"] and quota_ok(c))
            if c is None:
                break
            st.add(c)
            log["steps"].append({"n": len(st.sel), "id": c["id"], "score": round(s, 2), "seed": t})
    while len(st.sel) < TARGET_N:
        c, s = _best(eligible, st, quota_ok)
        if c is None:
            break
        st.add(c)
        log["steps"].append({"n": len(st.sel), "id": c["id"], "score": round(s, 2)})

    def no_new(c: Mapping[str, Any]) -> bool:
        return all(m in st.count for m in c["squad"])

    for _ in range(200):  # 수리
        short = sorted((m for m, n in st.count.items() if n < MIN_APPEAR), key=lambda m: (st.count[m], m))
        if not short:
            break
        m = short[0]
        c = None
        if len(st.sel) < MAX_N:
            c, _s = _best(eligible, st, lambda c: m in c["squad"] and no_new(c)
                          and st.skel[c["skeleton"]] < QUOTA[c["skeleton"]] + 1)
        if c is not None:
            st.add(c)
            log["repair"].append(f"{m} {st.count[m] - 1}→{st.count[m]}회: {c['id']} 추가")
        elif (sw := _swap(eligible, st, m, no_new)) is not None:
            c, x = sw
            st.remove(x)
            st.add(c)
            log["repair"].append(f"{m} {st.count[m] - 1}→{st.count[m]}회: {x['id']} → {c['id']} 교체")
        else:
            drop = [x for x in st.sel if m in x["squad"]]
            for x in drop:
                st.remove(x)
            log["repair"].append(f"{m} 채울 후보 없음: {', '.join(x['id'] for x in drop)} 제외")
        if len(st.sel) < MIN_N:
            # 새 니케 없이 채운다(틀 할당 +1까지)
            while len(st.sel) < MIN_N:
                c, _s = _best(eligible, st, lambda c: no_new(c) and st.skel[c["skeleton"]] < QUOTA[c["skeleton"]] + 1)
                if c is None:
                    break
                st.add(c)
                log["repair"].append(f"{MIN_N}개 미만: {c['id']} 추가")
    log["violations"] = check(st.sel)
    return st.sel, log


def check(sel: Sequence[Mapping[str, Any]]) -> list[str]:
    """README §평가 문제 규칙 점검. 어긴 것의 설명 목록(빈 목록 = 통과)."""
    v = []
    cnt = Counter(m for c in sel for m in c["squad"])
    short = sorted(m for m, n in cnt.items() if n < MIN_APPEAR)
    if short:
        v.append(f"{MIN_APPEAR}개 조합 미만 니케: {', '.join(f'{m}({cnt[m]})' for m in short)}")
    if len({frozenset(c["squad"]) for c in sel}) != len(sel):
        v.append("같은 구성이 두 번 있다")
    for sk in SKELETONS:
        if not any(c["skeleton"] == sk for c in sel):
            v.append(f"틀 {sk} 없음")
    if not any(layer_members(c["squad"]) for c in sel) or all(layer_members(c["squad"]) for c in sel):
        v.append("레이어 대상 포함·미포함 조합이 함께 있지 않다")
    missing = [m for m in LAYER_TARGETS if m not in cnt]
    if missing:
        v.append(f"빠진 레이어 대상: {', '.join(missing)}")
    if not any(miranda_rule(c["squad"]) for c in sel):
        v.append("미란다 + 에이다/미하라 조합 없음")
    if any(c.get("band") == "low" for c in sel):
        v.append("하 구간 조합이 있다")
    if not MIN_N <= len(sel) <= MAX_N:
        v.append(f"조합 수 {len(sel)} (범위 {MIN_N}~{MAX_N})")
    return v


def to_compositions(sel: Sequence[Mapping[str, Any]]) -> list[common.Composition]:
    """id = c01… (틀 순서 → 딜 내림차순)."""
    order = sorted(sel, key=lambda c: (SKELETONS.index(c["skeleton"]), -c["damage"], c["id"]))
    out: list[common.Composition] = []
    for i, c in enumerate(order, 1):
        tags = [f"band:{c['band']}", "ranker" if c["source"].startswith("ranker") else "swap"]
        tags += static_tags(c["squad"], c["gauge"])
        out.append({"id": f"c{i:02d}", "squad": list(c["squad"]), "skeleton": c["skeleton"], "tags": tags,
                    "source": f"{c['source']} [후보 {c['id']}]", "default_damage": int(c["damage"])})
    return out


# ---------------------------------------------------------------- selection.md

def _fmt_eok(x: int | None) -> str:
    return "오류" if x is None else f"{x / 1e8:.1f}"


METHOD_MD = f"""\
## 방법

규칙은 [README §평가 문제](README.md#평가-문제--조합-약-30개), 구현은 [`select_comps.py`](select_comps.py)(docstring에 전체 규칙).
컨트롤 결과를 보기 전에 정한 고정 규칙이다(시드 `{SEED}`).

| 단계 | 내용 |
|---|---|
| 출처 | 실험 2 [`pool.json`](../02_score_distribution/pool.json)(풀 60명 · 버스트 단계) · [`ranker_squads.json`](../02_score_distribution/ranker_squads.json)(S40 랭커 순서 구분 스쿼드 224개 → 구성 66개) |
| 니케 정보 | {CALC_SOURCE}에서 읽기 전용으로 뽑아 `NIKKE_INFO`에 넣었다: 무기 · 차지형(`is_charge`) · 입력 방식 · 풀차지 전용 · 정적 게이지 속도 |
| 후보 ① | 랭커 구성 66개, 배치 순서는 그 구성의 랭커 최빈 순서 |
| 후보 ② | 랭커 구성(덱 수순)의 한 자리를 같은 버스트 단계 풀 니케로 교체(자리 그대로). 레이어 대상 9명은 니케당 {CAP_FOCUS}개, 레드 후드 {CAP_REDHOOD}개(랭커가 쓰지 않아 그 틀은 교체로만 생긴다), 나머지 {CAP_OTHER}개까지. 레드 후드는 B2·B3 자리에 넣어 (1,1,2)+A · (2,1,1)+A 틀. 에이다는 미란다 구성부터 |
| 평가 | 후보 전부를 기본 레이어(운용 없음) + `accumulate`(어댑터 기본 sim) + 기본 적으로 1회씩 |
| 성능 구간 | 버스트 틀마다 딜 순 3등분 → 상 · 중만 남긴다(레드 후드 틀이 전체 분포에서 약해 틀마다 나눔) |
| 할당 | 틀별 {", ".join(f"{k} {v}" for k, v in QUOTA.items())} (합 {TARGET_N}) |
| 씨앗 | 레이어 대상 9명마다 그 니케가 든 후보를 아래 점수로 골라 {MIN_APPEAR}개 조합까지 먼저 넣는다 |
| 탐욕 선정 | 점수 = 등장 1~2회 니케 +2 · 처음 나오는 니케 −1 · 3회 미만 레이어 대상 +3 · 첫 미란다+에이다/미하라 +3 · 틀 안 상·중 균형 +1.5 · 틀 안 레이어 대상 포함/미포함 균형(절반 전 +1.5, 절반 이후 −4) · 랭커 구성 +1 · 차지형 수 구간 다양성 1/(1+n) · base 충전 추정 구간 다양성 1/(1+n). 동점은 시드 고정 순서 |
| 수리 | 등장 {MIN_APPEAR}회 미만 니케 → 새 니케 없는 후보 추가(최대 {MAX_N}개, 틀 할당 +1까지) → 안 되면 같은 틀 조합과 맞바꿈 → 그래도 안 되면 그 니케의 조합 제외. {MIN_N}개 미만이면 새 니케 없는 후보로 채움 |

**태그** — `band:high|mid` · `ranker|swap` · `layer_target`(+`layer:<니케>`) 또는 `no_layer_target` · `miranda_rule`(미란다 +
에이다/미하라 — 그 레이어가 붙는 조건) · 차지형 수 `charge_none|light|mid|heavy`(0 · 1 · 2 · 3명 이상) + `charge_n:<k>` ·
base 충전 추정 3등분 `gauge_fast|mid|slow` · `charger_candidate`(톡톡이가 되는 차지형이 있음 = 버충 담당 후보).

**한계** — base 충전 추정은 무기 사격만의 정적 값이다(스킬 충전 · 풀차지 배율 · 카메라 제외). 실제 base 충전 시간은 시뮬
결과인데 평가기 결과에 나오지 않아, 후보 사이 상대 순위로만 쓴다. 앨리스의 레이어(톡톡이)는 차지속도 옵션 8.18% 이상일 때만
붙는데, 기본 스펙에서 붙는 것을 원본(Python `23164e4`)으로 확인했다(`spec.char_defaults.applied`, 미란다 + 에이다 · 미하라도 붙음). 레이어가 붙는 니케 중 아인 · 밀크 : 블루밍
바니 · 길티 : 마이티 바니 · 신 : 스위프트 바니 · 라푼젤 : 퓨어 그레이스는 풀에 없어 넣지 않았다. 교체 후보는 랭커 구성에서 한
명만 바꾼 것이라 랭커 구성 근처에 몰려 있다(실험 2 §1: 무작위 스쿼드는 랭커 구성보다 훨씬 약하다).
"""


def candidates_md(cands: Sequence[Mapping[str, Any]]) -> str:
    by = Counter((c["skeleton"], c["source"].split(":")[0]) for c in cands)
    sks = sorted({c["skeleton"] for c in cands}, key=lambda s: (s not in SKELETONS, SKELETONS.index(s)
                                                                 if s in SKELETONS else 0, s))
    rows = "\n".join(f"| {sk} | {by[(sk, 'ranker')]} | {by[(sk, 'swap')]} |" for sk in sks)
    return (f"## 후보\n\n후보 {len(cands)}개 (랭커 구성 {sum(1 for c in cands if c['source'].startswith('ranker'))} · "
            f"한 명 교체 {sum(1 for c in cands if c['source'].startswith('swap'))}). "
            f"할당 밖 틀(`{'`·`'.join(s for s in sks if s not in QUOTA) or '없음'}`)은 선정에서 뺀다.\n\n"
            f"| 틀 | 랭커 | 교체 |\n|---|---|---|\n{rows}\n")


def selection_md(cands: Sequence[Mapping[str, Any]], comps: Sequence[Mapping[str, Any]] | None = None,
                 log: Mapping[str, Any] | None = None, evals: Mapping[str, Mapping[str, Any]] | None = None,
                 meta: Mapping[str, Any] | None = None) -> str:
    out = ["# 실험 6 조합 선정 (W3)\n",
           "`select_comps.py`가 쓴다 — 손으로 고치지 않는다. 형식은 `common.Composition`, 목록은 "
           "[`compositions.json`](compositions.json).\n", METHOD_MD, candidates_md(cands)]
    if comps is None:
        out.append("## 결과\n\n`pick` 미실행 — 평가기가 붙은 세션에서 "
                   "`source .cache/evaluators.env && python experiments/06_control_menu/select_comps.py pick`.\n")
        return "\n".join(out)
    assert log is not None and evals is not None and meta is not None
    errs = {i: e["error"] for i, e in evals.items() if e["error"] is not None or e["damage"] is None}
    out.append(f"## 평가\n\n| | |\n|---|---|\n| 평가기 | `{json.dumps(meta.get('evaluator'), ensure_ascii=False)}` |\n"
               f"| 요청 | {len(evals)}개 (기본 레이어 · accumulate · 기본 적) |\n"
               f"| **실제 시뮬** | **{meta.get('sim_count')}회** (캐시 적중 {meta.get('cache_hits')}) |\n"
               f"| 오류 | {len(errs)}개 |\n| 상·중 후보 | {log['eligible']}개 |\n")
    if errs:
        out.append("| 오류 후보 | 구성 | 오류 |\n|---|---|---|\n" + "\n".join(
            f"| {i} | {' · '.join(next(c['squad'] for c in cands if c['id'] == i))} | "
            f"{json.dumps(e, ensure_ascii=False)[:120]} |" for i, e in sorted(errs.items())) + "\n")
    dmg = {i: e["damage"] for i, e in evals.items()}
    band = bands(cands, dmg)
    rows = []
    for sk in sorted({c["skeleton"] for c in cands if c["id"] in band}):
        ds = sorted((dmg[c["id"]] for c in cands if c["skeleton"] == sk and c["id"] in band), reverse=True)
        hi = [dmg[c["id"]] for c in cands if c["skeleton"] == sk and band.get(c["id"]) == "high"]
        md = [dmg[c["id"]] for c in cands if c["skeleton"] == sk and band.get(c["id"]) == "mid"]
        rows.append(f"| {sk} | {len(ds)} | {_fmt_eok(ds[0])} | {_fmt_eok(min(hi))} | "
                    f"{_fmt_eok(min(md)) if md else '-'} | {_fmt_eok(ds[-1])} |")
    out.append("### 성능 구간 (틀별, 억)\n\n| 틀 | 후보 | 최대 | 상 하한 | 중 하한 | 최소 |\n|---|---|---|---|---|---|\n"
               + "\n".join(rows) + "\n")
    out.append("## 선정 과정\n\n씨앗 · 탐욕 단계(순번:후보(점수), 씨앗은 [대상]): " + " · ".join(
        f"{s['n']}:{s['id']}({s['score']})" + (f"[{s['seed']}]" if s.get("seed") else "") for s in log["steps"]) + "\n")
    out.append("수리: " + ("; ".join(log["repair"]) if log["repair"] else "없음") + "\n")
    out.append("규칙 점검: " + ("**통과**" if not log["violations"] else "**어김** — " + "; ".join(log["violations"])) + "\n")
    out.append("## 조합\n\n| id | 틀 | 배치 순서 | 기본 레이어 딜(억) | 구간 | 차지형 | 충전 추정(초) | 태그 | 출처 |\n"
               "|---|---|---|---|---|---|---|---|---|\n" + "\n".join(
                   f"| {c['id']} | {c['skeleton']} | {' · '.join(c['squad'])} | {_fmt_eok(c['default_damage'])} | "
                   f"{c['tags'][0].split(':')[1]} | {charge_count(c['squad'])} | {est_charge_time(c['squad']):.2f} | "
                   f"{' '.join(t for t in c['tags'][1:] if not t.startswith(('charge_n:', 'layer:')))} | {c['source']} |"
                   for c in comps) + "\n")
    cnt = Counter(m for c in comps for m in c["squad"])
    out.append("## 니케별 등장 조합 수\n\n| 니케 | 단계 | 조합 수 | 레이어 대상 | 차지형 | 조합 |\n|---|---|---|---|---|---|\n"
               + "\n".join(f"| {m} | {_burst_of(m)} | {n} | {'○' if m in LAYER_TARGETS else ''} | "
                           f"{'○' if NIKKE_INFO[m][1] else ''} | "
                           f"{' '.join(c['id'] for c in comps if m in c['squad'])} |"
                           for m, n in sorted(cnt.items(), key=lambda x: (-x[1], x[0]))) + "\n")
    tg = Counter(t for c in comps for t in c["tags"] if not t.startswith(("layer:", "charge_n:")))
    out.append("## 태그 분포\n\n" + " · ".join(f"`{t}` {n}" for t, n in sorted(tg.items())) + "\n")
    return "\n".join(out)


_BURST: dict[str, str] = {}


def _burst_of(m: str) -> str:
    if not _BURST:
        _BURST.update(load_sources()[0])
    return _BURST.get(m, "?")


# ---------------------------------------------------------------- 실행

def run_pick(evaluator: Any, *, out_json: Path = common.COMPOSITIONS, out_md: Path = SELECTION_MD,
             burst: Mapping[str, str] | None = None, ranker: Sequence[Mapping[str, Any]] | None = None
             ) -> tuple[list[common.Composition], dict[str, Any]]:
    cands = candidates(burst, ranker)
    evals = evaluate(cands, evaluator)
    sel, log = select(cands, {i: e["damage"] for i, e in evals.items()})
    comps = to_compositions(sel)
    meta = {"evaluator": getattr(evaluator, "version", None), "sim_count": evaluator.sim_count,
            "cache_hits": getattr(evaluator, "cache_hits", None)}
    log = {**log, **meta}
    out_json.write_text(json.dumps(comps, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    out_md.write_text(selection_md(cands, comps, log, evals, meta), encoding="utf-8")
    return comps, log


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates", help="규칙으로 후보 목록(평가기 불필요). selection.md에 방법·후보 요약")
    c.add_argument("--out", type=Path, help="후보 목록 JSON 경로")
    c.add_argument("--no-md", action="store_true", help="selection.md를 쓰지 않는다")
    p = sub.add_parser("pick", help="후보 평가 → compositions.json · selection.md")
    p.add_argument("--jobs", type=int)
    p.add_argument("--budget", type=int, default=1000, help="시뮬 예산(초과하면 멈춘다)")
    p.add_argument("--out", type=Path, default=common.COMPOSITIONS)
    p.add_argument("--md", type=Path, default=SELECTION_MD)
    e = sub.add_parser("extract", help="nikke-calc 데이터에서 NIKKE_INFO를 다시 뽑아 이 파일의 값과 비교")
    e.add_argument("calc_dir", type=Path, help="nikke-calc 체크아웃 (23164e4)")
    args = ap.parse_args(argv)

    if args.cmd == "extract":
        info = extract_info(args.calc_dir, list(load_sources()[0]))
        diff = sorted(k for k in set(info) | set(NIKKE_INFO) if info.get(k) != NIKKE_INFO.get(k))
        for k, v in info.items():
            print(f"    {k!r}: {v!r},")
        print(f"# 내장 NIKKE_INFO와 다른 니케: {diff or '없음'}", file=sys.stderr)
        return 1 if diff else 0

    if args.cmd == "candidates":
        cands = candidates()
        if args.out:
            args.out.write_text(json.dumps(cands, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if not args.no_md:
            SELECTION_MD.write_text(selection_md(cands), encoding="utf-8")
        sk = Counter(x["skeleton"] for x in cands)
        print(f"후보 {len(cands)}개 — " + " · ".join(f"{k} {v}" for k, v in sorted(sk.items())))
        return 0
    from nikke_opt.evaluator import make_evaluator
    with make_evaluator(jobs=args.jobs, budget=args.budget) as ev:
        comps, log = run_pick(ev, out_json=args.out, out_md=args.md)
    print(f"조합 {len(comps)}개 · 시뮬 {log['sim_count']}회 (캐시 {log['cache_hits']}) · "
          f"규칙 점검 {'통과' if not log['violations'] else log['violations']}")
    return 0 if not log["violations"] else 1


if __name__ == "__main__":
    sys.exit(main())
