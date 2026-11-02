/* nikke-opt 현황판(실험 31 · 최근 10시즌 편성안 지도) — data.json(web/build.py가 만든다)을 읽어 그린다. 외부 라이브러리 없음. */
'use strict';
(() => {
  const BOSSES = ['nocore', 'core30'];
  const BOSS_LABEL = { nocore: '코어 없음', core30: '코어 30px' };
  const EL_KO = { Electric: '전격', Fire: '작열', Iron: '철갑', Water: '수냉', Wind: '풍압' };
  const ARM_KO = { B: 'B — 시드 2개 합치기', W: 'W — 넓게 찾기' };
  // 버스트 단계 → nikke-analysis 버스트 문양(파일 · 가로 · 세로 px, 세로 13 기준)
  const BURST_GLYPH = { 1: ['i', 6, 13], 2: ['ii', 11, 13], 3: ['iii', 14, 13], A: ['i-ii-iii', 14, 13] };
  const FACE_BADGE = { lg: { el: 17, burst: 10 }, md: { el: 14, burst: 8 } };   // 얼굴 크기별 속성 · 버스트 표시 크기(sm은 없음)

  let D = null;
  const state = { season: null, boss: 'nocore' };

  // ------------------------------------------------------------ DOM
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === 'class') e.setAttribute('class', v);
        else if (k === 'text') e.textContent = v;
        else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
        else e.setAttribute(k, v === true ? '' : v);
      }
    }
    for (const c of kids.flat(Infinity)) {
      if (c == null || c === false) continue;
      e.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  const $ = (s) => document.querySelector(s);

  // ------------------------------------------------------------ 숫자
  const nf1 = new Intl.NumberFormat('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const nf0 = new Intl.NumberFormat('ko-KR');
  const eok = (v) => (v == null ? '—' : `${nf1.format(v)}억`);
  const pct = (v, d = 1) => (v == null ? '—' : `${(v * 100).toFixed(d)}%`);
  const int = (v) => (v == null ? '—' : nf0.format(Math.round(v)));
  const jf = (v) => (v == null ? '—' : v.toFixed(2));
  const dur = (s) => {
    if (s == null) return '—';
    const m = Math.round(s / 60);
    return m < 60 ? `${m}분` : `${Math.floor(m / 60)}시간 ${m % 60}분`;
  };
  const day = (iso) => (iso ? iso.slice(0, 10) : '—');
  const md = (iso) => (iso ? iso.slice(5, 10) : '—');
  const median = (xs) => {
    const a = xs.filter((x) => x != null).sort((p, q) => p - q);
    if (!a.length) return null;
    const m = a.length >> 1;
    return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
  };

  // ------------------------------------------------------------ 데이터 접근
  const seasonOf = (s) => D.seasons.find((x) => x.season === s);
  const nk = (n) => D.nikke[n] || {};
  const runOf = (S, b = state.boss) => S.by_boss[b];
  const doneRuns = (b = state.boss) => D.seasons.map((S) => runOf(S, b)).filter((r) => r.status === 'done');
  const clsLetter = (c) => (c.name || '').slice(0, 1);

  // ------------------------------------------------------------ 그림(니케 · 속성은 글자 없이 그림으로만)
  function elIcon(code, size = 16) {
    if (!code) return null;
    return h('img', { class: 'el', src: `icons/elements/${code.toLowerCase()}.png`, alt: EL_KO[code] || code,
      width: size, height: Math.round((size * 73) / 63), decoding: 'async' });
  }
  function burstGlyph(b, height) {
    const g = BURST_GLYPH[b];
    if (!g) return null;
    const url = `url("icons/bursts/${g[0]}.png")`;
    const w = Math.round((g[1] * height) / g[2]);
    return h('span', { class: 'glyph', role: 'img', 'aria-label': b === 'A' ? '버스트 전 단계' : `버스트 ${b}단계`,
      style: `width:${w}px;height:${height}px;-webkit-mask-image:${url};mask-image:${url}` });
  }
  function missingFace(n) {
    return h('span', { class: 'face-img face-missing', role: 'img', 'aria-label': n, text: '?' });
  }
  // 니케 얼굴. size: lg(덱) · md(목록) · sm(표 · 줄 안). lg · md는 오른쪽 위에 속성, 왼쪽 아래에 버스트 단계를 붙인다.
  function face(n, size = 'md', o = {}) {
    const info = nk(n);
    const cls = ['face', `f-${size}`, o.diff && 'diff', o.dim && 'dim'].filter(Boolean).join(' ');
    const img = info.img
      ? h('img', { class: 'face-img', src: info.img, alt: n, loading: 'lazy', decoding: 'async',
        onerror: (e) => e.target.replaceWith(missingFace(n)) })
      : missingFace(n);
    const badge = FACE_BADGE[size];
    return h('span', { class: cls }, img,
      badge && info.el && info.el.length ? h('span', { class: 'els' }, info.el.map((e) => elIcon(e, badge.el))) : null,
      badge && info.b ? h('span', { class: 'bst' }, burstGlyph(info.b, badge.burst)) : null,
      o.check ? h('span', { class: 'chk', 'aria-label': '우리 최선(A)에도 있음', text: '✓' }) : null,
      o.isNew ? h('span', { class: 'nw', 'aria-label': '새 니케', text: 'N' }) : null);
  }
  function faces(list, size = 'sm', o = {}) {
    return h('ul', { class: `faces faces-${size}` }, (list || []).map((n) => h('li', null, face(n, size, {
      dim: o.dimSet ? o.dimSet.has(n) : false, check: o.checkSet ? o.checkSet.has(n) : false,
    }))));
  }
  function bossImg(S, cls = 'boss-thumb') {
    return S.boss_img ? h('img', { class: cls, src: S.boss_img, alt: S.boss_name, decoding: 'async' }) : null;
  }
  // 보스 속성 → 약점, 그림으로
  function elPair(S, size = 16) {
    return h('span', { class: 'el-pair' }, elIcon(S.element, size), h('span', { class: 'arrow', 'aria-label': '약점', text: '→' }), elIcon(S.weak, size));
  }
  function badge(name, sm) {
    const l = (name || '').slice(0, 1);
    return h('span', { class: `cls-badge${sm ? ' sm' : ''} c-${'ABC'.includes(l) ? l : 'X'}`, text: name });
  }

  // ------------------------------------------------------------ 공통 조각
  function tile(label, value, note) {
    return h('div', { class: 'tile' }, h('div', { class: 'label', text: label }),
      h('div', { class: 'value' }, value), note ? h('div', { class: 'note' }, note) : null);
  }
  function tableWrap(t) { return h('div', { class: 'tbl-wrap' }, t); }
  function card(id, title, sub, ...kids) {
    return h('section', { class: 'card', id }, h('h3', { text: title }), sub ? h('p', { class: 'sub' }, sub) : null, ...kids);
  }
  function lazyDetails(cls, summary, fill, open) {
    const d = h('details', { class: cls, open: open || null }, summary, h('div', { class: 'lazy' }));
    const go = () => { if (d.open && !d.dataset.filled) { d.dataset.filled = '1'; d.lastChild.replaceChildren(...fill()); } };
    d.addEventListener('toggle', go);
    if (open) requestAnimationFrame(go);
    return d;
  }
  // 5덱 격자: 행 = 덱(1~5), 열 = 배치 순서. 5덱 묶음 하나가 격자 하나다.
  // o: title · note · size(lg = 큰 얼굴 + 니케별 딜, md = 작은 얼굴) · otherSet(없으면 점선) · newSet · hl(바뀐 덱 번호 Set, 1부터)
  function fiveGrid(set, o = {}) {
    const size = o.size || 'lg';
    const head = h('figcaption', { class: 'fg-head' },
      o.badge ? badge(o.badge) : null,
      h('span', { class: 'fg-title', text: o.title }),
      h('span', { class: 'fg-total', text: set ? eok(set.total) : '—' }),
      o.note ? h('span', { class: 'fg-note' }, o.note) : null);
    if (!set) {
      return h('figure', { class: `fgrid fg-${size}` }, head, h('div', { class: 'empty', text: o.empty || '계산 전' }));
    }
    const rows = set.decks.map((d, i) => {
      const dmg = Object.fromEntries((d.members || []).map(([n, v]) => [n, v]));
      const chg = !!(o.hl && o.hl.has(i + 1));
      return h('div', { class: `fg-row${chg ? ' chg' : ''}`, role: 'row' },
        h('div', { class: 'fg-lab', role: 'rowheader' },
          h('span', { class: 'fg-no', text: `${i + 1}` }),
          h('span', { class: 'fg-val', text: eok(d.value) }),
          chg ? h('span', { class: 'fg-chg', text: '바뀜' }) : null),
        d.order.map((n) => h('div', { class: 'fg-cell', role: 'cell' },
          face(n, size, { diff: !!(o.otherSet && !o.otherSet.has(n)), isNew: !!(o.newSet && o.newSet.has(n)) }),
          size === 'lg' && d.members ? h('span', { class: 'dmg', text: dmg[n] == null ? '' : eok(dmg[n]) }) : null)));
    });
    return h('figure', { class: `fgrid fg-${size}${o.ours ? ' ours' : ''}` }, head,
      h('div', { class: 'fg-body', role: 'table', 'aria-label': `${o.title} 5덱` }, rows));
  }
  function bossSeg(onPick) {
    return h('div', { class: 'seg', role: 'group', 'aria-label': '보스 조건' }, BOSSES.map((b) => h('button', {
      type: 'button', 'aria-pressed': String(b === state.boss), onclick: () => onPick(b),
    }, BOSS_LABEL[b])));
  }

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
    });
  }
  function renderFoot() {
    const src = D.source || {};
    const E = D.experiment;
    $('#foot').replaceChildren(
      h('p', null, '데이터: ', src.short ? h('a', { href: `${D.repo}/commit/${src.commit}`, text: src.short }) : '—',
        ` (${day(src.date)}) · 사이트 빌드 ${D.built_at.replace('T', ' ').replace('+00:00', ' UTC')}`),
      h('p', null, '평가기: nikke-calc-rs 89d2e64(원본 nikke-calc 23164e4 포팅) · 시즌 · 랭커 자료: ',
        h('a', { href: E.ranker_repo, text: 'Jgaram/nikke-analysis' }), E.analysis_repo_commit ? ` ${E.analysis_repo_commit}` : '',
        '의 enikk 원자료(시즌마다 6개 서버 상위 50명 × 5덱) · 출시일 · 애장품 날짜'),
      h('p', null, '실험 문서: ', h('a', { href: E.readme, text: '실험 31 README' }), ' · 절차: ',
        h('a', { href: E.exp30_readme, text: '실험 30' }), ' · 분류 정의: ', h('a', { href: E.exp28_readme, text: '실험 28' }),
        ' · 코드: ', h('a', { href: D.repo, text: 'Jgaram/nikke-opt' }), ' · 이 페이지는 main에 결과가 올라올 때마다 GitHub Actions가 다시 만듭니다.'),
      iconCredit(),
    );
  }
  function iconCredit() {
    const s = (D.icons && D.icons.source) || {};
    const at = s.repo && s.commit ? h('a', { href: `${s.repo}/tree/${s.commit}/data/assets/icons`, text: `Jgaram/nikke-analysis ${s.commit.slice(0, 7)}` }) : 'Jgaram/nikke-analysis';
    return h('p', null, '니케 얼굴 · 속성 · 버스트 · 보스 그림: ', at,
      '(blablalink · enikk에서 받은 것). 게임 이름 · 그림의 권리는 SHIFT UP · Level Infinite에 있습니다.');
  }

  // ------------------------------------------------------------ 한눈에
  function renderSummary(root) {
    root.append(h('section', { id: 'summary' }, h('h2', { text: '한눈에' }), h('div', { id: 'summary-body' })));
    renderSummaryBody();
  }
  function renderSummaryBody() {
    const P = D.progress;
    const runs = doneRuns();
    const arm = D.experiment.arm;
    const pending = P.done === 0;
    const tiles = h('div', { class: 'tiles' },
      tile('진행', h('span', null, `${P.done}`, h('small', { text: ` / ${P.total} 시즌` })),
        P.started > P.done ? `실행 중 ${P.started - P.done}시즌` : pending ? '실험 30 판정 뒤 실행' : null),
      tile('탐색 판', arm ? arm : '—', arm ? ARM_KO[arm] : '실험 30 판정 대기'),
      tile('새 시뮬', int(P.sims), '10시즌 합(부분별 기록)'),
      tile('97% 이상 큰 분류', runs.length ? `${median(runs.map((r) => r.n97))}개` : '—', `시즌 중앙 · ${BOSS_LABEL[state.boss]}`),
      tile('N25', runs.length ? `${median(runs.map((r) => r.metrics.N25))}` : '—', '우리 A 25명 중 랭커 상위 25명 · 시즌 중앙'),
      tile('V_top', runs.length ? pct(median(runs.map((r) => r.metrics.V_top))) : '—', '랭커 대표 5덱 ÷ 우리 A · 시즌 중앙'));
    $('#summary-body').replaceChildren(
      h('p', { class: 'sub' }, '시즌마다 그 시즌의 ', h('b', { text: '니케 풀 · 보스 속성 · 그때 있던 애장품' }),
        '만 주고(랭커 정보 없이) 찾은 5덱을 ', h('b', { text: '큰 분류' }), '(덱 나누기가 크게 다른 안)와 ',
        h('b', { text: '세부 분류' }), '(덱 1~2개만 바꾼 안)로 나눠, 그 시즌 랭커 덱과 나란히 봅니다. 줄을 누르면 시즌 상세로 갑니다.'),
      tiles,
      h('div', { class: 'picker' }, bossSeg((b) => { state.boss = b; renderSummaryBody(); selectSeason(state.season, b); })),
      overviewTable());
  }
  function overviewTable() {
    const head = h('tr', null, ['시즌', '기간', '속성 → 약점', '풀', '애장품 끔', '큰 분류 ≥97%', 'A · B · C (최선 대비)', '세부 분류 A · B · C', 'N25', 'V_top', '랭커 대표 ≈'].map((t, i) =>
      h('th', { class: i >= 3 && i !== 6 && i !== 10 ? 'r' : null, text: t })));
    const rows = D.seasons.map((S) => {
      const R = runOf(S);
      const done = R.status === 'done';
      const cl = done ? R.classes.slice(0, 3) : [];
      const near = done && R.classes.length ? nearest(R.metrics.J_top) : null;
      return h('tr', { class: `clickable${S.season === state.season ? ' sel' : ''}`, 'data-s': S.season,
        onclick: () => { selectSeason(S.season, state.boss); $('#detail').scrollIntoView({ behavior: 'smooth' }); } },
      h('td', null, h('div', { class: 'boss-cell' }, bossImg(S), h('div', null, h('b', { text: `S${S.season}` }), h('div', { class: 'small muted', text: S.boss_name })))),
      h('td', { class: 'small nowrap', text: `${day(S.start)} ~ ${md(S.end)}` }),
      h('td', null, elPair(S)),
      h('td', { class: 'r' }, `${S.pool}`, S.new.length ? h('span', { class: 'muted small', text: ` +${S.new.length}` }) : null),
      h('td', { class: 'r', text: S.favorite0.length ? `${S.favorite0.length}명` : '—' }),
      done ? h('td', { class: 'r', text: `${R.n97}` }) : h('td', { class: 'r muted', text: S.parts && Object.keys(S.parts).length ? '실행 중' : '계산 전' }),
      h('td', { class: 'small nowrap' }, done ? cl.map((c, i) => [i ? ' · ' : '', badge(c.name, true), ` ${pct(c.ratio)}`]) : ''),
      h('td', { class: 'r', text: done ? cl.map((c) => `${int(c.subs_count)}${c.capped ? '+' : ''}`).join(' · ') : '' }),
      h('td', { class: 'r', text: done ? `${R.metrics.N25}` : '' }),
      h('td', { class: 'r', text: done ? pct(R.metrics.V_top) : '' }),
      h('td', { class: 'small nowrap' }, near ? [badge(near[0], true), ` J ${jf(near[1])}`] : ''));
    });
    return h('div', { class: 'card', id: 'overview' }, h('h3', { text: `시즌 10개 · ${BOSS_LABEL[state.boss]}` }),
      h('p', { class: 'sub small' }, '큰 분류 ≥97% = 최선의 97% 이상인 큰 분류 수. 세부 분류 400+ = 400개에서 자름. ',
        'N25 = 우리 A 25명 중 그 시즌 랭커 사용 상위 25명. V_top = 랭커 대표 5덱의 시뮬 합 ÷ 우리 A. 랭커 대표 ≈ = 랭커 대표 5덱과 J가 가장 큰 큰 분류.'),
      tableWrap(h('table', { class: 'wide' }, h('thead', null, head), h('tbody', null, rows))));
  }
  const nearest = (jmap) => Object.entries(jmap || {}).sort((a, b) => b[1] - a[1])[0] || null;

  // ------------------------------------------------------------ 시즌 상세
  function renderDetailShell(root) {
    root.append(h('section', { id: 'detail' }, h('h2', { text: '시즌 상세' }), h('div', { id: 'picker' }), h('div', { id: 'season-body' })));
  }
  function selectSeason(s, b) {
    if (!seasonOf(s)) s = D.seasons[D.seasons.length - 1].season;
    state.season = s;
    if (b) state.boss = b;
    try { history.replaceState(null, '', `#S${s}-${state.boss}`); } catch (e) { /* file:// 등 */ }
    renderPicker();
    renderDetail();
    const t = document.querySelector('#overview tbody');
    if (t) for (const tr of t.children) tr.classList.toggle('sel', Number(tr.dataset.s) === s);
  }
  function renderPicker() {
    const chips = h('div', { class: 'chips', role: 'group', 'aria-label': '시즌' }, D.seasons.map((S) => h('button', {
      class: 'chip-btn season-chip', type: 'button', 'aria-pressed': String(S.season === state.season),
      onclick: () => selectSeason(S.season, state.boss),
    }, bossImg(S, 'chip-boss'), `S${S.season}`, runOf(S).status === 'done' ? null : h('span', { class: 'st', text: '·' }))));
    $('#picker').replaceChildren(h('div', { class: 'picker' }, chips,
      bossSeg((b) => { selectSeason(state.season, b); renderSummaryBody(); })));
  }
  function renderDetail() {
    const S = seasonOf(state.season);
    const R = runOf(S);
    $('#season-body').replaceChildren(seasonHero(S), classesCard(S, R), rankerCard(S, R), costCard(S));
  }

  function seasonHero(S) {
    const facts = [
      h('span', { class: 'fact' }, elPair(S, 18), h('span', { class: 'muted small', text: `${EL_KO[S.element]} 보스 · 약점 ${EL_KO[S.weak]}` })),
      h('span', { class: 'fact' }, h('span', { class: 'muted', text: '풀' }), h('b', { text: `${S.pool}명` })),
      h('span', { class: 'fact' }, h('span', { class: 'muted', text: '랭커' }), `${int(S.rankers.players)}명 × 5덱`),
    ];
    const rows = [];
    if (S.new.length) rows.push(h('div', { class: 'cond' }, h('span', { class: 'cond-k', text: '새 니케(직전 시즌 뒤)' }), faces(S.new, 'md')));
    rows.push(h('div', { class: 'cond' }, h('span', { class: 'cond-k', text: '애장품 끔(그때 없던 애장품)' }),
      S.favorite0.length ? faces(S.favorite0, 'md') : h('span', { class: 'muted small', text: '없음 — 풀의 애장품이 모두 나와 있던 시즌' })));
    if (S.excluded_nikke.length || S.excluded_treasure.length) {
      rows.push(h('div', { class: 'cond' }, h('span', { class: 'cond-k', text: '날짜 경계로 뺀 것' }),
        h('div', null,
          S.excluded_nikke.length ? h('div', { class: 'cond-line' }, h('span', { class: 'small muted', text: '니케 ' }), faces(S.excluded_nikke, 'md')) : null,
          S.excluded_treasure.length ? h('div', { class: 'cond-line' }, h('span', { class: 'small muted', text: '애장품 ' }), faces(S.excluded_treasure, 'md')) : null,
          h('p', { class: 'small muted', text: '시즌이 끝나는 날 점검 뒤에 들어온 것(실험 22 규칙은 그 시즌에 넣었다). 그 시즌 랭커 사용 0회.' }))));
    }
    return h('div', { class: 'card season-hero' },
      h('div', { class: 'boss-hero' }, bossImg(S, 'boss-img'),
        h('div', { class: 'boss-text' },
          h('p', { class: 'eyebrow', text: `S${S.season} · ${day(S.start)} ~ ${day(S.end)}` }),
          h('h3', { class: 'boss-name', text: S.boss_name }),
          h('div', { class: 'boss-facts' }, facts))),
      h('div', { class: 'conds' }, rows));
  }

  // 큰 분류: 앞 D.show.classes개는 펼친 상자, 나머지는 더보기
  function classesCard(S, R) {
    const sub = h('span', null, h('b', { text: '큰 분류' }), ' = 대표끼리 쌍 자카드 J ≤ 0.2(덱 나누기가 크게 다른 5덱), A = 최선. ',
      h('b', { text: '세부 분류' }), ' = 대표에서 덱 1~2개만 바꾼 5덱(대표와 J ≥ 0.5, 최선의 97% 이상). 값은 평가기 기본 레이어 180초 딜입니다.');
    if (R.status !== 'done') {
      return card('classes', `큰 분류 · ${BOSS_LABEL[state.boss]}`, sub,
        h('div', { class: 'empty', text: Object.keys(S.parts || {}).length ? '실행 중 — 끝나면 채워집니다.' : '계산 전 — 실험 30 판정 뒤 실행합니다.' }));
    }
    const show = D.show.classes;
    const head = h('p', { class: 'small muted' }, `최선(A) ${eok(R.best)} · 큰 분류 ${R.classes.length}개(최선의 95% 이상) 중 97% 이상 ${R.n97}개 · 기록 구성 ${int(R.comps)}개`,
      R.map_exact ? '' : ' · 고르기 제한 시간에 걸린 대표가 있어 정확해가 아닐 수 있음');
    const boxes = R.classes.slice(0, show).map((c, i) => classBox(S, R, c, i === 0));
    const rest = R.classes.slice(show);
    const more = rest.length ? lazyDetails('more', h('summary', { text: `더보기 — 큰 분류 ${rest.length}개 더` }), () => rest.map((c) => classBox(S, R, c, false))) : null;
    return card('classes', `큰 분류 · ${BOSS_LABEL[state.boss]}`, sub, head, boxes, more);
  }
  const subsCount = (c) => (c.capped ? `${int(c.subs_count)}개 이상` : `${int(c.subs_count)}개`);
  function classBox(S, R, c, open) {
    const vs = Object.entries(c.vs || {}).slice(0, 4).map(([o, v]) => h('span', { class: 'cls-j' }, badge(o, true), ` J ${jf(v.J)} · ${v.moves}명`));
    const jt = (R.metrics.J_top || {})[c.name];
    const sum = h('summary', { class: 'cls-sum' },
      badge(c.name),
      h('span', { class: 'cls-ratio', text: pct(c.ratio) }),
      h('span', { class: 'cls-total', text: eok(c.total) }),
      h('span', { class: 'cls-vs' }, vs),
      jt != null ? h('span', { class: 'cls-note', text: `랭커 대표와 J ${jf(jt)}` }) : null,
      h('span', { class: 'cls-subs', text: `세부 분류 ${subsCount(c)}` }));
    return lazyDetails('cls', sum, () => classInner(S, R, c), open);
  }
  function classInner(S, R, c) {
    const show = D.show.subs;
    const subs = c.subs || [];
    const repSet = new Set(c.decks.flatMap((d) => d.order));
    const newSet = new Set(S.new);
    const out = [h('div', { class: 'rep-grid' }, fiveGrid({ total: c.total, decks: c.decks }, {
      title: `대표 5덱`, badge: c.name, size: 'lg', ours: c.name === 'A', newSet,
      note: `최선 대비 ${pct(c.ratio)}${c.exact === false ? ' · 고르기 제한 시간에 걸림' : ''}`,
    }))];
    out.push(h('h4', { class: 'subs-h' }, `세부 분류 ${subsCount(c)}`,
      c.subs_count ? h('span', { class: 'muted small', text: ` · 덱 하나만 바뀐 것 ${int(c.subs_1deck)}개` }) : null));
    if (!subs.length) {
      out.push(h('p', { class: 'small muted', text: '최선의 97% 이상이면서 이 대표에서 덱 1~2개만 바꾼 5덱이 기록에 없습니다.' }));
      return out;
    }
    out.push(h('p', { class: 'small muted face-key', text: '줄을 누르면 5덱이 펼쳐집니다. 칠한 줄 = 바뀐 덱 · 점선 테두리 = 대표에 없던 니케 · 오른쪽 J = 이 대표 · 다른 큰 분류와의 J.' }));
    out.push(h('div', { class: 'subs' }, subs.slice(0, show).map((s, i) => subItem(R, c, s, i + 1, repSet))));
    const more = subs.slice(show);
    if (more.length) {
      out.push(lazyDetails('more', h('summary', { text: `더보기 — ${more.length}개 더 (합 순)` }), () => [
        h('div', { class: 'subs' }, more.map((s, i) => subItem(R, c, s, show + i + 1, repSet))),
        c.more_left ? h('p', { class: 'small muted more-left', text: `외 ${int(c.more_left)}개${c.capped ? ' 이상(400개에서 자름)' : ''}` }) : null]));
    } else if (c.more_left) {
      out.push(h('p', { class: 'small muted', text: `외 ${int(c.more_left)}개` }));
    }
    return out;
  }
  // 세부 분류 한 줄: 바뀐 덱 · 빠짐 → 들어옴(덱 사이 옮김) · 최선 대비 · J. 펴면 5덱 격자
  function subItem(R, c, s, rank, repSet) {
    const change = [];
    if (s.out.length || s.in.length) {
      change.push(h('span', { class: 'swap' }, faces(s.out, 'sm'), h('span', { class: 'arrow', 'aria-label': '대신', text: '→' }), faces(s.in, 'sm')));
    }
    const inSet = new Set(s.in);
    const mv = (s.moved || []).filter(([n]) => !inSet.has(n));
    if (mv.length) {
      change.push(h('span', { class: 'moved' }, mv.map(([n, a, b]) => h('span', { class: 'mv' }, face(n, 'sm'),
        h('span', { class: 'mv-d', 'aria-label': `${a}덱에서 ${b}덱으로`, text: `${a}→${b}` })))));
    }
    const other = Object.entries(s.J_other || {}).filter(([, j]) => j >= 0.2).map(([o, j]) => h('span', { class: 'sj' }, badge(o, true), ` ${jf(j)}`));
    const sum = h('summary', { class: 'sub-sum' },
      h('span', { class: 'sub-no', text: `${rank}` }),
      h('span', { class: 'sub-decks' }, s.changed.map((n) => h('span', { class: 'tag deck-tag', text: `${n}덱` }))),
      h('span', { class: 'sub-change' }, change),
      h('span', { class: 'sub-nums' },
        h('b', { class: 'sub-ratio', text: pct(s.total / R.best) }),
        h('span', { class: 'sj' }, badge(c.name, true), ` ${jf(s.J)}`),
        other));
    return lazyDetails('sub-item', sum, () => {
      const decks = c.decks.map((x) => ({ order: x.order, value: x.value }));
      for (const sl of s.slots) decks[sl.no - 1] = { order: sl.order, value: sl.value };
      return [fiveGrid({ total: s.total, decks }, {
        title: `${c.name} 세부 분류 ${rank}`, size: 'md', hl: new Set(s.changed), otherSet: repSet,
        note: `최선 대비 ${pct(s.total / R.best)} · 대표 ${c.name}와 J ${jf(s.J)} · 옮기거나 바꿀 니케 ${s.moves}명`,
      })];
    });
  }

  // 랭커: 대표 5덱 · 1위 5덱 격자(값은 같은 보스 조건으로 우리가 시뮬) + 지표 + 사용 상위 25
  function rankerCard(S, R) {
    const K = S.rankers;
    const A = R.status === 'done' && R.classes.length ? R.classes[0] : null;
    const aSet = A ? new Set(A.decks.flatMap((d) => d.order)) : null;
    const M = R.metrics || {};
    const jline = (jm) => (jm ? h('div', { class: 'jline small' }, '큰 분류와 J: ', Object.entries(jm).map(([o, j], i) => [i ? ' · ' : '', badge(o, true), ` ${jf(j)}`])) : null);
    const ratio = (set) => (A && set.total != null ? ` · 우리 A 대비 ${pct(set.total / A.total)}` : '');
    const sets = R.ranker_sets;
    const grids = h('div', { class: 'sets cmp' },
      h('div', null, fiveGrid(sets.top_five, { title: '랭커 대표 5덱', size: 'lg', otherSet: aSet,
        note: `300명 중 ${K.top_five_count}명이 5덱을 그대로 씀${ratio(sets.top_five)}${K.evaluated ? '' : ' · 값은 평가 전'}` }), jline(M.J_top)),
      h('div', null, fiveGrid(sets.rank1, { title: '랭커 1위 5덱', size: 'lg', otherSet: aSet,
        note: `${K.rank1_server} 서버 · 실전 ${eok(K.rank1_damage / 1e8)}${ratio(sets.rank1)}${K.evaluated ? '' : ' · 값은 평가 전'}` }), jline(M.J_r1)));
    const tiles = A ? h('div', { class: 'tiles' },
      tile('N25', `${M.N25}`, '우리 A 25명 중 랭커 사용 상위 25명'),
      tile('D4', `${M.D4}`, '우리 A 덱 중 랭커 상위 40 스쿼드와 4명 이상 같은 덱'),
      tile('V_top', pct(M.V_top), '랭커 대표 5덱 ÷ 우리 A'),
      tile('V_r1', pct(M.V_r1), '랭커 1위 5덱 ÷ 우리 A'),
      tile('V_pack', pct(M.V_pack), '랭커 상위 40 스쿼드로 짠 최선 ÷ 우리 A')) : null;
    const top = K.units.map(([n]) => n);
    const usage = h('div', null, h('h4', { text: '랭커 사용 상위 25' }),
      h('p', { class: 'small muted', text: aSet ? '✓ = 우리 A에도 있음. 격자의 점선 테두리 = 우리 A에 없는 니케.' : '우리 쪽은 계산 전입니다.' }),
      faces(top, 'md', { checkSet: aSet }),
      A ? h('div', { class: 'who' },
        h('div', null, h('h4', { text: `우리 A에만(${M.ours_only.length})` }), faces(M.ours_only, 'md')),
        h('div', null, h('h4', { text: `랭커 상위 25에만(${M.rankers_only.length})` }), faces(M.rankers_only, 'md'))) : null);
    const sq = h('details', null, h('summary', { text: `랭커 상위 40 스쿼드(가장 흔한 배치 순서, 서로 다른 스쿼드 ${int(K.distinct_squads)}개 중)` }),
      h('div', { class: 'inner' }, tableWrap(h('table', { class: 'mid' },
        h('thead', null, h('tr', null, ['#', '스쿼드', '쓴 덱 수', BOSS_LABEL[state.boss]].map((t, i) => h('th', { class: i >= 2 ? 'r' : null, text: t })))),
        h('tbody', null, K.squads.map((q, i) => h('tr', null, h('td', { class: 'small muted', text: `${i + 1}` }),
          h('td', null, faces(q.order, 'sm', { checkSet: aSet })), h('td', { class: 'r', text: int(q.count) }),
          h('td', { class: 'r', text: eok(q.values[state.boss]) }))))))));
    return card('rankers', `그 시즌 랭커 · ${BOSS_LABEL[state.boss]}`,
      '랭커 덱의 값은 같은 보스 조건 · 기본 스펙 · 기본 레이어로 우리가 시뮬한 값입니다(랭커의 실전 육성 · 컨트롤과 다릅니다).',
      tiles, grids, usage, sq);
  }

  function costCard(S) {
    const P = S.parts || {};
    const names = { B_s0: 'B 시드 0', B_s1: 'B 시드 1', W: 'W 넓게 찾기', core30: '코어 30(재평가 + 이어 찾기)', members: '덱별 니케 딜' };
    const keys = Object.keys(names).filter((k) => P[k]);
    if (!keys.length) return card('cost', '시뮬 비용', null, h('div', { class: 'empty', text: '계산 전' }));
    return card('cost', '시뮬 비용', `이 시즌 새 시뮬 ${int(S.sims_total)}회(부분별 기록 합)${S.arm ? ` · 판 ${ARM_KO[S.arm]}` : ''}`,
      tableWrap(h('table', { class: 'plain' },
        h('thead', null, h('tr', null, ['부분', '평가', '새 시뮬', '시간'].map((t, i) => h('th', { class: i ? 'r' : null, text: t })))),
        h('tbody', null, keys.map((k) => h('tr', null, h('td', { text: names[k] }), h('td', { class: 'r', text: int(P[k].evals ?? P[k].requests) }),
          h('td', { class: 'r', text: int(P[k].sims) }), h('td', { class: 'r', text: dur(P[k].seconds) })))))));
  }

  // ------------------------------------------------------------ 읽는 법
  function renderAbout(root) {
    root.append(h('section', { id: 'about' }, h('h2', { text: '읽는 법' }), h('div', { class: 'card' },
      h('dl', { class: 'kv' },
        h('dt', { text: '조건' }), h('dd', null, '시즌마다 그 시즌 끝까지 나온 니케 전원 보유 · 기본 스펙(상). 그때 없던 애장품은 0단계(나머지 3단계). 보스 = 평가기 기본 적(방어력 31784, 패턴 · 파츠 없음) + 시즌 보스 속성. 180초 · 기대값 · 버스트 게이지 실누적.'),
        h('dt', { text: '날짜 경계' }), h('dd', null, '출시일 · 애장품 날짜가 날짜만 있으면 그날 점검 뒤로 봅니다. 시즌은 점검 날 04:59에 끝나므로 그날 들어온 니케 · 애장품은 그 시즌에 없습니다.'),
        h('dt', { text: '탐색' }), h('dd', null, '실험 30 절차. B = 시드 2개(예산 12,500씩, 실제 약 11,000에서 끝남) 기록 합치기, W = B 앞 6,250 × 2 + 큰 분류마다 근처를 찾는 넓게 찾기(B와 총평가가 같게). 실험 30 판정으로 고릅니다. 랭커 정보는 쓰지 않습니다.'),
        h('dt', { text: '운용' }), h('dd', null, '평가기 기본 레이어(렐릭 베어 큐브, 니케별 기본 컨트롤) 고정. 큐브 · 컨트롤 후처리는 하지 않았습니다.'),
        h('dt', { text: '코어 30px' }), h('dd', null, '처음부터 따로 찾지 않고, 코어 없음 기록에서 고른 2,000개(큰 분류 대표 덱 + 대표 5덱의 덱 자리마다 바꿔 넣을 구성)를 코어 30으로 다시 평가한 뒤 그 위에서 2,000평가를 이어 찾습니다. 그 값으로 같은 분류를 만듭니다(실험 30 확인: 따로 찾은 최선 대비 S40 99.98% · S34 100.0%).'),
        h('dt', { text: 'J(쌍 자카드)' }), h('dd', null, '두 5덱에서 같은 덱에 묶인 니케 쌍이 얼마나 겹치는지(0~1). 덱 하나 통째 교체 0.67, 1명 교체 0.85, 맞교환 3번 0.35. 바꿀 니케 수 = 한쪽을 다른 쪽으로 만들 때 옮기거나 바꿀 니케 수.'),
        h('dt', { text: '큰 분류' }), h('dd', null, 'A = 기록의 최선 5덱. 다음 = 앞 대표 모두와 J ≤ 0.2인 겹치지 않는 5덱 중 합 최대. 최선의 95% 아래로 내려가면 멈춥니다(최대 10개).'),
        h('dt', { text: '세부 분류' }), h('dd', null, '대표에서 덱 1~2개만 바뀌고(나머지 그대로) 대표와 J ≥ 0.5, 합이 최선의 97% 이상인 5덱. 바뀐 덱이 서로 다른 것부터 3개를 보이고 나머지는 합 순 더보기(20개까지).'),
        h('dt', { text: '그림' }), h('dd', null, '니케 = 얼굴, 오른쪽 위 = 속성, 왼쪽 아래 = 버스트 단계, 오른쪽 아래 N = 직전 시즌 뒤 새 니케. 격자 숫자 = 덱 값, 얼굴 아래 = 니케별 딜.'),
        h('dt', { text: '한계' }), h('dd', null, '시뮬 안의 값입니다. 보스 패턴 · 파츠 · 실제 코어, 그 시점 밸런스 · 랭커 육성은 반영하지 않았습니다. 평가기 데이터 · 스킬은 지금 기준입니다(애장품만 그때로 껐습니다).')))));
  }

  // ------------------------------------------------------------ 시작
  function initialSelection() {
    const m = /^#S(\d+)-(nocore|core30)$/.exec(location.hash);
    if (m) return [Number(m[1]), m[2], true];
    return [D.seasons[D.seasons.length - 1].season, 'nocore', false];
  }
  async function main() {
    renderTheme();
    const app = $('#app');
    try {
      const r = await fetch('data.json', { cache: 'no-cache' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      D = await r.json();
    } catch (e) {
      app.replaceChildren(h('p', { class: 'loading', text: `data.json을 읽지 못했습니다: ${e.message}` }));
      return;
    }
    const [s, b, scroll] = initialSelection();
    state.season = s;
    state.boss = b;
    app.replaceChildren();
    renderSummary(app);
    renderDetailShell(app);
    renderAbout(app);
    renderFoot();
    selectSeason(s, b);
    if (scroll) requestAnimationFrame(() => document.getElementById('detail').scrollIntoView());
  }
  main();
})();
