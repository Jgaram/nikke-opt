"""실험 33 Q1 분석(시뮬 0) — README §Q1 사전 등록의 지문 · 확인 1~5.

    python experiments/33_role_vectors/run33.py q1     → q1.md · run_log/q1.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
R = sys.modules["run33"] if "run33" in sys.modules else None
if R is None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("run33", HERE / "run33.py")
    R = importlib.util.module_from_spec(spec)
    sys.modules["run33"] = R
    spec.loader.exec_module(R)

# ---------------------------------------------------------------- 사전 등록한 문턱(README §Q1)
REPRO_MIN = 0.8          # 확인 1: dealer · buffer 순위 상관
ADV_MATCH_MIN = 0.90     # 확인 2: adv_argmax = BEATS 속성인 니케 비율
TOP_THIRD = 1 / 3        # 확인 3 · 4: 같은 단계 상위 1/3 (순위 ≤ 수 × 1/3)
SPREAD_TOP = 1 / 4       # 확인 4
TOVE_LIFT_MIN = 1.5      # 확인 5
TOVE_TOP = 0.10          # 확인 5: 2단계 상위 10%
EXAMPLES_ADV = ("아니스 : 스타", "리틀 머메이드", "나유타")
LM = "리틀 머메이드"


def real(names) -> list[str]:
    return [n for n in names if not n.startswith(R.TEST_PREFIX)]


def in_top(rank: int, n: int, frac: float) -> bool:
    return rank <= frac * n


def stage_names(at: Mapping[str, Mapping[str, str]], names, stage: str) -> list[str]:
    return [n for n in names if at[n]["stage"] == stage]


def check_repro(fa: Mapping[str, Mapping], fb: Mapping[str, Mapping], keys=("dealer", "buffer", "spread", "own_adv", "adv_lift")
                ) -> dict[str, Any]:
    out = {}
    for k in keys:
        ns = [n for n in real(fa) if n in fb and fa[n].get(k) is not None and fb[n].get(k) is not None]
        out[k] = {"n": len(ns), "rho": R.spearman([fa[n][k] for n in ns], [fb[n][k] for n in ns]) if len(ns) > 2 else None}
    out["stable"] = all(out[k]["rho"] is not None and out[k]["rho"] >= REPRO_MIN for k in ("dealer", "buffer"))
    return out


def check_adv(fp: Mapping[str, Mapping], at: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    ns = [n for n in real(fp) if fp[n].get("adv_argmax")]
    miss = sorted(n for n in ns if fp[n]["adv_argmax"] != R.adv_element(at[n]["code"]))
    share = 1 - len(miss) / len(ns) if ns else None
    return {"n": len(ns), "match": share, "ok": share is not None and share >= ADV_MATCH_MIN, "miss": miss}


def check_examples(fp: Mapping[str, Mapping], at: Mapping[str, Mapping[str, str]], tl: Mapping[str, float]) -> dict[str, Any]:
    names = real(fp)
    out: dict[str, Any] = {}
    for x in EXAMPLES_ADV:
        st = stage_names(at, names, at[x]["stage"])
        rb, nb = R.rank_of({n: fp[n]["buffer"] for n in st}, x, st)
        ra, na = R.rank_of({n: fp[n]["own_adv"] for n in st}, x, st)
        out[x] = {"buffer_rank": [rb, nb], "own_adv_rank": [ra, na],
                  "ok": in_top(rb, nb, TOP_THIRD) and in_top(ra, na, TOP_THIRD)}
    top_buf = []
    for s in sorted({at[n]["stage"] for n in names}):
        st = stage_names(at, names, s)
        order = sorted((n for n in st if fp[n]["buffer"] is not None), key=lambda n: (-fp[n]["buffer"], n))
        top_buf += [n for i, n in enumerate(order, 1) if in_top(i, len(order), TOP_THIRD)]
    if LM in top_buf:
        rs, ns = R.rank_of({n: fp[n]["spread"] for n in top_buf}, LM, top_buf)
        out["spread_" + LM] = {"spread_rank": [rs, ns], "of": "buffer 같은 단계 상위 1/3", "ok": in_top(rs, ns, SPREAD_TOP)}
    else:
        out["spread_" + LM] = {"spread_rank": None, "of": "buffer 같은 단계 상위 1/3", "ok": False,
                               "note": f"{LM}이 buffer 상위 1/3 묶음에 없다"}
    st2 = [n for n in real(tl) if at[n]["stage"] == "2"]
    b = R.BREAD
    if b in tl:
        rt, nt = R.rank_of({n: tl[n] for n in st2}, b, st2)
        out["tove_" + b] = {"tove_lift": tl[b], "rank": [rt, nt], "ok": tl[b] >= TOVE_LIFT_MIN and in_top(rt, nt, TOVE_TOP)}
    else:
        out["tove_" + b] = {"tove_lift": None, "ok": False, "note": "토브 확인 기록 없음"}
    return out


def _f(v, d=3) -> str:
    return "—" if v is None else f"{v:.{d}f}"


def table_top(fp, at, key: str, stage: str, n: int = 10) -> list[str]:
    st = [x for x in real(fp) if at[x]["stage"] == stage and fp[x].get(key) is not None]
    order = sorted(st, key=lambda x: (-fp[x][key], x))[:n]
    return [f"| {i} | {x} | {at[x]['weapon']} · {at[x]['code']} | {_f(fp[x]['dealer'])} | {_f(fp[x]['buffer'])} | "
            f"{_f(fp[x]['own_adv'])} | {_f(fp[x]['adv_lift'], 2)} | {_f(fp[x]['spread'], 2)} |" for i, x in enumerate(order, 1)]


def report(res: Mapping[str, Any], at) -> str:
    fp = res["fp"]["R"]
    c = res["checks"]
    L = ["# 실험 33 Q1 — 역할 지문 결과", "", f"`analyze33.py` 생성. 평가기 {res['evaluator']}. 판단은 README §Q1 사전 등록 그대로다.", "",
         "## 확인", "", "| # | 확인 | 결과 | 판정 |", "|---|---|---|---|"]
    rp = c["repro"]
    L.append(f"| 1 | 재현성(R 대 R2 스피어만) | dealer {_f(rp['dealer']['rho'], 2)} · buffer {_f(rp['buffer']['rho'], 2)} · "
             f"spread {_f(rp['spread']['rho'], 2)} · own_adv {_f(rp['own_adv']['rho'], 2)} · adv_lift {_f(rp['adv_lift']['rho'], 2)} "
             f"(n = {rp['dealer']['n']}) | {'안정' if rp['stable'] else '불안정'} |")
    ad = c["adv"]
    L.append(f"| 2 | 우코 상성 | {_f(ad['match'], 3)}({ad['n']}명 중 어긋남 {len(ad['miss'])}) | {'맞음' if ad['ok'] else '미달'} |")
    ex = c["examples"]
    for x in EXAMPLES_ADV:
        e = ex[x]
        L.append(f"| 3 | {x} | buffer {e['buffer_rank'][0]}/{e['buffer_rank'][1]} · own_adv {e['own_adv_rank'][0]}/{e['own_adv_rank'][1]} "
                 f"(같은 단계) | {'맞음' if e['ok'] else '아님'} |")
    e = ex["spread_" + LM]
    L.append(f"| 4 | {LM} 흩어짐 | {'—' if e['spread_rank'] is None else f'{e['spread_rank'][0]}/{e['spread_rank'][1]}'} ({e['of']}) | "
             f"{'맞음' if e['ok'] else '아님'} |")
    e = ex["tove_" + R.BREAD]
    L.append(f"| 5 | {R.BREAD} + 토브 | tove_lift {_f(e.get('tove_lift'), 2)} · 2단계 순위 "
             f"{'—' if not e.get('rank') else f'{e['rank'][0]}/{e['rank'][1]}'} | {'맞음' if e['ok'] else '아님'} |")
    if ad["miss"]:
        L += ["", "우코 상성 어긋남: " + " · ".join(f"{n}({at[n]['code']} → 최대 {fp[n]['adv_argmax']})" for n in ad["miss"])]
    L += ["", "## 예시 니케 지문(R)", "", "| 니케 | 단계 · 무기 · 코드 | dealer | buffer | own_adv | adv_lift | spread | 가장 많이 올리는 동료 무기 |",
          "|---|---|---:|---:|---:|---:|---:|---|"]
    for x in list(EXAMPLES_ADV) + [R.BREAD, R.TOVE]:
        f = fp.get(x)
        if not f:
            continue
        bw = max(f["boost_weapon"].items(), key=lambda kv: kv[1]) if f["boost_weapon"] else ("—", None)
        L.append(f"| {x} | {at[x]['stage']} · {at[x]['weapon']} · {at[x]['code']} | {_f(f['dealer'])} | {_f(f['buffer'])} | "
                 f"{_f(f['own_adv'])} | {_f(f['adv_lift'], 2)} | {_f(f['spread'], 2)} | {bw[0]} {_f(bw[1], 3)} |")
    for key, title in (("dealer", "dealer(본인 딜) 상위"), ("buffer", "buffer(동료 딜 변화) 상위")):
        for s in ("1", "2", "3"):
            L += ["", f"## {title} — {s}단계", "", "| # | 니케 | 무기 · 코드 | dealer | buffer | own_adv | adv_lift | spread |",
                  "|---:|---|---|---:|---:|---:|---:|---:|"] + table_top(fp, at, key, s)
    L += ["", "## 비용", "", "| 묶음 | 요청 | 새 시뮬 | 초 |", "|---|---:|---:|---:|"]
    for k, v in res["cost"].items():
        L.append(f"| {k} | {v.get('requests', v.get('evals', '—'))} | {v['sims']} | {v['seconds']} |")
    return "\n".join(L) + "\n"


def cmd_q1() -> int:
    at = R.attrs()
    recs = {s: R.load_recs(R.LOG / f"probe_{s}.jsonl.gz") for s in ("R", "R2", "T")}
    fp = {"R": R.fingerprints(recs["R"], at), "R2": R.fingerprints(recs["R2"], at),
          "R+R2": R.fingerprints(recs["R"] + recs["R2"], at)}
    tl = R.tove_lifts(recs["R"], recs["T"])
    checks = {"repro": check_repro(fp["R"], fp["R2"]), "adv": check_adv(fp["R"], at),
              "examples": check_examples(fp["R"], at, tl)}
    cost = {}
    for el in R.ELEMENTS:
        for k in R.SEEDS:
            p = R.pre_path(el, k).with_suffix("").with_suffix(".json")
            if p.exists():
                cost[f"P {el} s{k}"] = json.loads(p.read_text(encoding="utf-8"))
    for s in ("R", "R2", "T"):
        cost[f"넣어 보기 {s}"] = json.loads((R.LOG / f"probe_{s}.json").read_text(encoding="utf-8"))
    ev = cost["넣어 보기 R"]["evaluator"]
    res = {"evaluator": f"{ev.get('repo')} {str(ev.get('commit'))[:7]}", "fp": fp, "tove_lift": tl, "checks": checks,
           "cost": {k: {kk: vv for kk, vv in v.items() if kk != "evaluator"} for k, v in cost.items()}}
    (R.LOG / "q1.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (HERE / "q1.md").write_text(report(res, at), encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, indent=1))
    return 0
