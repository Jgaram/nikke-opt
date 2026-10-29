"""실험 6 W2 — 니케별 컨트롤 선택지 생성. (골격: 관리자. 구현: W2)

평가기 어휘는 nikke-calc `docs/CONTROL.md` §설정 스키마 · `docs/SIM-JSON.md` §요청.
평가기 코드는 import하지 않는다. 니케 정보는 평가기 데이터(JSON)에서 뽑은 `nikke_info.json`만 읽는다
(추출: `--extract`, 출처 커밋은 그 파일의 `_source`와 menu.md). 축 · 값 격자 · 조립 규칙의 근거는 menu.md.

    python experiments/06_control_menu/menu.py --table              # 풀 60명의 선택지 표 (menu.md용)
    python experiments/06_control_menu/menu.py --check              # 조립 오류 검사 (평가기 필요)
    python experiments/06_control_menu/menu.py --check --sample 10  # 소수만 (고르게)
    python experiments/06_control_menu/menu.py --check --labels 에이다:cover:on 에이다:combo
    python experiments/06_control_menu/menu.py --extract /home/user/jgaram/nikke-calc   # nikke_info.json 다시 뽑기
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent.parent)]
from common import REPO_ROOT, START_OPTIONS, Variant, deep_merge  # noqa: E402

Key = tuple["str | None", str]  # (니케 또는 None, 축)

INFO_PATH = HERE / "nikke_info.json"
POOL_PATH = REPO_ROOT / "experiments" / "02_score_distribution" / "pool.json"
CALC_COMMIT = "23164e4a88fe46af609cc99b0de38a98313a5f4d"  # Rust 포팅 기준 원본 (README §조건)

# ── 값 격자 (근거: menu.md §값 격자) ──────────────────────────────────────────
TAP = {"window": "always", "mode": "tap", "rate": 3.6, "release": 0.03}  # 레이어 숙련 기준(앨리스·밀크)
HOLD_OWN_FB = {"window": "own_full_burst", "mode": "hold", "lead": 0.5}  # 레이어 기본(에이다·아인)
HOLD_JUDGE = {"window": "after_own_fb", "mode": "hold_judge", "lead": 0.1}  # 권장값
RELOAD_GRID: tuple[tuple[str, dict[str, Any]], ...] = (
    ("A0.3", {"policy": "before_fb_end", "lead": 0.3}),
    ("B0.1", {"policy": "into_fb", "margin": 0.1}),
    ("B0.5", {"policy": "into_fb", "margin": 0.5}),
    ("C0.1", {"policy": "finish_by_fb_end", "margin": 0.1}),
    ("C0.5", {"policy": "finish_by_fb_end", "margin": 0.5}),
    ("C0.1_dry", {"policy": "finish_by_fb_end", "margin": 0.1, "if_dry": True}),
)
BURST_DELAYS = (1.0, 2.0)
WAIT_OWN_COOLDOWN = 2.0
TACTIC = "버충"
# 풀차지가 곧 버충이라 톡톡이 담당에서 빼는 니케 (CONTROL.md §버충 컨트롤 §담당 선택). 추출 때 nikke_info.json에 싣는다
GAUGE_BY_FULL_CHARGE = ("헬름", "맥스웰 : 오디너리 미케닉", "스노우 화이트 : 헤비암즈")

# --check 스쿼드: 대상 니케 + 이 목록에서 대상이 아닌 앞 4명 (B1·B2·B3를 갖추고, 레이어 규칙이 걸리게 미란다를 넣었다)
CHECK_FILLERS = ("미란다", "크라운", "헬름", "리타", "라피 : 레드 후드")


class MenuConflict(ValueError):
    """평가기가 조립 시점에 거절할 선택지 조합. 시뮬하지 않고 건너뛰면 된다(menu.md §조립 규칙)."""


_INFO: dict[str, Any] | None = None


def info() -> dict[str, Any]:
    global _INFO
    if _INFO is None:
        _INFO = json.loads(INFO_PATH.read_text(encoding="utf-8"))
    return _INFO


def nikke(name: str) -> dict[str, Any]:
    try:
        return info()["nikke"][name]
    except KeyError:
        raise KeyError(f"nikke_info.json에 없는 니케: {name!r} (정식 명칭인지 확인, 필요하면 --extract)") from None


def _v(who: str | None, axis: str, name: str, patch: dict[str, Any]) -> Variant:
    label = f"{who if who is not None else 'squad'}:{axis}:{name}"
    return Variant(nikke=who, axis=axis, label=label, patch=patch)


def _ctrl(who: str, control: dict[str, Any]) -> dict[str, Any]:
    return {"chars": {who: {"control": control}}}


def _tappable(n: Mapping[str, Any]) -> bool:
    return n["charge"] and n["input"] == "UP" and not n["full_charge_only"]


def nikke_variants(who: str) -> dict[str, list[Variant]]:
    """니케 단위 축의 선택지. 스쿼드와 무관하다(같은 니케 → 같은 label · patch)."""
    n = nikke(who)
    layer = n["layer"]
    out: dict[str, list[Variant]] = {}

    # 좌클릭 — 차지형 UP만(DOWN_Charge는 click이 무력하다). 풀차지 전용은 톡톡이 불가, 홀드는 된다
    if n["charge"] and n["input"] == "UP":
        vs = []
        if "click" in layer:
            vs.append(_v(who, "click", "auto", _ctrl(who, {"click": False})))
        if not n["full_charge_only"]:
            vs.append(_v(who, "click", "tap", _ctrl(who, {"click": [dict(TAP)]})))
        if n["burst_stage"]:
            vs.append(_v(who, "click", "hold_own_fb", _ctrl(who, {"click": [dict(HOLD_OWN_FB)]})))
            if not n["full_charge_only"]:
                vs.append(_v(who, "click", "hold_own_fb+tap",
                             _ctrl(who, {"click": [dict(HOLD_OWN_FB), dict(TAP)]})))
            if n["charge_hold"]:
                vs.append(_v(who, "click", "hold_judge", _ctrl(who, {"click": [dict(HOLD_JUDGE)]})))
        out["click"] = vs

    # 장전컨 — 전 무기
    out["reload"] = [_v(who, "reload", name, _ctrl(who, {"reload": dict(r)})) for name, r in RELOAD_GRID]

    # 버스트 엄폐컨 — 본인 버스트 사이클에만 걸린다. 레이어 홀드(에이다 등)와 같은 창이라 홀드를 함께 끈다
    vs = []
    if layer.get("cover") != "always":
        on: dict[str, Any] = {"cover": {"policy": "own_full_burst"}}
        if layer.get("hold"):
            on["hold"] = False
        vs.append(_v(who, "cover", "on", _ctrl(who, on)))
    if "cover" in layer:
        vs.append(_v(who, "cover", "off", _ctrl(who, {"cover": False})))
    out["cover"] = vs

    # 탄충 취소
    vs = []
    if layer.get("cancel") != "always":
        vs.append(_v(who, "cancel", "on", _ctrl(who, {"reload": {"cancel_on_full": True}})))
    if "cancel" in layer:
        vs.append(_v(who, "cancel", "off", _ctrl(who, {"reload": {"cancel_on_full": False}})))
    out["cancel"] = vs

    # 버스트 — 딜레이 · 자기 쿨 대기 · 패턴(카탈로그가 있는 니케만). 한 축이라 셋 중 하나만 고른다
    if n["burst_stage"]:
        vs = [_v(who, "burst", f"delay{d:g}", _ctrl(who, {"burst": {"delay": d}})) for d in BURST_DELAYS]
        vs.append(_v(who, "burst", f"wait{WAIT_OWN_COOLDOWN:g}",
                     _ctrl(who, {"burst": {"wait_own_cooldown": WAIT_OWN_COOLDOWN}})))
        for p in n["burst_patterns"]:
            vs.append(_v(who, "burst", f"pattern={p}", _ctrl(who, {"burst": {"pattern": p}})))
        if "burst" in layer:
            vs.append(_v(who, "burst", "pattern_off", _ctrl(who, {"burst": {"pattern": False}})))
        out["burst"] = vs

    excl = info().get("exclude", {})
    return {ax: [v for v in vs if v["label"] not in excl] for ax, vs in out.items()}


def variants(squad: Sequence[str]) -> dict[Key, list[Variant]]:
    """스쿼드의 (니케, 축)마다 선택지 목록. 「바꾸지 않음」(출발점 그대로)은 넣지 않는다.

    - 니케 단위 축(click·reload·cover·cancel·burst)의 키는 (니케, 축), 스쿼드 단위(camera·tactic)는 (None, 축).
    - 선택지가 없는 축은 키를 두지 않는다(빈 list 금지).
    - 순서는 결정론적이어야 한다(같은 스쿼드 → 같은 순서). 좌표 하강이 이 순서로 시도한다.
    - label은 `common.Variant` 규칙을 따른다.

    순서: 배치 순서대로 니케마다 click → reload → cover → cancel → burst, 그 뒤 camera → tactic.
    """
    if len(set(squad)) != len(squad):
        raise ValueError(f"같은 니케가 두 번 있다: {list(squad)}")
    excl = info().get("exclude", {})
    out: dict[Key, list[Variant]] = {}
    for who in squad:
        for ax, vs in nikke_variants(who).items():
            if vs:
                out[(who, ax)] = vs
    cams = [_v(None, "camera", w, {"operation": {"camera": w}}) for w in squad if nikke(w)["charge"]]
    gauge = set(info().get("gauge_by_full_charge", GAUGE_BY_FULL_CHARGE))
    carriers = [_v(None, "tactic", f"{TACTIC}={w}", {"operation": {"tactics": [{"name": TACTIC, "target": w}]}})
                for w in squad if _tappable(nikke(w)) and w not in gauge]
    for ax, vs in (("camera", cams), ("tactic", carriers)):
        vs = [v for v in vs if v["label"] not in excl]
        if vs:
            out[(None, ax)] = vs
    return out


def _holds_own_fb(control: Mapping[str, Any]) -> bool:
    click = control.get("click")
    return isinstance(click, list) and any(
        e.get("window") == "own_full_burst" and e.get("mode") in ("hold", "hold_until_close") for e in click)


def conflicts(chosen: Sequence[Variant]) -> list[str]:
    """평가기가 조립에서 거절하는 조합의 이유 목록(없으면 []). 같은 (니케, 축) 중복은 apply가 따로 거절한다.

    - 같은 니케의 click 홀드(`own_full_burst`)와 cover `on` — 「같은 창에 엄폐컨과 홀드」(CONTROL.md §종전 키).
    """
    why = []
    by_nikke: dict[str, dict[str, Variant]] = {}
    for v in chosen:
        if v["nikke"] is not None:
            by_nikke.setdefault(v["nikke"], {})[v["axis"]] = v
    for who, axes in by_nikke.items():
        click, cover = axes.get("click"), axes.get("cover")
        if click and cover:
            cc = click["patch"]["chars"][who]["control"]
            vc = cover["patch"]["chars"][who]["control"].get("cover")
            if _holds_own_fb(cc) and isinstance(vc, Mapping) and vc.get("policy") == "own_full_burst":
                why.append(f"{who}: {click['label']} + {cover['label']} — 같은 창(own_full_burst)에 홀드와 엄폐컨")
    return why


def apply(options: Mapping[str, Any], chosen: Sequence[Variant]) -> dict[str, Any]:
    """기본 options 위에 선택지 patch들을 병합한 새 options. 입력은 바꾸지 않는다.

    - 같은 (니케, 축)의 선택지가 둘 이상이면 ValueError.
    - 한 니케의 여러 축은 `chars.<니케>.control` 안에서 합친다(예: reload 축과 cancel 축이 모두 `reload` 키를 쓰면
      두 조각을 합쳐야 한다 — 축 사이 키 충돌 규칙은 W2가 정하고 menu.md에 적는다).
    - options의 다른 칸(sim · operation.auto 등)은 보존한다.

    축끼리 같은 잎 키를 쓰지 않으므로(reload 축 = policy·lead·margin·if_dry, cancel 축 = cancel_on_full) 병합 결과는
    순서와 무관하다. 평가기가 거절할 조합(`conflicts()`)이면 `MenuConflict`(ValueError)를 낸다.
    """
    seen: set[tuple[str | None, str]] = set()
    for v in chosen:
        k = (v["nikke"], v["axis"])
        if k in seen:
            raise ValueError(f"같은 (니케, 축)의 선택지가 둘 이상: {k}")
        seen.add(k)
    why = conflicts(chosen)
    if why:
        raise MenuConflict("; ".join(why))
    out = deep_merge(options, {})
    for v in chosen:
        out = deep_merge(out, v["patch"])
    return out


# ── 조립 오류 검사 (--check) ────────────────────────────────────────────────

def pool_names() -> list[str]:
    return list(json.loads(POOL_PATH.read_text(encoding="utf-8"))["pool"])


def check_squad(who: str) -> list[str]:
    return [who] + [f for f in CHECK_FILLERS if f != who][:4]


def check_cases(names: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """니케마다: 기준(선택지 없음) 1 + 니케 단위 선택지 각 1 + 그 니케가 대상인 camera·tactic 각 1 + 모든 축 동시 1."""
    cases = []
    for who in names or pool_names():
        squad = check_squad(who)
        menu = variants(squad)
        base = dict(START_OPTIONS["layer"])
        cases.append({"nikke": who, "label": f"{who}:base", "squad": squad, "options": base})
        mine = [v for (w, _), vs in menu.items() if w == who for v in vs]
        mine += [v for (w, ax), vs in menu.items() if w is None for v in vs
                 if v["patch"]["operation"].get("camera") == who
                 or any(t.get("target") == who for t in v["patch"]["operation"].get("tactics", []))]
        for v in mine:
            cases.append({"nikke": who, "label": v["label"], "squad": squad, "options": apply(base, [v])})
        combo: list[Variant] = []
        for (w, ax), vs in menu.items():
            if w == who:
                for v in vs:  # 앞에서부터 충돌하지 않는 첫 선택지
                    if not conflicts(combo + [v]):
                        combo.append(v)
                        break
        cases.append({"nikke": who, "label": f"{who}:combo", "squad": squad, "options": apply(base, combo),
                      "combo": [v["label"] for v in combo]})
    return cases


def run_check(cases: Sequence[dict[str, Any]], kind: str = "auto") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from nikke_opt.evaluator import EvalRequest, make_evaluator
    ev = make_evaluator(kind)
    try:
        reqs = [EvalRequest(squad=tuple(c["squad"]), options=c["options"]) for c in cases]
        res = ev.evaluate(reqs)
        rows = []
        for c, r in zip(cases, res):
            rows.append({**c, "total_damage": r.total_damage, "error": r.error, "cached": r.cached})
        meta = {"evaluator": ev.version, "sim_count": ev.sim_count, "cache_hits": ev.cache_hits,
                "requests": len(cases)}
    finally:
        ev.close()
    return rows, meta


def check_report(rows: Sequence[dict[str, Any]], meta: Mapping[str, Any]) -> str:
    errs = [r for r in rows if r["error"]]
    ev = meta["evaluator"]
    lines = [f"평가기 {ev.get('repo')} `{str(ev.get('commit', ''))[:7]}` · 요청 {meta['requests']} · "
             f"실제 시뮬 {meta['sim_count']} · 캐시 {meta['cache_hits']} · 오류 {len(errs)}", ""]
    if not errs:
        lines.append("조립 오류 없음.")
        return "\n".join(lines)
    lines += ["| 니케 | 선택지 | 오류 | 메시지 |", "|---|---|---|---|"]
    for r in errs:
        e = r["error"]
        msg = str(e.get("message", "")).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r['nikke']} | `{r['label']}` | {e.get('type')} | {msg} |")
    return "\n".join(lines)


def write_exclude(rows: Sequence[dict[str, Any]]) -> list[str]:
    """선택지 단독 요청의 오류를 nikke_info.json `exclude`에 이유와 함께 적는다. base·combo 오류는 코드를 고칠 일이라 싣지 않는다."""
    data = json.loads(INFO_PATH.read_text(encoding="utf-8"))
    excl = data.setdefault("exclude", {})
    added = []
    for r in rows:
        if r["error"] and not r["label"].endswith((":base", ":combo")):
            excl[r["label"]] = f"{r['error'].get('type')}: {r['error'].get('message')}"
            added.append(r["label"])
    INFO_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    global _INFO
    _INFO = None
    return added


# ── 표 (--table) ───────────────────────────────────────────────────────────

def table(names: Sequence[str] | None = None) -> str:
    """니케별 선택지 표. camera·tactic은 그 니케가 대상이 될 수 있는지만 적는다."""
    names = list(names or pool_names())
    head = "| 니케 | 무기 | 입력 | 버스트 | click | reload | cover | cancel | burst | 카메라 · 버충 | 수 |"
    lines = [head, "|" + "---|" * 11]
    gauge = set(info().get("gauge_by_full_charge", GAUGE_BY_FULL_CHARGE))
    total = 0
    for who in names:
        n = nikke(who)
        nv = nikke_variants(who)
        cell = {ax: " · ".join(v["label"].rsplit(":", 1)[1] for v in nv.get(ax, [])) or "—"
                for ax in ("click", "reload", "cover", "cancel", "burst")}
        if cell["reload"] != "—":
            cell["reload"] = f"{len(nv['reload'])}값"
        sq = ("카메라" if n["charge"] else "") + (" · 버충" if _tappable(n) and who not in gauge else "")
        cnt = sum(len(v) for v in nv.values()) + bool(n["charge"]) + bool(_tappable(n) and who not in gauge)
        total += cnt
        inp = n["input"] + (" · 풀차지 전용" if n["full_charge_only"] else "")
        lines.append(f"| {who} | {n['weapon']} | {inp} | {n['burst_stage'] or '—'} | {cell['click']} | "
                     f"{cell['reload']} | {cell['cover']} | {cell['cancel']} | {cell['burst']} | {sq or '—'} | {cnt} |")
    lines.append(f"\n{len(names)}명, 선택지 합계 {total} (니케당 평균 {total / max(len(names), 1):.1f})")
    return "\n".join(lines)


# ── 추출 (--extract) ───────────────────────────────────────────────────────

_CLICK_KEYS = ("click", "tap_fire", "hold", "sequence")


def _layer_axes(control: Mapping[str, Any]) -> dict[str, bool]:
    """control dict가 건드리는 축. hold = own_full_burst 홀드(엄폐컨과 같은 창)."""
    ax: dict[str, bool] = {}
    if any(k in control for k in _CLICK_KEYS):
        ax["click"] = True
    h = control.get("hold")
    if (isinstance(h, Mapping) and h.get("policy") == "own_full_burst") or _holds_own_fb(control):
        ax["hold"] = True
    r = control.get("reload")
    if isinstance(r, Mapping):
        if "policy" in r or "anchor" in r:
            ax["reload"] = True
        if r.get("cancel_on_full"):
            ax["cancel"] = True
    if control.get("cover"):
        ax["cover"] = True
    b = control.get("burst")
    if isinstance(b, Mapping) and b.get("pattern"):
        ax["burst"] = True
    return ax


def extract(calc_dir: Path) -> dict[str, Any]:
    """nikke-calc 데이터 JSON에서 nikke_info.json을 만든다(읽기 전용, 코드 import 없음)."""
    d = Path(calc_dir) / "data"
    parsed = json.loads((d / "parsed_nikke.json").read_text(encoding="utf-8"))
    defaults = json.loads((d / "char_defaults.json").read_text(encoding="utf-8"))
    skills = json.loads((d / "parsed_skills.json").read_text(encoding="utf-8"))
    commit = subprocess.run(["git", "-C", str(calc_dir), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    old = json.loads(INFO_PATH.read_text(encoding="utf-8")) if INFO_PATH.exists() else {}
    out: dict[str, Any] = {}
    for name in sorted(parsed):
        p = parsed[name]
        if "is_charge" not in p:  # test_B1 등 시험용 더미 항목
            continue
        cd = defaults.get(name, {})
        layer: dict[str, str] = {}
        for ax in _layer_axes(cd.get("control", {})):
            layer[ax] = "always"
        for rule in cd.get("_rules", []):
            for ax in _layer_axes(rule.get("apply", {}).get("control", {})):
                layer.setdefault(ax, "rule")
        out[name] = {
            "weapon": p["weapon_type"],
            "charge": bool(p["is_charge"]),
            "input": p["input_type"],
            "full_charge_only": bool(p["full_charge_only"]),
            "burst_stage": p.get("burst_stage") or None,
            "burst_cooldown": p.get("burst_cooldown"),
            "max_ammo": p.get("max_ammo"),
            "reload_time": p.get("reload_time"),
            "charge_hold": "charge_hold" in json.dumps(skills.get(name, {}), ensure_ascii=False),
            "burst_patterns": list(cd.get("_burst_patterns", {})),
            "layer": dict(sorted(layer.items())),
        }
    return {
        "_source": {
            "repo": "Jgaram/nikke-calc", "commit": commit,
            "files": {"parsed_nikke.json": "weapon_type · is_charge · input_type · full_charge_only · burst_stage · "
                                           "burst_cooldown · max_ammo · reload_time",
                      "char_defaults.json": "_burst_patterns 이름 · 기본 레이어가 건드리는 축(control · _rules[].apply)",
                      "parsed_skills.json": "charge_hold:N 트리거 유무",
                      "docs/CONTROL.md": "gauge_by_full_charge (§버충 컨트롤 §담당 선택)"},
            "command": "python experiments/06_control_menu/menu.py --extract <nikke-calc 체크아웃>",
        },
        "gauge_by_full_charge": list(GAUGE_BY_FULL_CHARGE),
        "exclude": old.get("exclude", {}),
        "nikke": out,
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", action="store_true", help="풀 60명의 선택지 표")
    ap.add_argument("--check", action="store_true", help="조립 오류 검사 (make_evaluator)")
    ap.add_argument("--sample", type=int, default=0, help="--check: 요청을 고르게 N개만")
    ap.add_argument("--nikke", nargs="*", help="--check · --table: 이 니케들만")
    ap.add_argument("--labels", nargs="*", help="--check: 이 label의 요청만 (예: 에이다:cover:on 에이다:combo)")
    ap.add_argument("--evaluator", default="auto", choices=("auto", "rust", "python"))
    ap.add_argument("--write-exclude", action="store_true", help="--check: 단독 선택지 오류를 nikke_info.json exclude에 적는다")
    ap.add_argument("--json-out", type=Path, help="--check: 행 전체를 JSON Lines로")
    ap.add_argument("--extract", type=Path, metavar="NIKKE_CALC_DIR", help="nikke_info.json을 다시 뽑는다")
    a = ap.parse_args(argv)
    if a.extract:
        data = extract(a.extract)
        INFO_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{INFO_PATH} ← {a.extract} ({data['_source']['commit'][:7]}), {len(data['nikke'])}명")
    if a.table:
        print(table(a.nikke))
    if a.check:
        cases = check_cases(a.nikke)
        if a.labels:
            cases = [c for c in cases if c["label"] in set(a.labels)]
        if a.sample and a.sample < len(cases):
            step = len(cases) / a.sample
            cases = [cases[int(i * step)] for i in range(a.sample)]
        rows, meta = run_check(cases, a.evaluator)
        if a.json_out:
            with open(a.json_out, "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(check_report(rows, meta))
        if a.write_exclude:
            added = write_exclude(rows)
            print(f"\nexclude에 {len(added)}개 추가: {added}")
    if not (a.extract or a.table or a.check):
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
