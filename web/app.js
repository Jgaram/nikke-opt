/* nikke-opt 예측 현황판 — data.json(web/build.py가 만든다)을 읽어 그린다. 외부 라이브러리 없음. */
'use strict';
(() => {
  const BOSSES = ['nocore', 'core30'];
  const BOSS_LABEL = { nocore: '코어 없음', core30: '코어 30px' };
  const AXIS_KO = {
    click: '좌클릭', hold: '홀드', reload: '장전컨', cover: '버스트 엄폐컨', cancel: '풀장전 탄충 취소',
    burst: '버스트', cube: '큐브', camera: '카메라', tactic: '택틱',
  };
  const LAYER_KO = { always: '항상', rule: '조건부' };
  const PHASE_KO = {
    설계: '설계 — 버스트 단계 · 구조 틀만 보고 고르게 만든 스쿼드',
    구성: '구성 — 대리 모델(니케 + 짝)이 높게 본 스쿼드',
    탐색: '탐색 — 5덱 고치기(교체 · 두 덱 맞교환)와 한 명 교체, 100평가씩',
    킥: '킥 — 정체되면 최선 5덱의 덱 2개를 풀어 새로 짓기',
    순서: '순서 — 상위 구성의 배치 순서 다듬기',
    기타: '기타',
  };

  let D = null;
  const state = { season: null, boss: null };
  let charts = [];

  // ------------------------------------------------------------ DOM
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    setAttrs(e, attrs);
    for (const c of kids.flat(Infinity)) {
      if (c == null || c === false) continue;
      e.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  const NS = 'http://www.w3.org/2000/svg';
  function sv(tag, attrs, ...kids) {
    const e = document.createElementNS(NS, tag);
    setAttrs(e, attrs);
    for (const c of kids.flat(Infinity)) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
    return e;
  }
  function setAttrs(e, attrs) {
    if (!attrs) return;
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') e.setAttribute('class', v);
      else if (k === 'text') e.textContent = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : v);
    }
  }
  const $ = (s) => document.querySelector(s);

  // ------------------------------------------------------------ 숫자
  const nf1 = new Intl.NumberFormat('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const nf0 = new Intl.NumberFormat('ko-KR');
  const eok = (v) => (v == null ? '—' : `${nf1.format(v)}억`);
  const pct = (v, d = 1) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`);
  const int = (v) => (v == null ? '—' : nf0.format(Math.round(v)));
  const dur = (s) => {
    if (s == null) return '—';
    const m = Math.round(s / 60);
    return m < 60 ? `${m}분` : `${Math.floor(m / 60)}시간 ${m % 60}분`;
  };
  const day = (iso) => (iso ? iso.slice(0, 10) : '—');
  const median = (xs) => {
    const a = xs.filter((x) => x != null).sort((p, q) => p - q);
    if (!a.length) return null;
    const m = a.length >> 1;
    return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
  };
  function niceStep(span, target) {
    const raw = span / Math.max(1, target);
    const p = 10 ** Math.floor(Math.log10(raw));
    const f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  }

  // ------------------------------------------------------------ 툴팁
  const tip = document.getElementById('tip');
  function showTip(ev, head, rows) {
    tip.replaceChildren(
      h('div', { class: 't-h', text: head }),
      ...rows.map((r) => (typeof r === 'string' ? h('div', { text: r })
        : h('div', { class: 't-r' }, r.key ? h('span', { class: `key ${r.key}` }) : null, r.text))),
    );
    tip.hidden = false;
    placeTip(ev);
  }
  function placeTip(ev) {
    const pad = 14;
    const r = tip.getBoundingClientRect();
    let x = ev.clientX + pad;
    let y = ev.clientY + pad;
    if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - pad;
    tip.style.left = `${Math.max(8, x)}px`;
    tip.style.top = `${Math.max(8, y)}px`;
  }
  const hideTip = () => { tip.hidden = true; };

  // ------------------------------------------------------------ 차트 틀(폭에 맞춰 다시 그린다)
  function chart(draw, label) {
    const el = h('div', { class: 'chart', role: 'img', 'aria-label': label });
    charts.push({ el, draw });
    requestAnimationFrame(() => redraw(el, draw));
    return el;
  }
  function redraw(el, draw) {
    if (!el.isConnected) return;
    el.replaceChildren(draw(Math.max(280, el.clientWidth || 600)));
  }
  let rz = 0;
  window.addEventListener('resize', () => {
    clearTimeout(rz);
    rz = setTimeout(() => {
      charts = charts.filter((c) => c.el.isConnected);
      for (const c of charts) redraw(c.el, c.draw);
    }, 150);
  });

  // ------------------------------------------------------------ 데이터 접근
  const seasonOf = (s) => D.seasons.find((x) => x.season === s);
  const nk = (n) => D.nikke[n] || {};
  const doneRuns = () => D.seasons.flatMap((S) => BOSSES.map((b) => S.by_boss[b]).filter((r) => r.status === 'done'));
  function burstLabel(n) {
    const b = nk(n).b;
    return b === 'A' ? 'B1~3' : b ? `B${b}` : '?';
  }

  // ------------------------------------------------------------ 공통 조각
  function legend(items) {
    return h('div', { class: 'legend' }, items.map(([cls, text]) => h('span', null, h('span', { class: `key ${cls}` }), text)));
  }
  function tile(label, value, note, extra) {
    return h('div', { class: 'tile' }, h('div', { class: 'label', text: label }),
      h('div', { class: 'value' }, value), note ? h('div', { class: 'note' }, note) : null, extra || null);
  }
  function verdictEl(v) {
    const cls = v === '얼추 비슷' ? 'good' : v === '일부 다름' ? 'warn' : 'bad';
    const ico = cls === 'good' ? '✓' : cls === 'warn' ? '!' : '×';
    return h('span', { class: `verdict ${cls}` }, h('span', { class: 'ico', 'aria-hidden': 'true', text: ico }), v);
  }
  function chip(n, o = {}) {
    const info = nk(n);
    const title = [info.w, info.b ? `버스트 ${info.b === 'A' ? '전 단계' : info.b}` : null].filter(Boolean).join(' · ');
    return h('li', { class: `nk${o.lead ? ' lead' : ''}${o.diff ? ' diff' : ''}`, title: title || null },
      h('span', { class: 'bs', text: burstLabel(n) }), n,
      o.dmg != null ? h('span', { class: 'dmg', text: eok(o.dmg) }) : null,
      o.isNew ? h('span', { class: 'tag new', text: '신규' }) : null,
      o.diff ? h('span', { class: 'tag', text: o.diff }) : null);
  }
  function members(order, o = {}) {
    const dmg = Object.fromEntries((o.members || []).map(([n, d]) => [n, d]));
    return h('ol', { class: 'members' }, order.map((n) => chip(n, {
      lead: o.lead === n, dmg: o.members ? dmg[n] : null, isNew: o.newSet && o.newSet.has(n),
      diff: o.otherSet && !o.otherSet.has(n) ? o.diffLabel : null,
    })));
  }
  function details(summary, ...kids) {
    return h('details', null, h('summary', { text: summary }), h('div', { class: 'inner' }, ...kids));
  }
  function tableWrap(t) { return h('div', { class: 'tbl-wrap' }, t); }

  // ------------------------------------------------------------ 머리 · 꼬리
  function renderTheme() {
    const btn = $('#theme');
    const names = { auto: '자동', light: '밝게', dark: '어둡게' };
    let mode = 'auto';
    try { mode = localStorage.getItem('nikke-opt-theme') || 'auto'; } catch (e) { /* 저장소 없음 */ }
    const apply = () => {
      if (mode === 'auto') document.documentElement.removeAttribute('data-theme');
      else document.documentElement.setAttribute('data-theme', mode);
      btn.textContent = `테마: ${names[mode]}`;
    };
    apply();
    btn.addEventListener('click', () => {
      mode = mode === 'auto' ? 'light' : mode === 'light' ? 'dark' : 'auto';
      try { localStorage.setItem('nikke-opt-theme', mode); } catch (e) { /* 저장소 없음 */ }
      apply();
      for (const c of charts) redraw(c.el, c.draw);
    });
  }

  function renderFoot() {
    const src = D.source || {};
    $('#foot').replaceChildren(
      h('p', null, '데이터: ', src.short ? h('a', { href: `${D.repo}/commit/${src.commit}`, text: src.short }) : '—',
        ` (${day(src.date)}) · 사이트 빌드 ${D.built_at.replace('T', ' ').replace('+00:00', ' UTC')}`),
      h('p', null, '평가기: nikke-calc-rs 89d2e64(원본 nikke-calc 23164e4 포팅) · 랭커 자료: ',
        h('a', { href: D.experiment.ranker_repo, text: 'Jgaram/nikke-analysis' }), '의 enikk 원자료(시즌마다 6개 서버 상위 50명 × 5덱)'),
      h('p', null, '실험 문서: ', h('a', { href: D.experiment.readme, text: '실험 22 README' }), ' · 코드: ',
        h('a', { href: D.repo, text: 'Jgaram/nikke-opt' }), ' · 이 페이지는 main에 결과가 올라올 때마다 GitHub Actions가 다시 만듭니다.'),
    );
  }

  // ------------------------------------------------------------ 한눈에
  function renderSummary(root) {
    const j = D.judge;
    const runs = doneRuns();
    const pr = D.progress;
    const c = D.criteria;
    const sec = h('section', { id: 'summary' },
      h('h2', { text: '한눈에' }),
      h('p', { class: 'sub' }, `시즌 8개 × 보스 2개(코어 없음 · 코어 30px) = 사전 계산 16판 중 ${pr.done}판이 끝났습니다. `,
        pr.done < pr.total ? '나머지는 다른 세션이 돌리는 중이며, 결과가 올라오면 이 페이지가 자동으로 채워집니다.' : '모두 끝났습니다.'));
    const tiles = h('div', { class: 'tiles' },
      tile(j.seasons < 8 ? `판단 (잠정 · ${j.seasons}/8시즌)` : '판단', j.seasons ? verdictEl(j.verdict) : '—',
        `기준: N25 중앙 ≥ ${c.N25_MIN} 그리고 V_top 중앙 ≥ ${pct(c.V_MIN, 0)}`),
      tile('N25 중앙', h('span', null, j.N25_med ?? '—', h('small', { text: ' / 25' })),
        `우리 25명 중 랭커 사용 상위 25명에 든 수 · 랭커끼리 직전 시즌 ${j.N25_prev_med ?? '—'}`),
      tile('V_top 중앙', pct(j.V_top_med), '랭커 대표 5덱의 시뮬 합 ÷ 우리 최선 5덱 합'),
      tile('한 판 시뮬 횟수', h('span', null, int(median(runs.map((r) => r.sims))), h('small', { text: '회' })),
        `중앙 · 예산 15,000평가 · 끝난 판 합계 ${int(pr.sims)}회`),
      tile('한 판 시간', dur(median(runs.map((r) => r.seconds))), '중앙 · 4코어 컨테이너에서 4판 동시 실행한 벽시계 시간'),
      tile('최종의 99%에 닿기까지', h('span', null, int(median(runs.map((r) => r.reach['99']))), h('small', { text: '평가' })),
        '중앙 · 수렴 곡선에서 처음 닿은 평가 수'),
    );
    sec.append(tiles);
    root.append(sec);
  }

  // ------------------------------------------------------------ 시즌별 개관
  function dotPlot(rows, o) {
    return (w) => {
      const left = 70; const right = 18; const top = 26; const rowH = 34; const bottom = 28;
      const H = top + rows.length * rowH + bottom;
      const x = (v) => left + ((v - o.lo) / (o.hi - o.lo)) * (w - left - right);
      const svg = sv('svg', { width: w, height: H, viewBox: `0 0 ${w} ${H}` });
      for (const t of o.ticks) {
        svg.append(sv('line', { class: 'grid', x1: x(t), x2: x(t), y1: top - 6, y2: top + rows.length * rowH }));
        svg.append(sv('text', { x: x(t), y: H - 8, 'text-anchor': 'middle', class: 'num', text: o.fmt(t) }));
      }
      svg.append(sv('line', { class: 'thr', x1: x(o.thr), x2: x(o.thr), y1: top - 10, y2: top + rows.length * rowH }));
      svg.append(sv('text', { x: x(o.thr) + 4, y: top - 12, class: 't-ink', text: o.thrLabel }));
      rows.forEach((r, i) => {
        const y = top + i * rowH + rowH / 2;
        const g = sv('g');
        const hit = sv('rect', { class: 'row-hit', x: 0, y: y - rowH / 2, width: w, height: rowH, rx: 6 });
        g.append(hit);
        g.append(sv('text', { x: left - 12, y: y + 4, 'text-anchor': 'end', class: 't-ink', text: r.label }));
        if (r.band) {
          const [a, b] = [Math.min(...r.band), Math.max(...r.band)];
          const x0 = x(a); const x1 = Math.max(x(b), x0 + 4);
          g.append(sv('rect', { class: 'band', x: x0 - 2, y: y - 8, width: x1 - x0 + 4, height: 16, rx: 4 }));
        }
        let any = false;
        BOSSES.forEach((b, k) => {
          const v = r.vals[b];
          if (v == null) return;
          any = true;
          g.append(sv('circle', { class: `f-${b}`, cx: x(Math.max(o.lo, Math.min(o.hi, v))), cy: y + (k ? 5 : -5), r: 5.5 }));
        });
        if (!any) g.append(sv('text', { x: x(o.lo) + 6, y: y + 4, text: '계산 전' }));
        g.addEventListener('pointermove', (ev) => showTip(ev, r.tipHead, r.tipRows));
        g.addEventListener('pointerleave', hideTip);
        g.addEventListener('click', () => { hideTip(); selectSeason(r.season, null, true); });
        g.style.cursor = 'pointer';
        svg.append(g);
      });
      return svg;
    };
  }

  function renderOverview(root) {
    const c = D.criteria;
    const sec = h('section', { id: 'overview' }, h('h2', { text: '시즌별' }),
      h('p', { class: 'sub', text: '줄을 누르면 그 시즌 상세로 갑니다. 회색 띠는 랭커끼리의 눈금입니다 — 직전 시즌 · 같은 약점 직전 시즌의 랭커 상위 25명이 이번 시즌 랭커 상위 25명과 겹친 수.' }));
    const lg = legend([['k-nocore', '우리 예측 · 코어 없음'], ['k-core30', '우리 예측 · 코어 30px'], ['band', '랭커끼리 (직전 · 같은 약점 직전)']]);
    const n25Rows = D.seasons.map((S) => {
      const v = Object.fromEntries(BOSSES.map((b) => [b, S.by_boss[b].status === 'done' ? S.by_boss[b].N25 : null]));
      return {
        season: S.season, label: `S${S.season}`, vals: v,
        band: [S.baseline.N25_prev, S.baseline.N25_same].filter((x) => x != null),
        tipHead: `S${S.season} · ${S.boss_name}`,
        tipRows: [
          ...BOSSES.map((b) => ({ key: `k-${b}`, text: `${BOSS_LABEL[b]}: ${v[b] == null ? '계산 전' : `${v[b]} / 25`}` })),
          `랭커끼리: 직전 시즌(S${S.baseline.prev_season}) ${S.baseline.N25_prev} · 같은 약점(S${S.baseline.same_season ?? '—'}) ${S.baseline.N25_same ?? '—'}`,
        ],
      };
    });
    const vRows = D.seasons.map((S) => {
      const v = Object.fromEntries(BOSSES.map((b) => [b, S.by_boss[b].status === 'done' ? S.by_boss[b].V_top : null]));
      return {
        season: S.season, label: `S${S.season}`, vals: v, band: null,
        tipHead: `S${S.season} · ${S.boss_name}`,
        tipRows: BOSSES.map((b) => ({ key: `k-${b}`, text: `${BOSS_LABEL[b]}: V_top ${v[b] == null ? '계산 전' : pct(v[b])}` })),
      };
    });
    const vs = vRows.flatMap((r) => Object.values(r.vals)).filter((x) => x != null);
    const vlo = Math.min(0.8, Math.floor((Math.min(...vs, 1) - 0.02) * 20) / 20);
    const vhi = Math.max(1.05, Math.ceil((Math.max(...vs, 1) + 0.01) * 20) / 20);
    const vt = []; for (let t = vlo; t <= vhi + 1e-9; t += 0.05) vt.push(Math.round(t * 100) / 100);
    sec.append(h('div', { class: 'grid2' },
      h('div', { class: 'card' }, h('h3', { text: 'N25 — 니케가 얼마나 겹치나' }),
        h('p', { class: 'sub small', text: `우리 최선 5덱 25명 중 그 시즌 랭커 사용 상위 25명에 든 수. 기준 ≥ ${c.N25_MIN}.` }), lg,
        chart(dotPlot(n25Rows, { lo: 0, hi: 25, ticks: [0, 5, 10, 15, 20, 25], thr: c.N25_MIN, thrLabel: `기준 ${c.N25_MIN}`, fmt: (t) => String(t) }),
          '시즌별 N25 점 그래프')),
      h('div', { class: 'card' }, h('h3', { text: 'V_top — 랭커 덱을 시뮬은 얼마로 보나' }),
        h('p', { class: 'sub small', text: `랭커 대표 5덱의 시뮬 합 ÷ 우리 최선 5덱 합(같은 보스). 100%를 넘으면 랭커 덱이 우리 최선보다 높게 나온 것. 기준 ≥ ${pct(c.V_MIN, 0)}.` }),
        legend([['k-nocore', '코어 없음'], ['k-core30', '코어 30px']]),
        chart(dotPlot(vRows, { lo: vlo, hi: vhi, ticks: vt, thr: c.V_MIN, thrLabel: `기준 ${pct(c.V_MIN, 0)}`, fmt: (t) => pct(t, 0) }),
          '시즌별 V_top 점 그래프')),
    ));
    sec.append(h('div', { class: 'card' }, h('h3', { text: '시즌 × 보스 표' }),
      h('p', { class: 'sub small', text: '◀ = 그 시즌에 랭커와 더 맞는 보스(N25 → D4 → V_top 순). 시간은 4판을 동시에 돌린 벽시계 시간입니다.' }),
      tableWrap(overviewTable())));
    root.append(sec);
  }

  function overviewTable() {
    const head = h('tr', null, ['시즌', '기간', '보스 · 속성 → 약점', '풀', '코어', '우리 5덱 합', 'N25', 'D4', 'V_top', 'V_r1', 'V_pack', '시뮬', '시간', '99% 도달']
      .map((t, i) => h('th', { class: i >= 3 && i !== 4 ? 'r' : null, text: t })));
    const body = [];
    for (const S of D.seasons) {
      BOSSES.forEach((b, k) => {
        const r = S.by_boss[b];
        const ok = r.status === 'done';
        const cells = [];
        if (!k) {
          cells.push(h('td', { rowspan: 2 }, h('b', { text: `S${S.season}` })));
          cells.push(h('td', { rowspan: 2, class: 'small nowrap' }, `${day(S.start)}`, h('br'), h('span', { class: 'muted', text: `~ ${day(S.end).slice(5)}` })));
          cells.push(h('td', { rowspan: 2 }, S.boss_name, h('br'), h('span', { class: 'muted small', text: `${S.code} → 약점 ${S.weak_ko}` })));
          cells.push(h('td', { rowspan: 2, class: 'r', text: S.pool_size }));
        }
        cells.push(h('td', { style: 'white-space:nowrap' }, h('span', { class: `dot-inline k-${b}` }), BOSS_LABEL[b],
          S.better === b ? h('span', { class: 'mark', title: '랭커와 더 맞는 보스', text: ' ◀' }) : null));
        if (ok) {
          cells.push(...[eok(r.total), r.N25, `${r.D4}/5`, pct(r.V_top), pct(r.V_r1), pct(r.V_pack), int(r.sims), dur(r.seconds), int(r.reach['99'])]
            .map((t) => h('td', { class: 'r', text: t })));
        } else {
          cells.push(h('td', { colspan: 9 }, h('span', { class: 'pill pending', text: '계산 전' })));
        }
        body.push(h('tr', {
          class: `clickable${state.season === S.season && state.boss === b ? ' sel' : ''}`,
          onclick: () => selectSeason(S.season, b, true),
        }, cells));
      });
    }
    return h('table', { class: 'wide' }, h('thead', null, head), h('tbody', null, body));
  }

  // ------------------------------------------------------------ 시즌 상세
  function renderDetailShell(root) {
    root.append(h('section', { id: 'detail' }, h('h2', { text: '시즌 상세' }),
      h('p', { class: 'sub', text: '시즌(= 그때까지 출시된 니케 풀과 애장품)과 보스 코어를 고르세요.' }),
      h('div', { id: 'picker' }), h('div', { id: 'detail-body' })));
  }

  function selectSeason(s, b, scroll) {
    const S = seasonOf(s);
    state.season = s;
    state.boss = b || (S.better && S.by_boss[S.better].status === 'done' ? S.better
      : BOSSES.find((x) => S.by_boss[x].status === 'done') || 'nocore');
    try { history.replaceState(null, '', `#S${s}-${state.boss}`); } catch (e) { /* file:// 등 */ }
    renderPicker();
    renderDetail();
    const t = document.querySelector('#overview table');
    if (t) t.replaceWith(overviewTable());
    if (scroll) document.getElementById('detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderPicker() {
    const S = seasonOf(state.season);
    const chips = h('div', { class: 'chips', role: 'group', 'aria-label': '시즌' }, D.seasons.map((x) => {
      const n = BOSSES.filter((b) => x.by_boss[b].status === 'done').length;
      return h('button', {
        class: 'chip-btn', type: 'button', 'aria-pressed': String(x.season === state.season),
        onclick: () => selectSeason(x.season, state.boss),
      }, `S${x.season}`, n === 2 ? null : h('span', { class: 'st', text: n === 1 ? '1/2' : '계산 전' }));
    }));
    const seg = h('div', { class: 'seg', role: 'group', 'aria-label': '보스 코어' }, BOSSES.map((b) => h('button', {
      type: 'button', 'aria-pressed': String(b === state.boss), onclick: () => selectSeason(state.season, b),
    }, h('span', { class: `key k-${b}` }), BOSS_LABEL[b], S.by_boss[b].status === 'done' ? null : h('span', { class: 'muted small', text: ' (계산 전)' }))));
    $('#picker').replaceChildren(h('div', { class: 'picker' }, chips, seg));
  }

  function renderDetail() {
    const S = seasonOf(state.season);
    const R = S.by_boss[state.boss];
    const body = $('#detail-body');
    charts = charts.filter((c) => c.el.isConnected);
    const prevS = D.seasons[D.seasons.indexOf(S) - 1];
    const newSet = new Set(S.new_since_prev || []);
    body.replaceChildren(
      h('h3', { style: 'font-size:19px;margin-top:10px' }, `S${S.season} · ${S.boss_name} `,
        h('span', { class: 'muted', style: 'font-weight:500', text: `· ${BOSS_LABEL[state.boss]}` })),
      conditionsCard(S, R, prevS),
      costCard(S),
      R.status === 'done' ? bestCard(S, R, newSet) : h('div', { class: 'card' }, h('h3', { text: '우리 예측 — 1순위 5덱' }),
        h('div', { class: 'empty', text: '이 판은 아직 계산 전입니다. 다른 세션이 결과를 main에 올리면 자동으로 채워집니다. 랭커 덱의 시뮬 값은 아래에서 먼저 볼 수 있습니다.' })),
      R.status === 'done' ? altCard(S, R, newSet) : null,
      robustAltCard(),
      rankerCard(S, R, newSet),
    );
  }

  function conditionsCard(S, R, prevS) {
    const opt = R.options || {};
    const enemy = opt.enemy || { code: S.code, core_px: D.bosses[state.boss].core_px || undefined };
    const newList = S.new_since_prev;
    return h('div', { class: 'card' }, h('h3', { text: '조건 — 보스 · 패치 시점' }),
      h('dl', { class: 'kv' },
        h('dt', { text: '시즌 기간' }), h('dd', { text: `${day(S.start)} ~ ${day(S.end)}` }),
        h('dt', { text: '보스' }), h('dd', null, `${S.boss_name} · 속성 ${S.code} (약점 ${S.weak_ko})`),
        h('dt', { text: '코어' }), h('dd', { text: enemy.core_px ? `있음 · ${enemy.core_px}px` : '없음' }),
        h('dt', { text: '그 밖의 보스 값' }), h('dd', { text: '평가기 기본 적 — 방어력 31,784, 패턴 · 파츠 없음, 180초' }),
        h('dt', { text: '니케 풀' }), h('dd', null, `${S.pool_size}명 — 그 시즌 끝까지 출시된 SSR 전원 보유 · 기본 스펙`,
          newList ? h('span', { class: 'muted', text: ` · S${prevS.season} 이후 신규 ${newList.length}명` }) : null),
        h('dt', { text: '애장품' }), h('dd', { text: S.favorite0.length ? `그때 없던 애장품 ${S.favorite0.length}명은 0단계, 나머지 3단계` : '전원 3단계' }),
        h('dt', { text: '운용' }), h('dd', { text: '큐브 렐릭 베어 Lv15 · 평가기 기본 레이어 컨트롤 고정(후처리 없음) · solo · 버스트 게이지 실누적' }),
      ),
      details('니케 풀 · 신규 · 애장품 0단계 목록',
        newList && newList.length ? h('p', null, h('b', { text: `S${prevS.season} 이후 신규 (${newList.length}명): ` }), newList.join(', ')) : null,
        S.favorite0.length ? h('p', null, h('b', { text: '애장품 0단계: ' }), S.favorite0.join(', ')) : null,
        h('p', null, h('b', { text: `풀 (${S.pool_size}명): ` }), S.pool.join(', '))),
    );
  }

  function convChart(S) {
    const ser = BOSSES.map((b) => ({ b, r: S.by_boss[b] })).filter((x) => x.r.status === 'done' && x.r.history.length);
    return (w) => {
      const left = 46; const right = 14; const top = 14; const bottom = 30; const H = 240;
      const xmax = Math.max(...ser.map((x) => x.r.history[x.r.history.length - 1][0]), 1000);
      const ratios = ser.flatMap((x) => x.r.history.map(([, v]) => v / x.r.total));
      const ylo = Math.max(0, Math.floor((Math.min(...ratios) - 0.01) * 20) / 20);
      const yhi = 1.0;
      const X = (v) => left + (v / xmax) * (w - left - right);
      const Y = (v) => top + (1 - (v - ylo) / (yhi - ylo)) * (H - top - bottom);
      const svg = sv('svg', { width: w, height: H, viewBox: `0 0 ${w} ${H}` });
      const ys = niceStep(yhi - ylo, 4);
      for (let t = Math.ceil(ylo / ys) * ys; t <= yhi + 1e-9; t += ys) {
        svg.append(sv('line', { class: 'grid', x1: left, x2: w - right, y1: Y(t), y2: Y(t) }));
        svg.append(sv('text', { x: left - 6, y: Y(t) + 4, 'text-anchor': 'end', class: 'num', text: pct(t, 0) }));
      }
      const xs = niceStep(xmax, w < 480 ? 3 : 6);
      for (let t = 0; t <= xmax + 1e-9; t += xs) {
        svg.append(sv('text', { x: X(t), y: H - 10, 'text-anchor': 'middle', class: 'num', text: int(t) }));
      }
      svg.append(sv('line', { class: 'axis', x1: left, x2: w - right, y1: H - bottom, y2: H - bottom }));
      svg.append(sv('line', { class: 'thr', x1: left, x2: w - right, y1: Y(0.99), y2: Y(0.99), 'stroke-opacity': 0.5 }));
      const at = (r, e) => {
        let v = null;
        for (const [ee, vv] of r.history) { if (ee <= e) v = vv; else break; }
        return v;
      };
      for (const { b, r } of ser) {
        let d = '';
        r.history.forEach(([e, v], i) => {
          d += i ? ` H${X(e).toFixed(1)} V${Y(v / r.total).toFixed(1)}` : `M${X(e).toFixed(1)} ${Y(v / r.total).toFixed(1)}`;
        });
        svg.append(sv('path', { class: `s-${b}`, d }));
        const r99 = r.reach['99'];
        if (r99 != null) svg.append(sv('circle', { class: `f-${b}`, cx: X(r99), cy: Y(at(r, r99) / r.total), r: 5 }));
      }
      const xh = sv('line', { class: 'xh', y1: top, y2: H - bottom, visibility: 'hidden' });
      const dots = ser.map(({ b }) => sv('circle', { class: `f-${b}`, r: 5, visibility: 'hidden' }));
      svg.append(xh, ...dots);
      const hit = sv('rect', { class: 'hit', x: left, y: top, width: w - left - right, height: H - top - bottom });
      hit.addEventListener('pointermove', (ev) => {
        const box = svg.getBoundingClientRect();
        const e = Math.max(0, Math.min(xmax, ((ev.clientX - box.left - left) / (w - left - right)) * xmax));
        xh.setAttribute('x1', X(e)); xh.setAttribute('x2', X(e)); xh.setAttribute('visibility', 'visible');
        const rows = [];
        ser.forEach(({ b, r }, i) => {
          const v = at(r, e);
          if (v == null) { dots[i].setAttribute('visibility', 'hidden'); return; }
          dots[i].setAttribute('cx', X(e)); dots[i].setAttribute('cy', Y(v / r.total)); dots[i].setAttribute('visibility', 'visible');
          rows.push({ key: `k-${b}`, text: `${BOSS_LABEL[b]}: ${eok(v)} (최종의 ${pct(v / r.total)})` });
        });
        showTip(ev, `평가 ${int(e)}회까지의 최선 5덱 합`, rows.length ? rows : ['아직 첫 5덱 전']);
      });
      hit.addEventListener('pointerleave', () => {
        hideTip(); xh.setAttribute('visibility', 'hidden'); dots.forEach((d) => d.setAttribute('visibility', 'hidden'));
      });
      svg.append(hit);
      return svg;
    };
  }

  function costCard(S) {
    const done = BOSSES.filter((b) => S.by_boss[b].status === 'done');
    const card = h('div', { class: 'card' }, h('h3', { text: '예측에 든 시뮬 횟수와 시간' }),
      h('p', { class: 'sub small', text: '랭커 정보 없는 사전 계산 한 판(G+E, 예산 15,000평가). 평가 1회 = 180초 전체 시뮬 1회(이 판에서는 캐시 재사용 없음).' }));
    if (!done.length) {
      card.append(h('div', { class: 'empty', text: '이 시즌은 두 판 모두 계산 전입니다.' }));
      return card;
    }
    card.append(h('div', { class: 'tiles' }, done.map((b) => {
      const r = S.by_boss[b];
      const meta = D.runs_meta[r.name];
      return tile(BOSS_LABEL[b], h('span', null, int(r.sims), h('small', { text: '회' })),
        `${dur(r.seconds)} · ${nf1.format(r.sims / r.seconds)}회/초 · 99% 도달 ${int(r.reach['99'])}평가${meta && meta.session ? ` · ${meta.session} 세션` : ''}`);
    })));
    card.append(legend([['k-nocore', '코어 없음'], ['k-core30', '코어 30px']].filter(([k]) => done.includes(k.slice(2))).concat([['line k-ref', '최종의 99%']])),
      chart(convChart(S), `S${S.season} 탐색 수렴 곡선`),
      h('p', { class: 'small muted', text: '가로: 평가 수 · 세로: 그때까지 찾은 최선 5덱 합 ÷ 최종 합. 점 = 최종의 99%에 처음 닿은 곳. 계단이 뛰는 곳은 대개 킥(덱 2개를 풀어 새로 짓기)이 통한 자리입니다.' }));
    const pTable = h('table', null,
      h('thead', null, h('tr', null, h('th', { text: '단계' }), done.map((b) => h('th', { class: 'r', text: BOSS_LABEL[b] })))),
      h('tbody', null, Object.keys(PHASE_KO).filter((p) => done.some((b) => S.by_boss[b].phases[p])).map((p) => h('tr', null,
        h('td', { text: PHASE_KO[p] }), done.map((b) => h('td', { class: 'r', text: int(S.by_boss[b].phases[p] || 0) }))))));
    const reachT = h('table', null,
      h('thead', null, h('tr', null, h('th', { text: '최종 합의' }), done.map((b) => h('th', { class: 'r', text: BOSS_LABEL[b] })))),
      h('tbody', null, ['95', '99', '99.5', '100'].map((k) => h('tr', null, h('td', { text: `${k}%에 처음 닿은 평가 수` }),
        done.map((b) => h('td', { class: 'r', text: int(S.by_boss[b].reach[k]) }))))));
    card.append(details('단계별 시뮬 수 · 도달 평가 수(표)', tableWrap(pTable), tableWrap(reachT)));
    return card;
  }

  function controlDetails(order, settings) {
    const lay = order.filter((n) => Object.keys(nk(n).layer || {}).length);
    const items = lay.map((n) => {
      const L = nk(n).layer;
      const pat = nk(n).pat || [];
      return h('li', null, h('b', { text: n }), ' — ',
        Object.entries(L).map(([a, v]) => `${AXIS_KO[a] || a}(${LAYER_KO[v] || v})`).join(', '),
        pat.length && L.burst ? ` · 버스트 패턴 카탈로그: ${pat.join(' / ')}` : '');
    });
    return details('운용 · 컨트롤 보기',
      h('p', null, h('b', { text: '큐브: ' }), '5명 모두 렐릭 베어 큐브 Lv15(평가기 기본 스펙 큐브, 고정).'),
      settings && settings.length
        ? [h('p', null, h('b', { text: '탐색에서 고른 컨트롤:' })), h('ul', null, settings.map((s) => h('li', { text: s })))]
        : h('p', null, h('b', { text: '탐색에서 고른 컨트롤: ' }), '없음 — 실험 22는 큐브 · 컨트롤 후처리를 하지 않았습니다.'),
      h('p', null, h('b', { text: '평가기 기본 레이어가 이 덱에 거는 컨트롤:' })),
      items.length ? h('ul', null, items) : h('p', { text: '이 덱의 니케에는 기본 레이어 규칙이 없습니다 — 모두 평가기 기본 자동 운용입니다.' }),
      h('p', { class: 'muted small', text: '조건부 규칙은 동료 · 딜 순위 같은 조건이 맞을 때만 걸립니다. 이 덱에서 조건이 맞는지는 여기서 판정하지 않았습니다(nikke-calc 23164e4의 char_defaults 기준).' }),
      h('p', null, h('b', { text: '조작: ' }), 'solo — 조작자 1명, 조작이 겹치면 급한 쪽이 카메라를 가져갑니다. 버스트 입력은 카메라와 무관합니다.'),
      h('p', { class: 'muted small', text: '나중 과제: 여러 컨트롤이 겹칠 때 어느 것을 먼저 적용하는지(평가기의 우선순위 로직)도 함께 보여 주기.' }),
    );
  }

  function deckBlock(i, d, o) {
    const head = h('div', { class: 'deck-head' },
      h('span', { class: 'deck-no', text: i != null ? `${i + 1}` : '' }),
      h('span', { class: 'deck-val', text: eok(d.value) }),
      d.leader ? h('span', { class: 'deck-meta', text: `주력 ${d.leader}` }) : null,
      o.matchNote ? h('span', { class: 'deck-meta', text: o.matchNote }) : null,
      o.countNote ? h('span', { class: 'deck-meta', text: o.countNote }) : null);
    return h('div', { class: 'deck' }, head,
      members(d.order, { lead: d.leader, members: d.members, newSet: o.newSet, otherSet: o.otherSet, diffLabel: o.diffLabel }),
      o.controls ? controlDetails(d.order, d.settings) : null);
  }

  function bestCard(S, R, newSet) {
    const near = (d) => `랭커 상위 40 스쿼드와 최대 ${d.match}/5명 같음`;
    return h('div', { class: 'card' }, h('h3', { text: `우리 예측 — 1순위 5덱 · ${eok(R.total)}` }),
      h('p', { class: 'sub small' }, '덱 안의 순서 = 배치 순서. ',
        h('span', { class: 'nk', style: 'padding:0 6px 0 3px' }, h('span', { class: 'bs', text: 'B1' }), '버스트 단계'), ' ',
        h('span', { class: 'tag new', text: '신규' }), ' = 직전 표시 시즌 이후 추가된 니케. ',
        R.members_ready ? '굵은 테두리 = 주력(덱 딜 1위).' : '니케별 딜 · 주력은 members 계산 뒤 표시됩니다(일부는 랭커 덱과 같은 순서라 먼저 보임).'),
      h('div', { class: 'decks' }, R.decks.map((d, i) => {
        const blk = deckBlock(i, d, { newSet, controls: true, matchNote: near(d) });
        if (d.near) {
          blk.insertBefore(h('div', { class: 'small muted', style: 'margin-top:6px' },
            `가장 가까운 랭커 스쿼드(${d.near.count}명 사용): ${d.near.order.join(' · ')}`), blk.lastChild);
        }
        return blk;
      })));
  }

  function altCard(S, R, newSet) {
    const card = h('div', { class: 'card' }, h('h3', { text: '후순위 — 2~8순위 5덱' }),
      h('p', { class: 'sub small', text: '사전 계산이 「앞 순위들과 같은 덱(5명 그대로)을 2개 이하만 공유하는」 조건으로 차례로 뽑은 다음 최선 5덱입니다. 덱 묶음은 다르지만 니케는 대부분 겹칩니다.' }));
    if (!R.alts.length) {
      card.append(h('div', { class: 'empty', text: '기록에 후순위 5덱이 없습니다.' }));
      return card;
    }
    const best25 = new Set(R.decks.flatMap((d) => d.order));
    card.append(tableWrap(h('table', null,
      h('thead', null, h('tr', null, ['순위', '5덱 합', '1순위 대비', '같은 덱', '공유 니케', '빠진 니케 → 들어온 니케']
        .map((t, i) => h('th', { class: i && i < 5 ? 'r' : null, text: t })))),
      h('tbody', null, R.alts.map((a) => h('tr', null,
        h('td', { text: `${a.rank}순위` }), h('td', { class: 'r', text: eok(a.total) }), h('td', { class: 'r', text: pct(a.ratio, 2) }),
        h('td', { class: 'r', text: `${a.same_decks}/5` }), h('td', { class: 'r', text: `${a.shared}/25` }),
        h('td', { class: 'small', text: a.in.length ? `${a.out.join(', ')} → ${a.in.join(', ')}` : '같은 25명 — 덱 나누기만 다름' })))))));
    for (const a of R.alts) {
      card.append(details(`${a.rank}순위 덱 보기 · ${eok(a.total)}`,
        h('div', { class: 'decks' }, a.decks.map((d, i) => deckBlock(i, d, { newSet, otherSet: best25, diffLabel: '1순위에 없음' })))));
    }
    return card;
  }

  function robustAltCard() {
    return h('div', { class: 'card' }, h('h3', { text: '유력 대안 — 뼈대가 다른 안' }),
      h('div', { class: 'empty' }, h('b', { text: '공란 — 실험 22에서는 계산하지 않았습니다. ' }),
        '이 레포의 「유력 대안」은 최선 5덱의 덱 두 개를 기록에서 빼고 다시 짠 안 중, 합이 최선의 97% 이상이고 다시 짠 덱 · 주력 딜러가 다른 덱이 각각 2개 이상인 것입니다(실험 20 · 21). ',
        '실험 21의 가상 계정 8개(허수아비 보스)에서는 8개 모두 찾았습니다.'));
  }

  function totalsBars(R) {
    const rk = R.rankers || {};
    const rows = [];
    if (R.status === 'done') rows.push({ label: '우리 1순위 5덱', v: R.total, ours: true, note: '' });
    if (rk.top_five) rows.push({ label: `랭커 대표 5덱`, v: rk.top_five.total, note: `${rk.top_five.count}명이 5덱 그대로 사용` });
    if (rk.rank1) rows.push({ label: `랭커 1위 5덱`, v: rk.rank1.total, note: `${rk.rank1.server || ''} 서버` });
    if (rk.pack) rows.push({ label: '랭커 상위 40 스쿼드로 짠 최선', v: rk.pack.total, note: '랭커가 쓴 스쿼드만으로 겹치지 않게 묶은 최고' });
    const max = Math.max(...rows.map((r) => r.v || 0), 1);
    return h('div', { class: 'bars' }, rows.map((r) => h('div', { class: 'ubar', title: r.note || null },
      h('span', null, r.label, r.note ? h('div', { class: 'muted', style: 'font-size:12px', text: r.note }) : null),
      h('span', { class: 'track' }, h('span', { class: `fill${r.ours ? ' ours' : ''}`, style: `width:${((r.v || 0) / max) * 100}%;${r.ours ? `background:var(--c-${state.boss})` : ''}` })),
      h('span', { class: 'num', text: `${eok(r.v)}${R.status === 'done' && !r.ours && r.v ? ` · ${pct(r.v / R.total)}` : ''}` }))));
  }

  function rankerCard(S, R, newSet) {
    const rk = R.rankers || {};
    const done = R.status === 'done';
    const card = h('div', { class: 'card' }, h('h3', { text: '랭커 덱과 비교' }),
      h('p', { class: 'sub small', text: `${S.rankers.players}명 · ${int(S.rankers.decks)}덱(6개 서버 상위 50명). 랭커 덱도 같은 평가기 · 같은 보스 조건 · 기본 스펙으로 시뮬한 값입니다.` }));
    if (done) {
      card.append(h('div', { class: 'tiles' },
        tile('N25', h('span', null, R.N25, h('small', { text: ' / 25' })), `랭커끼리 직전 시즌 ${S.baseline.N25_prev} · 같은 약점 직전 ${S.baseline.N25_same ?? '—'}`),
        tile('D4', h('span', null, R.D4, h('small', { text: ' / 5' })), '랭커 상위 40 스쿼드와 4명 이상 같은 우리 덱 수'),
        tile('V_top', pct(R.V_top), '랭커 대표 5덱 ÷ 우리'),
        tile('V_r1', pct(R.V_r1), '랭커 1위 5덱 ÷ 우리'),
        tile('V_pack', pct(R.V_pack), '랭커 스쿼드로 짠 최선 ÷ 우리'),
        tile('주력 겹침', R.main_overlap == null ? '—' : h('span', null, R.main_overlap, h('small', { text: ' / 5' })),
          R.main_overlap == null ? 'members 계산 뒤 표시' : '우리 덱 주력 중 랭커 스쿼드 주력에 있는 수')));
    }
    card.append(h('h4', { text: `5덱 합 시뮬 값 · ${BOSS_LABEL[state.boss]}` }), totalsBars(R));
    if (rk.rank1 && rk.rank1.real) {
      card.append(h('p', { class: 'small muted', text: `참고: 랭커 1위의 실제 기록은 ${eok(rk.rank1.real)}입니다. 실전 육성(레벨 · 큐브 · 소장품) · 보스 패턴 · 파츠가 들어간 값이라 위 시뮬 값과 직접 비교하지 않습니다.` }));
    }
    const top5 = rk.top_five ? rk.top_five.decks : [];
    const ours = done ? R.decks : [];
    const ours25 = new Set(ours.flatMap((d) => d.order));
    const top25s = new Set(top5.flatMap((d) => d.order));
    card.append(h('h4', { text: '덱 나란히 보기' }),
      h('p', { class: 'small muted', text: '점선 테두리 = 상대 5덱(25명)에 없는 니케.' }),
      h('div', { class: 'vs' },
        h('div', null, h('b', { text: `우리 1순위 · ${eok(done ? R.total : null)}` }),
          done ? h('div', { class: 'decks', style: 'margin-top:6px' }, ours.map((d, i) => deckBlock(i, d, { newSet, otherSet: top25s, diffLabel: '우리만' })))
            : h('div', { class: 'empty', style: 'margin-top:6px', text: '계산 전' })),
        h('div', null, h('b', { text: `랭커 대표 5덱 · ${eok(rk.top_five && rk.top_five.total)} · ${rk.top_five ? rk.top_five.count : 0}명` }),
          h('div', { class: 'decks', style: 'margin-top:6px' }, top5.map((d, i) => deckBlock(i, d, { newSet, otherSet: done ? ours25 : null, diffLabel: '랭커만' }))))));
    if (rk.rank1) {
      card.append(details(`랭커 1위 5덱 보기 (${rk.rank1.server || ''}) · 시뮬 ${eok(rk.rank1.total)}`,
        h('div', { class: 'decks' }, rk.rank1.decks.map((d, i) => deckBlock(i, d, { newSet, otherSet: done ? ours25 : null, diffLabel: '우리 5덱에 없음' })))));
    }
    if (rk.pack) {
      card.append(details(`랭커 상위 40 스쿼드로 짠 최선 5덱 보기 · ${eok(rk.pack.total)}`,
        h('div', { class: 'decks' }, rk.pack.decks.map((d, i) => deckBlock(i, d, { newSet, otherSet: done ? ours25 : null, diffLabel: '우리 5덱에 없음' })))));
    }
    // 니케 사용
    const units = S.rankers.units.slice(0, 25);
    const players = S.rankers.players;
    card.append(h('h4', { text: '랭커 사용 상위 25명' }),
      h('p', { class: 'small muted', text: done ? `막대 = ${players}명 중 쓴 랭커 수 · ✓ = 우리 1순위 5덱에도 있음` : `막대 = ${players}명 중 쓴 랭커 수` }),
      h('div', { class: 'ulist' }, units.map(([n, c]) => h('div', { class: 'ubar' },
        h('span', null, done ? (ours25.has(n) ? '✓ ' : '　 ') : '', n),
        h('span', { class: 'track' }, h('span', { class: 'fill', style: `width:${(c / players) * 100}%` })),
        h('span', { class: 'num small', text: c })))));
    if (done) {
      card.append(h('p', { class: 'small' }, h('b', { text: '우리만 쓴 니케: ' }), R.ours_only.length ? R.ours_only.join(', ') : '없음'),
        h('p', { class: 'small' }, h('b', { text: '랭커 상위 25인데 우리가 안 쓴 니케: ' }), R.rankers_only.length ? R.rankers_only.join(', ') : '없음'));
    }
    // 상위 40 스쿼드
    const sq = rk.squads || [];
    card.append(details(`랭커 상위 ${sq.length} 스쿼드 표 (이 보스 시뮬 값)`, tableWrap(h('table', { class: 'mid' },
      h('thead', null, h('tr', null, ['쓴 랭커', '배치 순서', '시뮬 딜', '주력', '우리 덱과 최대 겹침'].map((t, i) => h('th', { class: i === 0 || i === 2 || i === 4 ? 'r' : null, text: t })))),
      h('tbody', null, sq.map((q) => h('tr', null,
        h('td', { class: 'r', text: q.count }), h('td', { class: 'small', text: q.order.join(' · ') }),
        h('td', { class: 'r', text: q.value == null ? '평가기 밖' : eok(q.value) }), h('td', { class: 'small', text: q.leader || '—' }),
        h('td', { class: 'r', text: done ? `${q.overlap}/5` : '—' }))))))));
    if (done && R.coef_top && R.coef_top.length) {
      card.append(details('탐색이 본 니케 가치 상위 20 (대리 모델)', h('p', { class: 'small muted', text: '사전 계산의 마지막 대리 모델(니케 + 짝 릿지)이 매긴 니케 단독 항입니다. 짝 효과는 빠져 있어, 짝을 타는 니케는 낮게 나올 수 있습니다.' }),
        tableWrap(h('table', null, h('thead', null, h('tr', null, ['니케', '단독 항', '우리 5덱', '랭커 상위 25'].map((t, i) => h('th', { class: i ? 'r' : null, text: t })))),
          h('tbody', null, R.coef_top.map(([n, v, a, b]) => h('tr', null, h('td', { text: n }), h('td', { class: 'r', text: nf1.format(v) }),
            h('td', { class: 'r', text: a ? '✓' : '' }), h('td', { class: 'r', text: b ? '✓' : '' }))))))));
    }
    return card;
  }

  // ------------------------------------------------------------ 읽는 법
  function renderAbout(root) {
    const c = D.criteria;
    root.append(h('section', { id: 'about' }, h('h2', { text: '읽는 법' }),
      h('div', { class: 'grid2' },
        h('div', { class: 'card' }, h('h3', { text: '이 예측은 어떻게 나왔나' }),
          h('ul', null,
            h('li', { text: '계정 = 그 시즌 끝까지 출시된 SSR 전원 보유 · 기본 스펙. 랭커 덱 · 사용률은 탐색에 쓰지 않습니다.' }),
            h('li', { text: '보스 = 평가기 기본 적에 시즌 보스 속성과 코어(없음 · 30px)만 바꿔 넣음. 패턴 · 파츠는 없습니다.' }),
            h('li', { text: '탐색 = 실험 12의 랭커 없는 사전 계산(G+E) 15,000평가: 고르게 만든 스쿼드 → 대리 모델이 고른 스쿼드 → 5덱 고치기 · 한 명 교체 국소 탐색, 정체되면 킥, 끝에 배치 순서 다듬기.' }),
            h('li', { text: '5덱 = 평가한 스쿼드 중 니케가 겹치지 않는 5개의 합이 최대인 묶음.' }),
            h('li', { text: '운용 = 큐브 렐릭 베어 Lv15 · 평가기 기본 레이어 컨트롤 고정. 큐브 · 컨트롤 탐색은 하지 않았습니다.' }))),
        h('div', { class: 'card' }, h('h3', { text: '지표' }),
          h('dl', { class: 'kv' },
            h('dt', { text: 'N25' }), h('dd', { text: `우리 25명 중 그 시즌 랭커 사용 상위 25명에 든 수(0~25). 기준 중앙 ≥ ${c.N25_MIN}.` }),
            h('dt', { text: 'D4' }), h('dd', { text: '우리 5덱 중 랭커 상위 40 스쿼드 어느 것과 4명 이상 같은 덱 수(0~5).' }),
            h('dt', { text: 'V_top' }), h('dd', { text: `랭커 대표 5덱(5덱을 그대로 쓴 랭커가 가장 많은 조합)의 시뮬 합 ÷ 우리 최선 합. 기준 중앙 ≥ ${pct(c.V_MIN, 0)}.` }),
            h('dt', { text: 'V_r1 · V_pack' }), h('dd', { text: '같은 비율: 1위 5덱 · 랭커 상위 40 스쿼드만으로 짠 최선 5덱.' }),
            h('dt', { text: '더 맞는 보스' }), h('dd', { text: '시즌마다 N25가 큰 보스(같으면 D4, 그다음 V_top). 판단은 이 보스의 값으로 8시즌 중앙을 봅니다.' }),
            h('dt', { text: '판단' }), h('dd', { text: '얼추 비슷 = 두 기준 모두 · 일부 다름 = 하나만 · 다름 = 둘 다 아님.' })))),
      h('div', { class: 'card' }, h('h3', { text: '한계' }),
        h('ul', null,
          h('li', { text: '실전 정확도를 검증하는 실험이 아닙니다. 보스 패턴 · 파츠 · 실제 코어 크기와 위치 · 랭커 육성(레벨 · 큐브 · 소장품) · 그 시점 밸런스와 평가기 데이터 차이가 모두 빠졌습니다.' }),
          h('li', { text: '사전 계산 시드가 하나라 4번 중 1번 꼴로 뼈대를 놓칠 수 있습니다(실험 12).' }),
          h('li', { text: '시뮬은 지금 평가기 데이터(nikke-calc-rs 89d2e64)로 돌렸습니다. 옛 시즌의 당시 수치와 다를 수 있습니다.' }),
          h('li', { text: '랭커 덱 칸 중 평가기 풀 밖(SR · R 등)은 S4 0.9% · S9 0.1% · 나머지 0%입니다.' }))),
    ));
  }

  // ------------------------------------------------------------ 시작
  function initialSelection() {
    const m = /^#S(\d+)-(nocore|core30)$/.exec(location.hash);
    if (m && seasonOf(Number(m[1]))) return [Number(m[1]), m[2], true];
    const withDone = D.seasons.filter((S) => BOSSES.some((b) => S.by_boss[b].status === 'done'));
    const S = withDone.length ? withDone[withDone.length - 1] : D.seasons[D.seasons.length - 1];
    return [S.season, null, false];
  }

  async function main() {
    renderTheme();
    const app = $('#app');
    try {
      const res = await fetch('data.json', { cache: 'no-cache' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      D = await res.json();
    } catch (e) {
      app.replaceChildren(h('p', { class: 'loading', text: `data.json을 읽지 못했습니다 (${e.message}). web/build.py로 만든 폴더에서 열어 주세요.` }));
      return;
    }
    app.replaceChildren();
    renderSummary(app);
    renderOverview(app);
    renderDetailShell(app);
    renderAbout(app);
    renderFoot();
    const [s, b, scroll] = initialSelection();
    selectSeason(s, b, false);
    if (scroll) requestAnimationFrame(() => document.getElementById('detail').scrollIntoView());
  }
  main();
})();
