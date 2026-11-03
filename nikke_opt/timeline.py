"""덱 하나의 컨트롤 타임라인 — 평가기 `sim.trace`(nikke-calc-rs만)를 화면용 짧은 모양으로 줄인다.

후처리가 고른 최종 선택지로 **한 번 더** 시뮬해 「언제 무슨 키를 누르나」를 받는다(시뮬 1회 · 탐색 값은 그대로).

    from nikke_opt.timeline import traced, compact
    req = traced(EvalRequest(squad, boss, options))   # options.sim.trace = true
    r = ev.evaluate([req])[0]
    tl = compact(r.raw["trace"], squad, r.raw["duration"])

평가기 `trace`(nikke-calc-rs `crates/runner/src/execute.rs` `trace_json`)의 네 줄을 그대로 옮긴다. 정의를 여기서 다시 쓰지 않는다.

| 칸 | 모양 | 뜻 · 키 |
|---|---|---|
| `fb` | `[[t0, t1]]` | 풀버스트 구간 |
| `b` | `[[t, 단계, 자리, 재진입]]` | 버스트 사용(1~3단계). 자리 = 배치 순서 0~4(스쿼드 밖이면 -1), 재진입 1 = 같은 단계 다시 |
| `c` | `[[t0, t1, 자리, 입력, 연 것]]` | 조작 구간. 입력 `tap`(좌클릭 톡톡이) · `hold`(좌클릭 홀드) · `cover`(shift 엄폐) · `all`(space 전체 엄폐) |
| `cam` | `[[t, 자리]]` | 그 시각부터의 카메라(바뀔 때만 한 줄, 키 Z · X · C · V · B = 자리 0~4). -1 = 아무도 안 봄 |

시각은 초, 소수 셋째 자리(1프레임 = 1/60초가 남게)로 줄인다.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping, Sequence

from nikke_opt.evaluator import EvalRequest

VERSION = 1
NDIGITS = 3
_INPUT = {("click", "tap"): "tap", ("click", "hold"): "hold", ("cover", "cover"): "cover", ("cover_all", "cover"): "all"}


def traced(req: EvalRequest) -> EvalRequest:
    """같은 요청에 `sim.trace: true`만 더한다(평가 결과 · 총딜은 그대로, 결과에 `trace`가 붙는다)."""
    sim = dict(req.options.get("sim") or {})
    sim["trace"] = True
    return replace(req, options={**req.options, "sim": sim})


def _t(x: float) -> float:
    return round(float(x), NDIGITS)


def compact(trace: Mapping[str, Any], squad: Sequence[str], duration: float) -> dict[str, Any]:
    """평가기 `trace` → 화면용 모양(모듈 설명의 표). 니케는 배치 순서 자리 번호로 적는다."""
    slot = {n: i for i, n in enumerate(squad)}

    def at(n: Any) -> int:
        return slot.get(n, -1) if isinstance(n, str) else -1

    cam = []
    for row in trace.get("camera") or []:
        names = row.get("names") or []
        cam.append([_t(row["t"]), at(names[0]) if names else -1])
    ctrl = []
    for c in trace.get("controls") or []:
        kind = _INPUT.get((c.get("input"), c.get("mode")), f"{c.get('input')}:{c.get('mode')}")
        ctrl.append([_t(c["t0"]), _t(c["t1"]), at(c.get("caster")), kind, c.get("producer") or ""])
    return {
        "v": VERSION,
        "squad": list(squad),
        "dur": float(duration),
        "fb": [[_t(w["t0"]), _t(w["t1"])] for w in trace.get("full_bursts") or []],
        "b": [[_t(b["t"]), int(b["stage"]), at(b.get("caster")), 1 if b.get("reenter") else 0]
              for b in trace.get("bursts") or []],
        "c": ctrl,
        "cam": cam,
    }
