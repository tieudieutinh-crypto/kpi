/* kpi_personal.js - Trang KPI cá nhân, 3 bước: Mẫu 3 (danh mục), Mẫu 4 (tự chấm), Mẫu 5 (tổng hợp).
 * Bố cục dạng bảng theo hàng, cột của biểu mẫu; nhóm theo trục và nhóm nhiệm vụ, mỗi nhóm có nút thêm nhiệm vụ.
 * Điểm được tính ngay để xem trước; số liệu chính thức luôn do máy chủ tính lại khi lưu (Phụ lục 2). */
(() => {
  'use strict';
  const D = JSON.parse(document.getElementById('kpi-data').textContent);
  const E = D.eval;
  const editPlan = D.editable && D.stage === 'plan';
  const editResult = D.editable && D.stage === 'result';
  const LEAD = !!D.leadership;
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const GROUPS = [['thuong_xuyen', 'I. Nhóm nhiệm vụ thường xuyên'], ['trong_tam', 'II. Nhóm nhiệm vụ trọng tâm, then chốt']];

  // ---------- tiện ích ----------
  const $ = (s, root = document) => root.querySelector(s);
  const make = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const r2 = x => Math.round((x + Number.EPSILON) * 100) / 100;
  const fmt = (x, d = 2) => (x == null || isNaN(x)) ? '—' : Number(x).toLocaleString('vi-VN', { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmtN = x => (x == null || x === '' || isNaN(x)) ? '—' : Number(x).toLocaleString('vi-VN', { maximumFractionDigits: 2 });
  const toNum = v => (v === '' || v == null || isNaN(Number(v))) ? null : Number(v);
  const dmy = iso => iso ? iso.split('-').reverse().join('/') : '';
  const td = (cls, text) => make('td', cls, text);

  // ---------- trạng thái ----------
  let items, axesState, common, selfRating, selfComment, dirty = false;

  function load(src) {
    items = src.items.map(i => ({ ...i }));
    axesState = {};
    src.axes.forEach(a => { axesState[a.axis_id] = { is_main: a.is_main, max_score: a.max_score, goals: a.goals || '', results: a.results || '', note: a.note || '' }; });
    common = {};
    D.criteria.forEach(c => { common[c.id] = { satisfied: null, note: '' }; });
    src.common.forEach(c => { common[c.criterion_id] = { satisfied: c.satisfied, note: c.note || '' }; });
    selfRating = src.self_rating || '';
    selfComment = src.self_comment || '';
    E.plan = src.plan;
  }

  function markDirty() {
    dirty = true;
    const s = $('#bar-state'); if (s) s.textContent = 'Có thay đổi chưa lưu';
  }

  // ---------- tính toán (phản chiếu models.py) ----------
  const coefOf = (cat, code) => (D.coef[cat] && D.coef[cat][code]) || { value: 0, bonus: 0 };

  function computeItem(it) {
    const planned = it.planned_qty || 0, actual = it.actual_qty || 0;
    const ratio = planned > 0 ? r2(actual / planned) : (actual > 0 ? 1 : 0);
    it.kpi_qty = Math.min(ratio, 1);
    it.over_qty = r2(Math.max(ratio - 1, 0));
    const conv = (it.task_score != null) ? r2(it.task_score / 100) : 1;
    it.conversion_coef = conv;
    const q = coefOf('quality', it.quality_code), p = coefOf('progress', it.progress_code), l = coefOf('leadership', it.leadership_code);
    it.quality_value = q.value; it.progress_value = p.value; it.leadership_value = l.value;
    it.qty_conv = r2(it.kpi_qty * conv);
    it.quality_conv = r2(q.value * conv); it.progress_conv = r2(p.value * conv); it.leadership_conv = r2(l.value * conv);
    it.over_quality = it.quality_exceeded ? q.bonus : 0;
    it.over_progress = it.progress_exceeded ? p.bonus : 0;
  }

  function computeAxis(axisId) {
    const rows = items.filter(i => i.axis_id === axisId);
    rows.forEach(computeItem);
    const total = rows.reduce((s, i) => s + (i.conversion_coef || 0), 0);
    const sum = k => r2(rows.reduce((s, i) => s + (i[k] || 0), 0));
    const pct = k => total > 0 ? r2(sum(k) / total * 100) : 0;
    const a = pct('qty_conv'), b = pct('quality_conv'), c = pct('progress_conv'), d = LEAD ? pct('leadership_conv') : 0;
    const parts = LEAD ? [a, b, c, d] : [a, b, c];
    const kpi = r2(parts.reduce((s, x) => s + x, 0) / parts.length);
    const max = (axesState[axisId] && axesState[axisId].max_score) || 0;
    return {
      count: rows.length, total: r2(total), a, b, c, d, kpi, max, score: r2(kpi * max / 100),
      s9: sum('qty_conv'), s11: sum('quality_conv'), s14: sum('progress_conv'), s16: sum('leadership_conv'),
      s17: sum('over_qty'), s18: sum('over_quality'), s19: sum('over_progress'),
    };
  }

  function totals() {
    const commonScore = D.criteria.reduce((s, c) => s + (common[c.id].satisfied ? c.max_score : 0), 0);
    let result = 0, alloc = 0;
    D.axes.forEach(a => {
      const st = axesState[a.id];
      if (st) alloc += st.max_score || 0;
      if (items.some(i => i.axis_id === a.id)) result += computeAxis(a.id).score;
    });
    return { common: r2(commonScore), result: r2(result), total: r2(commonScore + result), alloc: r2(alloc) };
  }

  // ---------- ô nhập trong bảng ----------
  function input(it, f, type, onChange, attrs = {}) {
    let el;
    if (type === 'textarea') { el = make('textarea', 'cell-in'); el.rows = 2; }
    else if (type === 'select') { el = make('select', 'cell-in'); }
    else { el = make('input', 'cell-in'); el.type = type; }
    Object.entries(attrs).forEach(([k, v]) => { if (k !== 'short' && k !== 'cat') el[k] = v; });
    if (type === 'select') {
      el.append(new Option('—', ''));
      Object.entries(D.coef[attrs.cat] || {}).forEach(([code, c]) => {
        const o = new Option(attrs.short ? fmtN(c.value) : `${fmtN(c.value)} · ${c.label}`, code);
        o.title = `${fmtN(c.value)} · ${c.label}${c.description ? ' – ' + c.description : ''}`; el.append(o);
      });
    }
    if (type === 'checkbox') el.checked = !!it[f];
    else el.value = it[f] == null ? '' : it[f];
    el.dataset.f = f;
    if (type === 'select') { const tip = () => { const o = el.selectedOptions[0]; el.title = o && o.value ? o.title : ''; }; tip(); el.addEventListener('change', tip); }
    const handler = () => {
      if (type === 'checkbox') it[f] = el.checked;
      else if (type === 'number') it[f] = toNum(el.value);
      else if (type === 'select') it[f] = el.value === '' ? null : Number(el.value);
      else it[f] = el.value;
      markDirty(); onChange();
    };
    el.addEventListener(type === 'select' || type === 'checkbox' || type === 'date' ? 'change' : 'input', handler);
    return el;
  }

  function newItem(axisId, key, ind) {
    return {
      id: null, axis_id: axisId, task_group: key, indicator_id: ind ? ind.id : null, from_plan: false,
      task: ind ? ind.content : '', product: ind ? ind.product : '', difficulty: ind ? ind.difficulty : '',
      planned_qty: ind && ind.quarter_target ? ind.quarter_target : 1,
      deadline_text: ind ? ind.deadline_text : '', deadline_date: ind ? ind.deadline_date : '',
      task_score: D.limits.task_std, note: '', actual_qty: null, actual_date: '',
      quality_code: null, progress_code: null, leadership_code: null,
      quality_exceeded: false, progress_exceeded: false, result_note: '',
    };
  }

  function addRow(tbody, cols, axisId, key, rerender) {
    const tr = make('tr', 'add-row'); const outer = td(); outer.colSpan = cols;
    const cell = make('span', 'sticky-label'); outer.append(cell);
    const add = make('button', 'small secondary', '+ Thêm nhiệm vụ'); add.type = 'button';
    add.addEventListener('click', () => { items.push(newItem(axisId, key)); markDirty(); rerender(axisId, key); });
    cell.append(add);
    const used = new Set(items.map(i => i.indicator_id).filter(Boolean));
    const cands = D.indicators.filter(x => x.axis_id === axisId && x.task_group === key && !used.has(x.id));
    if (cands.length) {
      const sel = make('select', 'from-ind'); sel.title = 'Chọn nhanh từ chỉ tiêu KPI tập thể của Ban (Mẫu 1)';
      sel.append(new Option('+ Thêm từ chỉ tiêu của Ban…', ''));
      cands.forEach(x => sel.append(new Option(x.content.length > 70 ? x.content.slice(0, 70) + '…' : x.content, x.id)));
      sel.addEventListener('change', () => {
        const ind = D.indicators.find(x => x.id === Number(sel.value));
        if (ind) { items.push(newItem(axisId, key, ind)); markDirty(); rerender(axisId, key); }
      });
      cell.append(sel);
    }
    tr.append(outer); tbody.append(tr);
  }

  function removeBtn(it, after) {
    const b = make('button', 'small danger icon', '✕'); b.type = 'button'; b.title = 'Xóa nhiệm vụ';
    b.addEventListener('click', () => {
      if (it.task && !confirm('Xóa nhiệm vụ này?')) return;
      items.splice(items.indexOf(it), 1); markDirty(); after();
    });
    return b;
  }

  function headRow(thead, labels) {
    const tr = make('tr');
    labels.forEach(l => {
      const th = make('th');
      if (Array.isArray(l)) { th.append(make('span', 'colno', l[0]), document.createTextNode(' ' + l[1])); if (l[2]) th.className = l[2]; }
      else th.textContent = l;
      tr.append(th);
    });
    thead.append(tr);
  }

  function sectionRow(tbody, cls, text, cols) {
    const tr = make('tr', cls); const c = td(); c.colSpan = cols; c.append(make('span', 'sticky-label', text));
    tr.append(c); tbody.append(tr);
  }

  // =================== BƯỚC 1 · MẪU 3 ===================
  function renderPlan() {
    const box = $('#plan-table'); if (!box) return;
    box.replaceChildren();
    const rows = editPlan ? items : (E.plan || []);
    if (!editPlan && !rows.length) { box.append(make('p', 'muted', 'Chưa có nhiệm vụ nào trong Mẫu 3.')); return; }
    const table = make('table', 'form-table');
    const thead = make('thead');
    const labels = [['(1)', 'STT'], ['(2)', 'Nhiệm vụ / sản phẩm, công việc', 'w-task'], ['(3)', 'Sản phẩm'],
      ['(4)', 'Độ khó, mới, phức tạp; phạm vi tác động'], ['(5)', 'Số lượng'], ['(6)', 'Tiến độ, thời hạn'],
      ['(7)', 'Điểm công việc'], ['(8)', 'Hệ số quy đổi']];
    if (editPlan) labels.push('');
    headRow(thead, labels);
    table.append(thead);
    const cols = labels.length;
    const tbody = make('tbody');
    D.axes.forEach(axis => {
      const axisRows = rows.filter(r => r.axis_id === axis.id);
      if (!editPlan && !axisRows.length) return;
      sectionRow(tbody, 'axis-row', `Trục ${axis.number}. ${axis.name}`, cols);
      GROUPS.forEach(([key, title]) => {
        const gRows = axisRows.filter(r => r.task_group === key);
        if (!editPlan && !gRows.length) return;
        sectionRow(tbody, 'group-row', title, cols);
        gRows.forEach((it, idx) => {
          const tr = make('tr');
          tr.append(td('ctr', String(idx + 1)));
          if (editPlan) {
            const coefCell = td('num');
            const upd = () => { coefCell.textContent = fmt(it.task_score != null ? r2(it.task_score / 100) : null); };
            const cTask = td(); cTask.append(input(it, 'task', 'textarea', () => {}, { maxLength: 2000, placeholder: 'Nội dung nhiệm vụ' }));
            const cProd = td(); cProd.append(input(it, 'product', 'text', () => {}, { maxLength: 300 }));
            const cDiff = td(); cDiff.append(input(it, 'difficulty', 'textarea', () => {}, { maxLength: 1000 }));
            const cQty = td(); cQty.append(input(it, 'planned_qty', 'number', () => {}, { min: 0, step: 'any' }));
            const cDl = td('stack-cell');
            cDl.append(input(it, 'deadline_text', 'text', () => {}, { maxLength: 200, placeholder: 'VD: trước 30/12' }),
              input(it, 'deadline_date', 'date', () => {}));
            const cScore = td(); cScore.append(input(it, 'task_score', 'number', upd, { min: 1, max: D.limits.task_max, step: 'any' }));
            upd();
            const cDel = td('ctr'); cDel.append(removeBtn(it, () => renderPlan()));
            tr.append(cTask, cProd, cDiff, cQty, cDl, cScore, coefCell, cDel);
          } else {
            tr.append(td('', it.task), td('', it.product), td('', it.difficulty), td('num', fmtN(it.planned_qty)),
              td('', [it.deadline_text, dmy(it.deadline_date)].filter(Boolean).join(' · ')),
              td('num', fmtN(it.task_score)), td('num', fmt(it.conversion_coef)));
          }
          tbody.append(tr);
        });
        if (editPlan) addRow(tbody, cols, axis.id, key, () => renderPlan());
      });
    });
    table.append(tbody);
    box.append(table);
    if (editPlan) refreshTotals();
  }

  // =================== BƯỚC 2 · MẪU 4 ===================
  // Bố cục theo Mẫu 4 (Hướng dẫn 07): 19 cột, tiêu đề 3 tầng, dòng TỔNG.
  function th(text, cls, rs, cs) {
    const e = make('th', cls || '', text);
    if (rs) e.rowSpan = rs; if (cs) e.colSpan = cs;
    return e;
  }

  function renderResult() {
    const box = $('#result-table'); if (!box) return;
    box.replaceChildren();
    if (!editResult && !items.length) { box.append(make('p', 'muted', 'Chưa có nhiệm vụ nào.')); return; }
    const table = make('table', 'form-table result m4');
    // Tỉ lệ độ rộng 19 cột (+ cột xóa) để bảng vừa khung nội dung
    const widths = [2.4, 13.4, 6.3, 4, 7.6, 4.4, 4.6, 3.8, 3.8, 6.2, 3.8, 7.8, 6.2, 3.8, 5.6, 3.8, 3.4, 3.4, 3.4];
    const cg = make('colgroup');
    widths.forEach(w => { const c = make('col'); c.style.width = w + '%'; cg.append(c); });
    if (editResult) { const c = make('col'); c.style.width = '2.4%'; cg.append(c); }
    table.append(cg);
    const thead = make('thead');
    const r1 = make('tr'), r2 = make('tr'), r3 = make('tr'), r4 = make('tr', 'colnos');
    r1.append(th('TT', 'stk1', 3), th('NHIỆM VỤ ĐỀ RA KẾ HOẠCH', 'grp', 1, 5), th('THỰC TẾ TRIỂN KHAI', 'grp', 1, 10),
      th('Hệ số KPI vượt', 'grp', 2, 3));
    if (editResult) r1.append(th('', '', 4));
    r2.append(th('Nhiệm vụ', 'stk2 w-task', 2), th('Sản phẩm', '', 2), th('Số lượng', '', 2), th('Tiến độ', '', 2),
      th('Hệ số quy đổi', '', 2), th('KPI (Số lượng)', 'grp', 1, 3), th('KPI (Chất lượng)', 'grp', 1, 2),
      th('KPI (Tiến độ)', 'grp', 1, 3), th('Lãnh đạo, chỉ đạo, điều hành', 'grp' + (LEAD ? '' : ' na'), 1, 2));
    ['Số lượng thực tế hoàn thành', 'Hệ số KPI', 'Quy đổi', 'Hệ số KPI', 'Quy đổi', 'Thời điểm thực tế hoàn thành',
      'Hệ số KPI', 'Quy đổi'].forEach(t => r3.append(th(t)));
    r3.append(th('Hệ số KPI', LEAD ? '' : 'na'), th('Quy đổi', LEAD ? '' : 'na'),
      th('KPI (SL)'), th('KPI (CL)'), th('KPI (TĐ)'));
    [...r3.children].slice(-3).forEach((c, i) => { c.title = ['KPI (Số lượng)', 'KPI (Chất lượng)', 'KPI (Tiến độ)'][i]; });
    for (let i = 1; i <= 19; i++) r4.append(th(`(${i})`, i === 1 ? 'stk1' : (i === 2 ? 'stk2' : '')));
    thead.append(r1, r2, r3, r4);
    table.append(thead);
    const cols = 19 + (editResult ? 1 : 0);
    const tbody = make('tbody');
    let no = 0;
    D.axes.forEach(axis => {
      const axisRows = items.filter(r => r.axis_id === axis.id);
      if (!editResult && !axisRows.length) return;
      sectionRow(tbody, 'axis-row', `Trục ${axis.number}. ${axis.name}`, cols);
      GROUPS.forEach(([key, title]) => {
        const gRows = axisRows.filter(r => r.task_group === key);
        if (!editResult && !gRows.length) return;
        sectionRow(tbody, 'group-row', title, cols);
        gRows.forEach(it => tbody.append(resultRow(it, ++no, axis.id)));
        if (editResult) addRow(tbody, cols, axis.id, key, () => renderResult());
      });
      if (axisRows.length) {
        const sr = make('tr', 'sum-row'); sr.dataset.axisSum = axis.id;
        tbody.append(sr); fillSumRow(sr, items.filter(i => i.axis_id === axis.id), `Cộng trục ${axis.number}`, computeAxis(axis.id));
      }
    });
    const total = make('tr', 'sum-row total-row'); total.id = 'm4-total';
    tbody.append(total); fillSumRow(total, items, 'TỔNG');
    table.append(tbody);
    box.append(table);
  }

  /** Ô ngày gọn dạng dd/mm/yyyy (lưu ISO yyyy-mm-dd). */
  function dateInput(it, f, refresh) {
    const el = make('input', 'cell-in date-text'); el.type = 'text'; el.placeholder = 'dd/mm/yyyy'; el.maxLength = 10;
    el.inputMode = 'numeric'; el.value = dmy(it[f]); el.title = 'Ngày dạng dd/mm/yyyy';
    el.addEventListener('change', () => {
      const v = el.value.trim();
      const m = v.match(/^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})$/);
      if (!v) { it[f] = ''; el.classList.remove('invalid'); }
      else if (m) {
        const iso = `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`;
        const d = new Date(iso + 'T00:00:00');
        if (isNaN(d) || d.getDate() !== Number(m[1])) { el.classList.add('invalid'); return; }
        it[f] = iso; el.value = dmy(iso); el.classList.remove('invalid');
      } else { el.classList.add('invalid'); return; }
      markDirty(); refresh();
    });
    return el;
  }

  function coefInput(it, refresh) {
    const el = make('input', 'cell-in short'); el.type = 'number'; el.min = 0.01; el.max = D.limits.task_max / 100; el.step = 0.01; el.inputMode = 'decimal';
    el.title = 'Hệ số quy đổi = điểm công việc / 100 (công việc chuẩn = 1, tối đa 2)';
    el.value = it.task_score != null ? r2(it.task_score / 100) : '';
    el.addEventListener('input', () => { const v = toNum(el.value); it.task_score = v == null ? null : r2(v * 100); markDirty(); refresh(); });
    return el;
  }

  function resultRow(it, no, axisId) {
    const tr = make('tr'); tr.dataset.row = '';
    const editableNew = editResult && !it.from_plan;
    const refresh = () => {
      computeItem(it); fillComputed(tr, it);
      const s = $(`tr[data-axis-sum="${axisId}"]`); if (s) fillSumRow(s, items.filter(i => i.axis_id === axisId), `Cộng trục ${(D.axes.find(a => a.id === axisId) || {}).number}`, computeAxis(axisId));
      const t = $('#m4-total'); if (t) fillSumRow(t, items, 'TỔNG');
      refreshTotals();
    };
    const o = k => { const c = td('num out'); c.dataset.o = k; return c; };
    const c1 = td('ctr', String(no));
    const c2 = td();
    if (editableNew) c2.append(input(it, 'task', 'textarea', refresh, { maxLength: 2000, placeholder: 'Nhiệm vụ mới' }));
    else { c2.append(document.createTextNode(it.task || '')); if (it.from_plan) c2.append(' ', make('span', 'tag', 'Mẫu 3')); }
    const c3 = td(); if (editableNew) c3.append(input(it, 'product', 'text', refresh, { maxLength: 300 })); else c3.textContent = it.product || '';
    const c4 = td('num'); if (editableNew) c4.append(input(it, 'planned_qty', 'number', refresh, { min: 0, step: 'any' })); else c4.textContent = fmtN(it.planned_qty);
    const c5 = td('stack-cell');
    if (editableNew) c5.append(input(it, 'deadline_text', 'text', refresh, { maxLength: 200, placeholder: 'Diễn giải' }), dateInput(it, 'deadline_date', refresh));
    else c5.textContent = [it.deadline_text, dmy(it.deadline_date)].filter(Boolean).join(' · ');
    const c6 = td('num'); if (editResult) c6.append(coefInput(it, refresh)); else { c6.dataset.o = 'coef'; }
    const c7 = td('num'); if (editResult) c7.append(input(it, 'actual_qty', 'number', refresh, { min: 0, step: 'any', inputMode: 'decimal' })); else c7.textContent = fmtN(it.actual_qty);
    const c10 = td('stack-cell');
    if (editResult) {
      c10.append(input(it, 'quality_code', 'select', refresh, { cat: 'quality', short: true }));
      const l = make('label', 'mini-check'); l.title = 'Chất lượng nổi trội, được công nhận'; l.append(input(it, 'quality_exceeded', 'checkbox', refresh), document.createTextNode(' nổi trội')); c10.append(l);
    } else c10.textContent = it.quality_code ? fmtN(coefOf('quality', it.quality_code).value) : '—';
    const c12 = td(); if (editResult) c12.append(dateInput(it, 'actual_date', refresh)); else c12.textContent = dmy(it.actual_date);
    const c13 = td('stack-cell');
    if (editResult) {
      c13.append(input(it, 'progress_code', 'select', refresh, { cat: 'progress', short: true }));
      const l = make('label', 'mini-check'); l.title = 'Vượt tiến độ, được công nhận'; l.append(input(it, 'progress_exceeded', 'checkbox', refresh), document.createTextNode(' vượt TĐ')); c13.append(l);
    } else c13.textContent = it.progress_code ? fmtN(coefOf('progress', it.progress_code).value) : '—';
    const c15 = td(LEAD ? '' : 'na ctr');
    if (!LEAD) c15.textContent = '—';
    else if (editResult) c15.append(input(it, 'leadership_code', 'select', refresh, { cat: 'leadership', short: true }));
    else c15.textContent = it.leadership_code ? fmtN(coefOf('leadership', it.leadership_code).value) : '—';
    const c16 = LEAD ? o('leadership_conv') : td('na ctr', '—');
    tr.append(c1, c2, c3, c4, c5, c6, c7, o('kpi_qty'), o('qty_conv'), c10, o('quality_conv'), c12, c13, o('progress_conv'),
      c15, c16, o('over_qty'), o('over_quality'), o('over_progress'));
    if (editResult) { const cDel = td('ctr'); if (!it.from_plan) cDel.append(removeBtn(it, () => { renderResult(); refreshTotals(); })); tr.append(cDel); }
    computeItem(it); fillComputed(tr, it);
    return tr;
  }

  function fillComputed(tr, it) {
    const set = (k, v) => { const c = tr.querySelector(`[data-o="${k}"]`); if (c) c.textContent = v; };
    set('coef', fmt(it.conversion_coef)); set('kpi_qty', fmt(it.kpi_qty)); set('qty_conv', fmt(it.qty_conv));
    set('quality_conv', fmt(it.quality_conv)); set('progress_conv', fmt(it.progress_conv)); set('leadership_conv', fmt(it.leadership_conv));
    set('over_qty', it.over_qty > 0 ? fmt(it.over_qty) : '');
    set('over_quality', it.over_quality > 0 ? fmt(it.over_quality) : '');
    set('over_progress', it.over_progress > 0 ? fmt(it.over_progress) : '');
    const late = it.actual_date && it.deadline_date && it.actual_date > it.deadline_date;
    tr.classList.toggle('late', !!late);
  }

  /** Dòng cộng (theo trục hoặc TỔNG): cộng cột (6), (9), (11), (14), (16), (17), (18), (19). */
  function fillSumRow(tr, rows, label, axis) {
    rows.forEach(computeItem);
    const sum = k => r2(rows.reduce((s, i) => s + (i[k] || 0), 0));
    tr.replaceChildren();
    const lab = td(); lab.colSpan = 5;
    const text = axis ? `${label} · KPI ${fmt(axis.kpi)}% (A ${fmt(axis.a)} · B ${fmt(axis.b)} · C ${fmt(axis.c)}${LEAD ? ` · D ${fmt(axis.d)}` : ''})` : label;
    lab.append(make('span', 'sticky-label', text));
    tr.append(lab, td('num', fmt(sum('conversion_coef'))), td(), td(), td('num', fmt(sum('qty_conv'))), td(),
      td('num', fmt(sum('quality_conv'))), td(), td(), td('num', fmt(sum('progress_conv'))), td(LEAD ? '' : 'na'),
      td('num' + (LEAD ? '' : ' na'), LEAD ? fmt(sum('leadership_conv')) : '—'),
      td('num', fmt(sum('over_qty'))), td('num', fmt(sum('over_quality'))), td('num', fmt(sum('over_progress'))));
    if (editResult) tr.append(td());
  }

  // =================== BƯỚC 3 · MẪU 5 ===================
  // A. Nhóm tiêu chí chung: TT | Tiêu chí | Đảm bảo | Không đảm bảo | Điểm tối đa | Điểm đạt | Ghi chú
  function renderCommon() {
    const box = $('#common-body'); if (!box) return;
    box.replaceChildren();
    const table = make('table', 'form-table m5a');
    const thead = make('thead'); const hr = make('tr'), nr = make('tr', 'colnos');
    ['TT', 'Tiêu chí / Nội dung', 'Đảm bảo (đánh dấu x)', 'Không đảm bảo (đánh dấu x)', 'Điểm tối đa',
      'Điểm đạt (chấm tối đa nếu đảm bảo; 0 điểm nếu không đảm bảo)', 'Ghi chú']
      .forEach((h, i) => hr.append(th(h, i === 1 ? 'w-task' : '')));
    for (let i = 1; i <= 7; i++) nr.append(th(`(${i})`));
    thead.append(hr, nr); table.append(thead);
    const tb = make('tbody');
    let lastGroup = null;
    D.criteria.forEach(c => {
      if (c.group_no !== lastGroup) {
        lastGroup = c.group_no;
        const members = D.criteria.filter(x => x.group_no === c.group_no);
        const gr = make('tr', 'crit-group'); gr.dataset.group = c.group_no;
        gr.append(td('ctr', String(c.group_no)), td('', c.group_title), td(), td(),
          td('num', fmt(members.reduce((s, x) => s + x.max_score, 0), 0)), td('num gsum', ''), td());
        tb.append(gr);
      }
      const tr = make('tr'); tr.dataset.cid = c.id;
      tr.append(td('ctr', c.code), td('', c.title));
      [true, false].forEach(val => {
        const cell = td('ctr'); const r = make('input'); r.type = 'radio'; r.name = 'c' + c.id;
        r.title = val ? 'Đảm bảo' : 'Không đảm bảo';
        r.checked = common[c.id].satisfied === val; r.disabled = !editResult;
        r.addEventListener('change', () => { common[c.id].satisfied = val; markDirty(); refreshCommonRow(tr, c); refreshTotals(); });
        cell.append(r); tr.append(cell);
      });
      tr.append(td('num', fmt(c.max_score, 0)), td('num score', ''));
      const note = td();
      if (editResult) {
        const n = make('input', 'cell-in'); n.maxLength = 500; n.value = common[c.id].note || '';
        n.addEventListener('input', () => { common[c.id].note = n.value; markDirty(); });
        note.append(n);
      } else note.textContent = common[c.id].note || '';
      tr.append(note);
      refreshCommonRow(tr, c);
      tb.append(tr);
    });
    const total = make('tr', 'sum-row'); total.id = 'm5a-total';
    tb.append(total);
    table.append(tb); box.append(table);
  }

  function refreshCommonRow(tr, c) {
    const s = common[c.id].satisfied;
    $('.score', tr).textContent = s == null ? '—' : fmt(s ? c.max_score : 0, 0);
    tr.classList.toggle('unanswered', s == null);
    const g = document.querySelector(`tr.crit-group[data-group="${c.group_no}"] .gsum`);
    if (g) g.textContent = fmt(D.criteria.filter(x => x.group_no === c.group_no)
      .reduce((sum, x) => sum + (common[x.id].satisfied ? x.max_score : 0), 0), 0);
  }

  // B. Kết quả thực hiện nhiệm vụ được giao: TT | Tiêu chí / Nội dung | Mục tiêu, nhiệm vụ đề ra |
  //    Kết quả sản phẩm thực tế | Điểm KPI (%) | Điểm tối đa | Điểm đạt | Ghi chú
  function autoGoals(axisId) {
    return items.filter(i => i.axis_id === axisId).map(i =>
      `- ${i.task}${i.product ? ` (${i.product})` : ''}: ${fmtN(i.planned_qty)}`).join('\n');
  }
  function autoResults(axisId) {
    return items.filter(i => i.axis_id === axisId).map(i =>
      `- ${i.task}: ${i.actual_qty == null ? '…' : fmtN(i.actual_qty)}/${fmtN(i.planned_qty)}${i.result_note ? ` – ${i.result_note}` : ''}`).join('\n');
  }

  function renderAxisSummary() {
    const box = $('#axis-summary'); if (!box) return;
    box.replaceChildren();
    const used = D.axes.filter(a => items.some(i => i.axis_id === a.id) || (axesState[a.id] && axesState[a.id].max_score > 0));
    if (!used.length) { box.append(make('p', 'muted', 'Chưa có nhiệm vụ nào ở Mẫu 4.')); return; }
    const table = make('table', 'form-table m5b');
    const thead = make('thead'); const hr = make('tr'), nr = make('tr', 'colnos');
    ['TT', 'Tiêu chí / Nội dung', 'Mục tiêu, nhiệm vụ đề ra', 'Kết quả sản phẩm thực tế', 'Điểm KPI (%)', 'Điểm tối đa',
      'Điểm đạt (= Điểm KPI × Điểm tối đa) / 100', 'Ghi chú'].forEach((h, i) => hr.append(th(h, i === 1 ? '' : (i === 2 || i === 3 ? 'w-task' : ''))));
    for (let i = 1; i <= 8; i++) nr.append(th(`(${i})`));
    thead.append(hr, nr); table.append(thead);
    const tb = make('tbody');
    used.forEach((axis, idx) => {
      const tr = make('tr');
      const st = axesState[axis.id] = axesState[axis.id] || { is_main: false, max_score: 0, goals: '', results: '', note: '' };
      if (!st.goals) st.goals = autoGoals(axis.id);
      if (!st.results) st.results = autoResults(axis.id);
      const area = (f, rows) => {
        const c = td();
        if (editResult) {
          const t = make('textarea', 'cell-in'); t.rows = rows; t.maxLength = 5000; t.value = st[f] || '';
          t.addEventListener('input', () => { st[f] = t.value; markDirty(); }); c.append(t);
        } else c.append(make('div', 'pre', st[f] || ''));
        return c;
      };
      const kpiCell = td('num'), outs = td('num');
      const max = make('input', 'cell-in short'); max.type = 'number'; max.min = 0; max.max = D.limits.result_max; max.step = 'any';
      max.value = st.max_score || ''; max.disabled = !editResult;
      const fill = () => {
        const r = computeAxis(axis.id);
        kpiCell.textContent = fmt(r.kpi);
        kpiCell.title = `A ${fmt(r.a)}% · B ${fmt(r.b)}% · C ${fmt(r.c)}%${LEAD ? ` · D ${fmt(r.d)}%` : ''}`;
        outs.textContent = fmt(r.score);
      };
      max.addEventListener('input', () => { st.max_score = toNum(max.value) || 0; markDirty(); fill(); refreshTotals(); });
      const cMax = td('num'); cMax.append(max);
      const note = td();
      if (editResult) {
        const n = make('input', 'cell-in'); n.maxLength = 1000; n.value = st.note || '';
        n.addEventListener('input', () => { st.note = n.value; markDirty(); }); note.append(n);
      } else note.textContent = st.note || '';
      tr.append(td('ctr', String(idx + 1)), td('', `Trục ${axis.number}. ${axis.name}`), area('goals', 4), area('results', 4),
        kpiCell, cMax, outs, note);
      fill();
      tb.append(tr);
    });
    const tB = make('tr', 'sum-row'); tB.id = 'm5b-total';
    const tAB = make('tr', 'sum-row total-row'); tAB.id = 'm5ab-total';
    tb.append(tB, tAB);
    table.append(tb); box.append(table);
  }

  // ---------- tổng hợp ----------
  function refreshTotals() {
    const t = totals();
    const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v; };
    set('common-total', `${fmt(t.common)} / 30`); set('result-total', `${fmt(t.result)} / 70`);
    set('t-common', fmt(t.common)); set('t-result', fmt(t.result)); set('t-total', fmt(t.total));
    const al = $('#alloc');
    if (al) { al.textContent = `Đã phân bổ ${fmt(t.alloc)} / 70 điểm`; al.className = 'meter ' + (Math.abs(t.alloc - 70) < 0.005 ? 'ok' : (t.alloc > 70 ? 'bad' : 'warn')); }
    const sumRow = (id, label, max, got) => {
      const row = document.getElementById(id); if (!row) return;
      row.replaceChildren();
      const c = td('', label); c.colSpan = id === 'm5a-total' ? 4 : 5;
      row.append(c, td('num', fmt(max, 0)), td('num', fmt(got)));
      row.append(td());
    };
    sumRow('m5a-total', 'Tổng (A) =', 30, t.common);
    sumRow('m5b-total', 'TỔNG (B) =', t.alloc, t.result);
    sumRow('m5ab-total', 'TỔNG (A + B) =', 30 + t.alloc, t.total);
    const bar = $('#bar-total');
    if (bar) bar.textContent = D.stage === 'result' ? `A ${fmt(t.common)} + B ${fmt(t.result)} = ${fmt(t.total)} điểm` : `${items.length} nhiệm vụ trong Mẫu 3`;
  }

  function showList(box, title, list) {
    box.replaceChildren();
    if (!list || !list.length) { box.hidden = true; return; }
    box.append(make('b', '', title));
    const ul = make('ul'); list.forEach(w => ul.append(make('li', '', w))); box.append(ul); box.hidden = false;
  }
  const showWarnings = list => showList($('#warnings'), 'Lưu ý khi chấm điểm (chưa chặn trình):', D.stage === 'result' ? list : []);
  function showErrors(list) {
    const box = $('#save-errors'); showList(box, 'Chưa lưu được:', list);
    if (list && list.length) box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  // ---------- lưu ----------
  function buildPayload() {
    const used = new Set(items.map(i => i.axis_id));
    return {
      self_rating: selfRating, self_comment: selfComment,
      axes: D.axes.filter(a => used.has(a.id) || (axesState[a.id] && axesState[a.id].max_score > 0))
        .map(a => { const st = axesState[a.id] || {}; return { axis_id: a.id, is_main: !!st.is_main, max_score: st.max_score || 0,
          goals: st.goals || '', results: st.results || '', note: st.note || '' }; }),
      common: D.criteria.map(c => ({ criterion_id: c.id, satisfied: common[c.id].satisfied, note: common[c.id].note })),
      items: items.map(i => ({
        id: i.id, axis_id: i.axis_id, task_group: i.task_group, indicator_id: i.indicator_id, task: i.task,
        product: i.product, difficulty: i.difficulty, planned_qty: i.planned_qty, deadline_text: i.deadline_text,
        deadline_date: i.deadline_date, task_score: i.task_score, note: i.note, actual_qty: i.actual_qty,
        actual_date: i.actual_date, quality_code: i.quality_code, progress_code: i.progress_code,
        leadership_code: LEAD ? i.leadership_code : null, quality_exceeded: i.quality_exceeded,
        progress_exceeded: i.progress_exceeded, result_note: i.result_note,
      })),
    };
  }

  async function save() {
    const btns = document.querySelectorAll('.savebar button'); btns.forEach(b => b.disabled = true);
    $('#bar-state').textContent = 'Đang lưu…';
    try {
      const res = await fetch(D.saveUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(buildPayload()),
      });
      let body = null; try { body = await res.json(); } catch (_) { /* không phải JSON */ }
      if (!res.ok || !body || !body.ok) {
        showErrors((body && body.errors) || [res.status === 400 ? 'Phiên làm việc đã hết hạn, hãy tải lại trang.' : 'Không lưu được, vui lòng thử lại.']);
        $('#bar-state').textContent = 'Lưu thất bại';
        return false;
      }
      showErrors(null); load(body.data); renderAll(); showWarnings(body.data.warnings);
      dirty = false; $('#bar-state').textContent = 'Đã lưu ' + new Date().toLocaleTimeString('vi-VN');
      return true;
    } catch (_) {
      showErrors(['Mất kết nối tới máy chủ, vui lòng thử lại.']); $('#bar-state').textContent = 'Lưu thất bại'; return false;
    } finally { btns.forEach(b => b.disabled = false); }
  }

  function renderAll() {
    renderPlan(); renderResult(); renderCommon(); renderAxisSummary();
    const sr = $('#self-rating'), sc = $('#self-comment');
    if (sr) sr.value = selfRating; if (sc) sc.value = selfComment;
    refreshTotals();
  }

  // ---------- chuyển bước ----------
  function showStep(n) {
    document.querySelectorAll('.step-panel').forEach(p => { p.hidden = p.dataset.panel !== String(n); });
    document.querySelectorAll('#stepper .step').forEach(s => s.classList.toggle('active', s.dataset.step === String(n)));
  }
  const defaultStep = D.stage === 'result' ? (E.status === 'draft' ? 2 : 3) : 1;
  const fromHash = () => { const m = location.hash.match(/^#step([123])$/); return m ? Number(m[1]) : null; };
  document.querySelectorAll('#stepper .step').forEach(a => a.addEventListener('click', e => {
    e.preventDefault(); history.replaceState(null, '', a.getAttribute('href')); showStep(a.dataset.step);
  }));

  // ---------- khởi tạo ----------
  load(E);
  renderAll();
  showWarnings(E.warnings);
  showStep(fromHash() || defaultStep);

  const sr = $('#self-rating'), sc = $('#self-comment');
  if (sr) { sr.disabled = !editResult; sr.addEventListener('change', () => { selfRating = sr.value; markDirty(); }); }
  if (sc) { sc.disabled = !editResult; sc.addEventListener('input', () => { selfComment = sc.value; markDirty(); }); }

  if (D.editable) {
    const allOk = $('#all-ok');
    if (allOk) allOk.addEventListener('click', () => { D.criteria.forEach(c => common[c.id].satisfied = true); markDirty(); renderCommon(); refreshTotals(); });
    $('#btn-save').addEventListener('click', save);
    const sub = $('#btn-submit');
    if (sub) sub.addEventListener('click', async () => {
      if (!confirm(sub.dataset.confirm)) return;
      if (await save()) { dirty = false; $('#submit-form').submit(); }
    });
    document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(); } });
    window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  }
})();
