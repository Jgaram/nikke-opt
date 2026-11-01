"""실험 28 — 5덱 편성안의 큰 분류 · 세부 분류(시뮬 0): 실험 25 · 27 기록(w1~w8)으로 계층을 만들어 본다.

    python experiments/28_plan_tree/tree28.py      → results.md · analysis.json

- 큰 분류(J로 나눔): A = 최선 5덱(실험 25 P 판, 후처리 뒤), B = 실험 27 대안(최선과 J ≤ 0.2, 근처 탐색 + 후처리 뒤),
  C = A · B 둘 다와 J ≤ 0.2인 5덱 중 합 최대(기록에서 고르기만, 후처리 전).
- 세부 분류: 대표에서 덱 1~2개만 바뀐 5덱(나머지 3~4덱은 그대로) 중 대표와 J ≥ 0.5이고 합이 최선의 97% 이상인 것.
  J ≥ 0.5 = 맞교환 2번(0.52) · 덱 하나 통째 교체(0.67) · 1~2명 교체(0.72 ~ 0.85)까지. 맞교환 3번(0.35)부터는 뺀다.
- 값: 구성마다 max(기본 레이어, 알려진 운용 값). 대표 덱은 대표의 값(후처리 뒤)을 쓴다. 새 덱은 운용 값이 없으면 기본 레이어라
  세부 분류 값은 낮게 잡힐 수 있다(표시한다). 주력 딜러 개념은 쓰지 않는다.
"""

from __future__ import annotations

import heapq
import importlib.util
import json
import statistics
import sys
import time
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
EXPS = HERE.parent
EXP25, EXP27 = EXPS / "25_jpick_alt", EXPS / "27_alt_local_check"
sys.path.insert(0, str(EXP25))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R27 = sys.modules.get("run27") or _load("run27", EXP27 / "run27.py")
R25, R9, P24, SIM = R27.R25, R27.R9, R27.P24, R27.SIM
E8 = 1e8

THETA_BIG = 0.2           # 큰 분류 대표끼리 J ≤ 0.2
J_SUB = 0.5               # 세부 분류: 대표와 J ≥ 0.5
GOOD = 0.97               # 최선의 97% 이상만
SHOW, MORE = 3, 20        # 표에 3개, 더보기 20개까지
PACK_LIMIT = 120.0


def account(sid: str) -> dict[str, Any]:
    recs = R9.load_records(Path(f"{R25.run_file(sid)}.jsonl.gz")) + R9.load_records(EXP27 / "run_log" / f"{sid}.jsonl.gz")
    book = R9.book_of(recs)
    post: dict[tuple, float] = {}
    for d in (EXP25 / "run_log" / "ops" / "T@main", EXP27 / "run_log" / "ops" / "T@main"):
        for p in d.glob("*.json"):
            r = json.loads(p.read_text(encoding="utf-8"))
            if r["id"].startswith(f"{sid}|") and r.get("value") is not None:
                post[tuple(r["squad"])] = r["value"] / E8
    vals = {c: (max(v, post.get(sq, v)), sq) for c, (v, sq) in book.items()}
    known = {c for c, (_, sq) in book.items() if sq in post}
    return {"book": book, "vals": vals, "known": known, "post": post}


def plan_of(decks: Sequence) -> list[tuple[float, tuple]]:
    return [(float(v), tuple(q)) for v, q in decks]


def key(plan: Sequence[tuple[float, tuple]]) -> frozenset:
    return frozenset(frozenset(q) for _, q in plan)


def pick_far(vals: Mapping[frozenset, tuple[float, tuple]], book: Mapping, refs: Sequence[Sequence[tuple]],
             theta: float = THETA_BIG, limit: float = PACK_LIMIT) -> dict[str, Any]:
    """refs 모두와 J ≤ θ(각 기준과의 공유 쌍 ≤ 예산)인 겹치지 않는 5덱 중 합 최대 — 기준마다 예산을 따로 지키는 분기 한정.
    값 순 DFS, 상한 = 남은 후보 중 앞 r개 값 합. 제한 시간을 넘기면 찾은 해를 쓰고 exact = False."""
    b = P24.budget_of(theta)
    costs = [P24.pair_cost(book, [frozenset(q) for q in r]) for r in refs]
    cands = sorted(((v, sq, c, tuple(ci[c] for ci in costs)) for c, (v, sq) in vals.items()
                    if all(ci[c] <= b for ci in costs)), key=lambda t: (-t[0], t[1]))
    bit: dict[str, int] = {}
    masks = []
    for _, _, c, _ in cands:
        m = 0
        for x in c:
            m |= 1 << bit.setdefault(x, len(bit))
        masks.append(m)
    vs = [t[0] for t in cands]
    cs = [t[3] for t in cands]
    n, k = len(cands), 5
    best = {"total": float("-inf"), "pick": None}
    deadline = time.monotonic() + limit
    state = {"timeout": False, "nodes": 0}

    def ok(i: int, used: int, spent: tuple) -> tuple | None:
        if masks[i] & used:
            return None
        ns = tuple(a + c for a, c in zip(spent, cs[i]))
        return None if any(x > b for x in ns) else ns

    # 시작 해: 앞쪽 후보마다 탐욕 완성
    for first in range(min(n, 200)):
        used, spent, total, pick = 0, tuple(0 for _ in refs), 0.0, []
        for j in range(first, n):
            ns = ok(j, used, spent)
            if ns is None:
                continue
            used, spent, total = used | masks[j], ns, total + vs[j]
            pick.append(j)
            if len(pick) == k:
                break
        if len(pick) == k and total > best["total"]:
            best["total"], best["pick"] = total, pick

    # 값 − μ·비용 순서로도 채워 본다(값 순 탐욕은 두 예산 안에서 못 채우기 쉽다). 합은 후보 번호 순으로 더한다
    for mu in (0.5, 1, 2, 4, 8, 16):
        order = sorted(range(n), key=lambda j: (-(vs[j] - mu * sum(cs[j])), j))
        for first in range(min(n, 50)):
            used, spent, pick = 0, tuple(0 for _ in refs), []
            for j in order[first:]:
                ns = ok(j, used, spent)
                if ns is None:
                    continue
                used, spent = used | masks[j], ns
                pick.append(j)
                if len(pick) == k:
                    break
            if len(pick) == k:
                total = 0.0
                for j in sorted(pick):
                    total += vs[j]
                if total > best["total"]:
                    best["total"], best["pick"] = total, sorted(pick)

    def bound(i0: int, r: int, used: int, spent: tuple) -> float:
        """i0 이후에서, 지금 쓴 니케와 겹치지 않고 혼자서는 예산 안인 후보의 앞 r개 값 합(서로 겹침은 무시)."""
        out, got = 0.0, 0
        for j in range(i0, n):
            if ok(j, used, spent) is not None:
                out += vs[j]
                got += 1
                if got == r:
                    return out
        return float("-inf")

    def dfs(i0: int, r: int, used: int, spent: tuple, total: float, pick: list) -> None:
        if r == 0:
            if total > best["total"]:
                best["total"], best["pick"] = total, list(pick)
            return
        if total + bound(i0, r, used, spent) <= best["total"]:
            return
        for i in range(i0, n - r + 1):
            if total + sum(vs[i:i + r]) <= best["total"]:
                return
            ns = ok(i, used, spent)
            if ns is None:
                continue
            state["nodes"] += 1
            if state["nodes"] % 4096 == 0 and time.monotonic() > deadline:
                state["timeout"] = True
                return
            pick.append(i)
            dfs(i + 1, r - 1, used | masks[i], ns, total + vs[i], pick)
            pick.pop()
            if state["timeout"]:
                return

    dfs(0, k, 0, tuple(0 for _ in refs), 0.0, [])
    if best["pick"] is None:
        return {"found": False, "exact": not state["timeout"]}
    d = [(vs[i], cands[i][1]) for i in best["pick"]]
    return {"found": True, "total": best["total"], "decks": d, "exact": not state["timeout"], "nodes": state["nodes"]}


def subs(rep: Sequence[tuple[float, tuple]], vals: Mapping[frozenset, tuple[float, tuple]], known: set, floor: float,
         cap: int = 400) -> list[dict[str, Any]]:
    """rep에서 덱 1~2개를 바꾼 5덱(나머지 그대로) 중 J ≥ J_SUB · 합 ≥ floor. 합 큰 순 cap개까지."""
    rplan = [list(q) for _, q in rep]
    rkey = key(rep)
    cand = sorted(((v, sq, c) for c, (v, sq) in vals.items()), key=lambda t: -t[0])
    heap: list = []
    seen: set = set()

    def push(total: float, plan: list[tuple[float, tuple]], changed: tuple):
        k = key(plan)
        if k == rkey or k in seen:
            return
        j = SIM.pair_jaccard(rplan, [list(q) for _, q in plan])
        if j < J_SUB:
            return
        seen.add(k)
        item = (total, len(seen), plan, changed, j)
        if len(heap) < cap:
            heapq.heappush(heap, item)
        elif total > heap[0][0]:
            heapq.heapreplace(heap, item)

    n = len(rep)
    for drop in (1, 2):
        for idx in combinations(range(n), drop):
            kept = [rep[i] for i in range(n) if i not in idx]
            kv = sum(v for v, _ in kept)
            used = set().union(*(set(q) for _, q in kept))
            free = [t for t in cand if used.isdisjoint(t[2])]
            if drop == 1:
                for v, sq, c in free:
                    if kv + v < floor:
                        break
                    push(kv + v, kept + [(v, sq)], idx)
            else:
                for a, (v1, s1, c1) in enumerate(free):
                    if kv + v1 + (free[0][0] if free else 0) < floor:
                        break
                    for v2, s2, c2 in free[a + 1:]:
                        if kv + v1 + v2 < floor:
                            break
                        if c1.isdisjoint(c2):
                            push(kv + v1 + v2, kept + [(v1, s1), (v2, s2)], idx)
    out = []
    for total, _, plan, changed, j in sorted(heap, key=lambda t: -t[0]):
        new = [q for _, q in plan[n - len(changed):]]
        rd = [set(rep[i][1]) for i in changed]
        nd = [set(q) for q in new]
        before, after = set().union(*rd), set().union(*nd)
        out.append({"total": total, "J": j, "changed": [i + 1 for i in changed], "new_decks": [list(q) for q in new],
                    "new_values": [v for v, _ in plan[n - len(changed):]],
                    "out": sorted(before - after), "in": sorted(after - before),
                    "moves": SIM.moves([list(q) for _, q in rep], [list(q) for _, q in plan]),
                    "new_unposted": sum(frozenset(q) not in known for q in new)})
    return out


def order_subs(ss: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """표에 보일 SHOW개는 바뀐 덱이 서로 다른 것부터 합 큰 순으로 고르고(같은 덱의 1명 교체만 몰리지 않게), 나머지는 합 순."""
    shown: list[dict[str, Any]] = []
    for s in ss:
        if len(shown) < SHOW and not any(set(s["changed"]) & set(x["changed"]) for x in shown):
            shown.append(s)
    for s in ss:
        if len(shown) >= SHOW:
            break
        if s not in shown:
            shown.append(s)
    return shown + [s for s in ss if s not in shown]


def analyze_account(sid: str) -> dict[str, Any]:
    acc = account(sid)
    p25 = R27.plan25(sid)
    r27 = json.loads((EXP27 / "run_log" / f"{sid}.json").read_text(encoding="utf-8"))
    best = p25["total"]
    floor = GOOD * best
    A = plan_of(p25["decks"])
    B = plan_of(r27["final"]["decks"])
    t0 = time.time()
    c = pick_far(acc["vals"], acc["book"], [[q for _, q in A], [q for _, q in B]])
    C = plan_of(c["decks"]) if c["found"] else None
    classes = []
    for name, rep, note in (("A", A, "최선(후처리 뒤)"), ("B", B, "실험 27 대안(후처리 뒤)"), ("C", C, "기록에서 고르기(후처리 전)")):
        if rep is None:
            classes.append({"name": name, "found": False, "note": note})
            continue
        tot = sum(v for v, _ in rep)
        ss = order_subs(subs(rep, acc["vals"], acc["known"], floor))
        classes.append({"name": name, "found": True, "note": note, "total": tot, "ratio": tot / best,
                        "decks": [[v, list(q)] for v, q in rep], "subs_count": len(ss), "subs": ss[:MORE],
                        "subs_1deck": sum(len(s["changed"]) == 1 for s in ss)})
    reps = {k["name"]: [list(q) for _, q in (A if k["name"] == "A" else B if k["name"] == "B" else C)]
            for k in classes if k["found"]}
    jj = {f"{a}-{b}": SIM.pair_jaccard(reps[a], reps[b]) for a, b in combinations(sorted(reps), 2)}
    for k in classes:
        if not k["found"]:
            continue
        rep = [q for _, q in k["decks"]]
        for s in k["subs"]:
            plan = [list(rep[i]) for i in range(len(rep)) if i + 1 not in s["changed"]] + s["new_decks"]
            s["J_other"] = {o: SIM.pair_jaccard(reps[o], plan) for o in reps if o != k["name"]}
    names = {s["id"]: s["name"] for s in R25.A25.check_scenarios()}
    return {"scenario": sid, "name": names[sid], "best": best, "classes": classes, "rep_J": jj,
            "C_pick": {k: c.get(k) for k in ("found", "exact", "nodes")}, "seconds": round(time.time() - t0, 1)}


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def short(n: str) -> str:
    return n.split(" : ")[0] if " : " in n else n


def main() -> int:
    rows = []
    for s in R25.A25.check_scenarios():
        r = analyze_account(s["id"])
        rows.append(r)
        print(s["id"], [(k["name"], pct(k.get("ratio")), k.get("subs_count")) for k in r["classes"]], r["C_pick"], flush=True)
    L = ["# 실험 28 결과 — 큰 분류 · 세부 분류(시뮬 0, w1~w8)", "",
         "`python experiments/28_plan_tree/tree28.py`가 만든다. 정의는 [README](README.md).", "",
         "## 계정별 요약", "",
         "| 계정 | A 최선 | B (후처리 뒤) | C (후처리 전) | 대표끼리 J (A-B · A-C · B-C) | 세부 분류 수 ≥ 97% (A · B · C) |",
         "|---|---|---|---|---|---|"]
    for r in rows:
        cl = {k["name"]: k for k in r["classes"]}
        jj = r["rep_J"]
        L.append(f"| {r['scenario']} | {r['best']:.1f}억 | {pct(cl['B'].get('ratio'))} | {pct(cl['C'].get('ratio')) if cl['C']['found'] else '없음'} | "
                 f"{jj.get('A-B', 0):.2f} · {jj.get('A-C', 0):.2f} · {jj.get('B-C', 0):.2f} | "
                 f"{cl['A']['subs_count']} · {cl['B']['subs_count']} · {cl['C'].get('subs_count', '—')} |")
    cs = [k["ratio"] for r in rows for k in r["classes"] if k["name"] == "C" and k["found"]]
    L += ["", f"C: 중앙 {pct(statistics.median(cs)) if cs else '—'}, 97% 이상 {sum(x >= GOOD for x in cs)}/{len(rows)}(후처리 전 값). "
              f"세부 분류 수는 상한 400개에서 자른다.", ""]
    for r in rows:
        L += [f"## {r['scenario']} (최선 {r['best']:.1f}억)", ""]
        for k in r["classes"]:
            if not k["found"]:
                L += [f"### 큰 분류 {k['name']} — 없음", ""]
                continue
            L += [f"### 큰 분류 {k['name']} — {pct(k['ratio'])} · {k['note']}", ""]
            for i, (v, q) in enumerate(k["decks"]):
                L.append(f"{i + 1}. {v:.1f}억 — " + " · ".join(short(x) for x in q))
            L += ["", f"세부 분류 {k['subs_count']}개(덱 하나만 바뀐 것 {k['subs_1deck']}개). 위 {SHOW}개는 바뀐 덱이 겹치지 않게 고른 것, 더보기는 합 순 {MORE}개까지:", "",
                  "| # | 합 | J | 바뀐 덱 | 빠짐 → 들어옴 | 새 덱 | 후처리 안 된 새 덱 |", "|---|---|---|---|---|---|---|"]
            for i, s in enumerate(k["subs"]):
                tag = "" if i < SHOW else " (더보기)"
                swap = (" · ".join(short(x) for x in s["out"]) + " → " + " · ".join(short(x) for x in s["in"])) if s["in"] else "같은 니케 · 덱 사이 옮김"
                L.append(f"| {i + 1}{tag} | {pct(s['total'] / r['best'])} | {s['J']:.2f} | {', '.join(map(str, s['changed']))}덱 | {swap} | "
                         + " / ".join(" · ".join(short(x) for x in q) for q in s["new_decks"]) + f" | {s['new_unposted']} |")
            L.append("")
    (HERE / "results.md").write_text("\n".join(L), encoding="utf-8")
    (HERE / "analysis.json").write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
