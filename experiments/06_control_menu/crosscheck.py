"""실험 6 W1 — Rust nikke-sim ↔ Python 원본(nikke-calc 23164e4) 대조 → crosscheck.md. (골격: 관리자. 구현: W1)

같은 요청을 두 평가기(make_evaluator("rust") · make_evaluator("python"))로 돌려 총딜 상대 차이를 표로 남긴다.
요청은 기본 적 · 기본 sim(expected + accumulate) 위에 축 하나씩을 바꾼 20개다(`REQUESTS`).

    source .cache/evaluators.env && python experiments/06_control_menu/crosscheck.py          # 실행 → crosscheck.md
    python experiments/06_control_menu/crosscheck.py --dry-run                                # 요청 줄만 출력
    source .cache/evaluators.env && python experiments/06_control_menu/crosscheck.py --only A0,A9 --out /tmp/x.md

차이 = (Rust − Python) / Python. |차이| ≥ `--threshold`(기본 1%, 임시)인 요청과 그 축을 「표시」 절에 모은다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent)]

from nikke_opt.evaluator import EvalRequest, EvalResult, make_evaluator  # noqa: E402

OUT = HERE / "crosscheck.md"
THRESHOLD = 0.01  # 임시 기준 (SESSIONS.md W1)

# 조합 4개 — nikke-calc baseline/ 의 하네스 스쿼드에서 골랐다(배치 순서 그대로).
# 무기·버스트 단계는 nikke-calc data/parsed_nikke.json(23164e4)을 읽어 확인했다.
SQUADS: dict[str, list[str]] = {
    # S36_아인루주: 레이어 대상 3명(미란다 전담 패턴 · 에이다/아인 홀드). 차지형 4명(타키나·아인·루주 SR, 에이다 RL)
    "A": ["미란다", "타키나", "아인", "루주", "에이다"],
    # S39_레이븐레드후드: 레드 후드 틀. 프리카 레이어(민트와 함께면 첫 사이클만). 레이븐은 풀차지 전용 RL
    "B": ["리타", "민트", "레이븐", "프리카", "레드 후드"],
    # S40_브리드라피: 차지형은 아니스 : 스타(DOWN_Charge)뿐. MG 둘(라피 : 레드 후드 · 미하라 : 본딩 체인)
    "C": ["브리드 : 사일런트 트랙", "라피 : 레드 후드", "아니스 : 스타", "미하라 : 본딩 체인", "프리바티"],
    # S40_앨리스모더니아: 앨리스(SR, 육성 가드 레이어). 3번 자리 레이는 MG라 기본 카메라가 게이지에 무영향
    "D": ["리타", "그레이브", "레이", "앨리스", "모더니아"],
}


def _ctl(name: str, control: Mapping[str, Any]) -> dict[str, Any]:
    return {"chars": {name: {"control": dict(control)}}}


# 요청 하나 = {id, squad, axis, label, options}. axis는 대조 보고에서 묶는 이름이다.
# options는 EvalRequest.options — sim은 어댑터 기본(expected + accumulate) 위에 얹힌다.
REQUESTS: list[dict[str, Any]] = [
    # 기준: 운용 없음(평가기 기본 레이어) + accumulate + solo
    {"id": "A0", "squad": "A", "axis": "base", "label": "기본 레이어 · accumulate", "options": {}},
    {"id": "B0", "squad": "B", "axis": "base", "label": "기본 레이어 · accumulate", "options": {}},
    {"id": "C0", "squad": "C", "axis": "base", "label": "기본 레이어 · accumulate", "options": {}},
    {"id": "D0", "squad": "D", "axis": "base", "label": "기본 레이어 · accumulate", "options": {}},
    # 게이지 방식: fixed와 비교해 accumulate 자체의 차이를 가른다
    {"id": "A1", "squad": "A", "axis": "gauge", "label": "기본 레이어 · fixed",
     "options": {"sim": {"burst_gauge_mode": "fixed"}}},
    {"id": "C1", "squad": "C", "axis": "gauge", "label": "기본 레이어 · fixed",
     "options": {"sim": {"burst_gauge_mode": "fixed"}}},
    # 완전 오토: 레이어까지 끈다
    {"id": "A2", "squad": "A", "axis": "auto", "label": "operation.auto: true",
     "options": {"operation": {"auto": True}}},
    {"id": "B2", "squad": "B", "axis": "auto", "label": "operation.auto: true",
     "options": {"operation": {"auto": True}}},
    # 조작 모드: solo(기본)와 warn(조율 없음 — 겹쳐도 둘 다 집행)을 비교. A는 아인·에이다 홀드가 겹칠 수 있다
    {"id": "A3", "squad": "A", "axis": "solo", "label": "control_mode: warn (solo 조율 끔)",
     "options": {"operation": {"control_mode": "warn"}}},
    # 좌클릭
    {"id": "B4", "squad": "B", "axis": "click", "label": "레드 후드 상시 톡톡이 3.6",
     "options": _ctl("레드 후드", {"click": [{"window": "always", "mode": "tap", "rate": 3.6}]})},
    {"id": "B5", "squad": "B", "axis": "click", "label": "프리카 본인 풀버스트 홀드",
     "options": _ctl("프리카", {"click": [{"window": "own_full_burst", "mode": "hold", "lead": 0.5}]})},
    # 장전컨
    {"id": "D6", "squad": "D", "axis": "reload", "label": "모더니아 장전컨 A(before_fb_end 0.3)",
     "options": _ctl("모더니아", {"reload": {"policy": "before_fb_end", "lead": 0.3}})},
    {"id": "C6", "squad": "C", "axis": "reload", "label": "라피 : 레드 후드 장전컨 C(if_dry)",
     "options": _ctl("라피 : 레드 후드", {"reload": {"policy": "finish_by_fb_end", "margin": 0.1, "if_dry": True}})},
    # 버스트 엄폐컨 · 탄충 취소
    {"id": "C7", "squad": "C", "axis": "cover", "label": "미하라 : 본딩 체인 버스트 엄폐컨",
     "options": _ctl("미하라 : 본딩 체인", {"cover": {"policy": "own_full_burst"}})},
    {"id": "D8", "squad": "D", "axis": "cancel", "label": "모더니아 · 레이 탄충 취소",
     "options": {"chars": {"모더니아": {"control": {"reload": {"cancel_on_full": True}}},
                           "레이": {"control": {"reload": {"cancel_on_full": True}}}}}},
    # 버스트 버튼
    {"id": "B9", "squad": "B", "axis": "burst_delay", "label": "레드 후드 버스트 딜레이 2.0초",
     "options": _ctl("레드 후드", {"burst": {"delay": 2.0}})},
    {"id": "A9", "squad": "A", "axis": "burst_pattern", "label": "미란다 패턴 끔(전담 해제)",
     "options": _ctl("미란다", {"burst": {"pattern": False}})},
    {"id": "A10", "squad": "A", "axis": "burst_wait", "label": "루주 wait_own_cooldown 3.0",
     "options": _ctl("루주", {"burst": {"wait_own_cooldown": 3.0}})},
    # 택틱 · 카메라
    {"id": "A11", "squad": "A", "axis": "tactic", "label": "버충 택틱(담당 루주)",
     "options": {"operation": {"tactics": [{"name": "버충", "target": "루주"}]}}},
    {"id": "D12", "squad": "D", "axis": "camera", "label": "카메라 앨리스(기본: 3번 레이)",
     "options": {"operation": {"camera": "앨리스"}}},
]

# 크게 다를 때 먼저 볼 곳(사전 후보). 실행 뒤 결과를 보고 crosscheck.md에 판단을 덧붙인다.
AXIS_HINTS: dict[str, str] = {
    "base": "레이어 규칙 전개(char_defaults `_rules`) · accumulate 게이지 산식 · 고유 버스트 충전 효과",
    "gauge": "fixed 사이클 표(burst_gauge.json) 읽기 · first_burst",
    "auto": "auto=true일 때 레이어·패턴 모드 저지 우선 타격 끄기",
    "solo": "조율(_arbitrate_control) 등급·선점 · 카메라 추종",
    "click": "차지 래치 시점 · tap 발사 간격(rate·release) · hold lead",
    "reload": "next_fb_start/fb_end 앵커 · reload_total(minus) · if_dry 판정",
    "cover": "엄폐 진입 시 재장전 · duration_bullets 버프 소모",
    "cancel": "탄환 충전 instant 핸들러의 재장전 취소",
    "burst_delay": "버튼 불 들어온 시각 = max(단계 열림, 쿨 해제) 기준",
    "burst_pattern": "pattern false 처리 · 같은 단계 후보 순서(등급)",
    "burst_wait": "wait_own_cooldown 대기 창",
    "tactic": "버충 pick · burst_charge 창 판정 · 카메라 고정",
    "camera": "풀차지 게이지 배율(카메라 초점) · single 유도",
}


def build_requests(only: Sequence[str] | None = None) -> list[tuple[dict[str, Any], EvalRequest]]:
    """(요청 정의, EvalRequest) 목록. `only`가 있으면 그 id만, 정의 순서대로."""
    ids = {r["id"] for r in REQUESTS}
    if only:
        unknown = sorted(set(only) - ids)
        if unknown:
            raise ValueError(f"모르는 요청 id: {unknown}")
    out = []
    for r in REQUESTS:
        if only and r["id"] not in only:
            continue
        out.append((r, EvalRequest(tuple(SQUADS[r["squad"]]), options=r["options"])))
    return out


def rel_diff(rust: int | None, py: int | None) -> float | None:
    if rust is None or py is None or py == 0:
        return None
    return (rust - py) / py


def _members(res: EvalResult) -> dict[str, int]:
    return {m["name"]: m["damage"] for m in res.raw.get("members") or [] if "name" in m}


def compare(spec: Mapping[str, Any], rust: EvalResult, py: EvalResult, threshold: float = THRESHOLD) -> dict[str, Any]:
    """요청 하나의 대조 행. 니케별 딜 차이 중 가장 큰 것도 남긴다(원인 니케 추정용)."""
    d = rel_diff(rust.total_damage, py.total_damage)
    rm, pm = _members(rust), _members(py)
    worst_name, worst = None, None
    for name in pm:
        md = rel_diff(rm.get(name), pm[name])
        if md is not None and (worst is None or abs(md) > abs(worst)):
            worst_name, worst = name, md
    return {
        "id": spec["id"], "squad": spec["squad"], "axis": spec["axis"], "label": spec["label"],
        "rust": rust.total_damage, "python": py.total_damage, "diff": d,
        "worst_member": worst_name, "worst_member_diff": worst,
        "rust_error": rust.error, "python_error": py.error,
        "rust_control": (rust.raw.get("control_detail") or {}).get("preempted"),
        "python_control": (py.raw.get("control_detail") or {}).get("preempted"),
        "flag": d is None or abs(d) >= threshold,
    }


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:+.3f}%"


def _num(x: int | None) -> str:
    return "오류" if x is None else f"{x:,}"


def render_md(rows: Sequence[Mapping[str, Any]], meta: Mapping[str, Any], threshold: float = THRESHOLD) -> str:
    """crosscheck.md 본문. rows가 비면 요청 목록만 쓴다(미실행)."""
    lines = [
        "# 실험 6 W1 — Rust ↔ Python 원본 대조",
        "",
        "`crosscheck.py`가 만든다. 차이 = (Rust − Python) / Python, 총딜 기준. "
        f"|차이| ≥ {threshold * 100:g}%(임시)는 **표시**.",
        "",
        "## 조건",
        "",
        "- 적: 평가기 기본(허수아비, 방어력 31784) · `sim`: 어댑터 기본(`expected: true` · `burst_gauge_mode: accumulate`)"
        " · `operation.control_mode`: 평가기 기본 `solo` · 육성: 기본 스펙",
        f"- Rust: {json.dumps(meta.get('rust'), ensure_ascii=False)}",
        f"- Python: {json.dumps(meta.get('python'), ensure_ascii=False)}",
        f"- 실제 시뮬 횟수: Rust {meta.get('rust_sims', '—')} · Python {meta.get('python_sims', '—')}"
        f" (캐시 적중 Rust {meta.get('rust_hits', '—')} · Python {meta.get('python_hits', '—')})",
        f"- 실행 시각: {meta.get('when', '—')} · 걸린 시간: Rust {meta.get('rust_sec', '—')}초 · Python {meta.get('python_sec', '—')}초",
        "",
        "## 조합",
        "",
        "| 키 | 배치 순서 |",
        "|---|---|",
    ]
    lines += [f"| {k} | {' · '.join(v)} |" for k, v in SQUADS.items()]
    lines += ["", "## 요청별 차이", ""]
    by_id = {r["id"]: r for r in rows}
    lines += ["| id | 조합 | 축 | 바꾼 것 | Rust 총딜 | Python 총딜 | 차이 | 차이가 가장 큰 니케 | 표시 |",
              "|---|---|---|---|---:|---:|---:|---|---|"]
    for spec in REQUESTS:
        r = by_id.get(spec["id"])
        if r is None:
            lines.append(f"| {spec['id']} | {spec['squad']} | {spec['axis']} | {spec['label']} | 미실행 | 미실행 | — | — | |")
            continue
        worst = f"{r['worst_member']} {_pct(r['worst_member_diff'])}" if r["worst_member"] else "—"
        lines.append(f"| {r['id']} | {r['squad']} | {r['axis']} | {r['label']} | {_num(r['rust'])} | "
                     f"{_num(r['python'])} | {_pct(r['diff'])} | {worst} | {'**표시**' if r['flag'] else ''} |")
    flagged = [r for r in rows if r["flag"]]
    lines += ["", f"## 표시 — {threshold * 100:g}% 이상 차이 나는 축", ""]
    if not rows:
        lines.append("미실행.")
    elif not flagged:
        lines.append(f"없음 — 모든 요청이 {threshold * 100:g}% 안이다.")
    else:
        lines += ["| id | 축 | 차이 | 원인 후보(사전) | 오류 |", "|---|---|---:|---|---|"]
        for r in flagged:
            err = "; ".join(f"{k}: {json.dumps(v, ensure_ascii=False)[:120]}"
                            for k, v in (("Rust", r["rust_error"]), ("Python", r["python_error"])) if v)
            lines.append(f"| {r['id']} | {r['axis']} | {_pct(r['diff'])} | {AXIS_HINTS.get(r['axis'], '')} | {err} |")
    lines += ["", "## 판단", "", meta.get("judgement") or "실행 뒤 쓴다.", ""]
    return "\n".join(lines)


def run(only: Sequence[str] | None = None, threshold: float = THRESHOLD, raw_out: Path | None = None
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pairs = build_requests(only)
    reqs = [q for _, q in pairs]
    meta: dict[str, Any] = {"when": time.strftime("%Y-%m-%d %H:%M")}
    results: dict[str, list[EvalResult]] = {}
    for kind in ("rust", "python"):
        ev = make_evaluator(kind)
        try:
            t0 = time.monotonic()
            results[kind] = ev.evaluate(reqs)
            meta[f"{kind}_sec"] = round(time.monotonic() - t0, 1)
            meta[kind] = ev.version
            meta[f"{kind}_sims"] = ev.sim_count
            meta[f"{kind}_hits"] = ev.cache_hits
        finally:
            ev.close()
    rows = [compare(spec, rs, ps, threshold) for (spec, _), rs, ps in zip(pairs, results["rust"], results["python"])]
    if raw_out:
        with open(raw_out, "w", encoding="utf-8") as f:
            for (spec, q), rs, ps in zip(pairs, results["rust"], results["python"]):
                f.write(json.dumps({"id": spec["id"], "request": q.to_line(), "rust": rs.raw, "python": ps.raw},
                                   ensure_ascii=False) + "\n")
    return rows, meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="평가하지 않고 요청 줄(JSON Lines)만 출력")
    ap.add_argument("--only", help="쉼표로 나눈 요청 id만")
    ap.add_argument("--out", type=Path, default=OUT, help="표를 쓸 파일 (기본 crosscheck.md)")
    ap.add_argument("--raw", type=Path, help="두 평가기의 결과 원문을 JSON Lines로 남길 곳")
    ap.add_argument("--threshold", type=float, default=THRESHOLD)
    a = ap.parse_args(argv)
    only = [s.strip() for s in a.only.split(",")] if a.only else None
    if a.dry_run:
        for spec, q in build_requests(only):
            print(json.dumps({"id": spec["id"], **q.to_line()}, ensure_ascii=False))
        return 0
    rows, meta = run(only, a.threshold, a.raw)
    a.out.write_text(render_md(rows, meta, a.threshold), encoding="utf-8")
    for r in rows:
        print(f"{r['id']:>4} {r['axis']:<13} {_pct(r['diff']):>10} {'표시' if r['flag'] else ''}")
    print(f"→ {a.out} (시뮬 Rust {meta['rust_sims']} · Python {meta['python_sims']})")
    return 1 if any(r["rust_error"] or r["python_error"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
