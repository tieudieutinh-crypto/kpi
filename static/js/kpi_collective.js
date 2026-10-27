/* kpi_collective.js - Trang KPI tập thể (Mẫu 1 + Mẫu 2). Số liệu chính thức do máy chủ tính khi lưu. */
(() => {
  'use strict';
  const D = JSON.parse(document.getElementById('kpi-data').textContent);
  const editM1 = !!D.editM1, editM2 = !!D.editM2;   // chỉ một giai đoạn được sửa tại một thời điểm
  const editable = editM1;                          // bảng Mẫu 1
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const GROUPS = [['thuong_xuyen', 'Nhóm nhiệm vụ thường xuyên'], ['trong_tam', 'Nhóm nhiệm vụ trọng tâm, then chốt']];

  const $ = (s, root = document) => root.querySelector(s);
  const make = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const r2 = x => Math.round((x + Number.EPSILON) * 100) / 100;
  const fmt = (x, d = 2) => (x == null || isNaN(x)) ? '—' : Number(x).toLocaleString('vi-VN', { minimumFractionDigits: d, maximumFractionDigits: d });
  const toNum = v => (v === '' || v == null || isNaN(Number(v))) ? null : Number(v);

  let rows, otherKey, models, dirty = false;

  function load(src) {
    rows = src.indicators.map(i => ({ ...i }));
    otherKey = src.other_key_tasks || ''; models = src.innovative_models || '';
  }
  function markDirty() { dirty = true; const s = $('#bar-state'); if (s) s.textContent = 'Có thay đổi chưa lưu'; }

  function compute(r) {
    r.pct_quarter = (r.quarter_target > 0 && r.result != null) ? r2(r.result / r.quarter_target * 100) : null;
    r.pct_year = (r.annual_target > 0 && r.result != null) ? r2(r.result / r.annual_target * 100) : null;
    r.on_time = (r.deadline_date && r.actual_date) ? r.actual_date <= r.deadline_date : null;
  }

  function summary() {
    rows.forEach(compute);
    if (!$('#s-total')) return;
    const withRes = rows.filter(r => r.pct_quarter != null);
    const capped = withRes.map(r => Math.min(r.pct_quarter, 100));
    $('#s-total').textContent = rows.length;
    $('#s-result').textContent = withRes.length;
    $('#s-achieved').textContent = withRes.filter(r => r.pct_quarter >= 100).length;
    $('#s-ontime').textContent = withRes.filter(r => r.on_time).length;
    $('#s-avg').textContent = capped.length ? fmt(r2(capped.reduce((s, x) => s + x, 0) / capped.length)) + '%' : '—';
  }

  const td = (cls, text) => make('td', cls, text);
  const fmtN = x => (x == null || x === '' || isNaN(x)) ? '—' : Number(x).toLocaleString('vi-VN', { maximumFractionDigits: 2 });
  const dmy = iso => iso ? iso.split('-').reverse().join('/') : '';
  const GROUP_TITLES = { thuong_xuyen: 'I. Nhóm nhiệm vụ thường xuyên', trong_tam: 'II. Nhóm nhiệm vụ trọng tâm, then chốt' };

  function input(r, f, type, after, attrs = {}) {
    let el;
    if (type === 'textarea') { el = make('textarea', 'cell-in'); el.rows = 2; }
    else if (type === 'leader') { el = make('select', 'cell-in'); el.append(new Option('— Chưa giao —', '')); D.leaders.forEach(l => el.append(new Option(l.name, l.id))); }
    else { el = make('input', 'cell-in'); el.type = type; }
    Object.entries(attrs).forEach(([k, v]) => { el[k] = v; });
    el.value = r[f] == null ? '' : r[f];
    el.addEventListener(type === 'leader' || type === 'date' ? 'change' : 'input', () => {
      if (type === 'number') r[f] = toNum(el.value);
      else if (type === 'leader') r[f] = el.value === '' ? null : Number(el.value);
      else r[f] = el.value;
      markDirty(); compute(r); if (after) after(); summary();
    });
    return el;
  }

  function head(table, labels) {
    const thead = make('thead'), tr = make('tr');
    labels.forEach(([no, l, cls]) => { const th = make('th', cls || ''); if (no) th.append(make('span', 'colno', no)); th.append(document.createTextNode(l)); tr.append(th); });
    thead.append(tr); table.append(thead);
  }
  const section = (tb, cls, text, cols) => { const tr = make('tr', cls); const c = td(); c.colSpan = cols; c.append(make('span', 'sticky-label', text)); tr.append(c); tb.append(tr); };

  // ---------- Mẫu 1: chỉ tiêu, nhiệm vụ ----------
  function renderM1() {
    const box = $('#m1-table'); box.replaceChildren();
    const table = make('table', 'form-table');
    const labels = [['(1)', 'STT'], ['(2)', 'Nội dung, nhiệm vụ, chỉ tiêu', 'w-task'], ['(3)', 'Sản phẩm / ĐVT'],
      ['(4)', 'Chỉ tiêu năm'], ['(5)', 'Chỉ tiêu quý'], ['(6)', 'Độ khó, mới, phức tạp; phạm vi tác động'],
      ['(7)', 'Cơ quan chủ trì'], ['(8)', 'Cơ quan phối hợp'], ['(9)', 'Lãnh đạo trực tiếp phụ trách'], ['(10)', 'Thời gian hoàn thành']];
    if (editable) labels.push(['', '']);
    head(table, labels);
    const cols = labels.length, tb = make('tbody');
    D.axes.forEach(axis => {
      const axisRows = rows.filter(r => r.axis_id === axis.id);
      if (!editable && !axisRows.length) return;
      section(tb, 'axis-row', `Trục ${axis.number}. ${axis.name}`, cols);
      GROUPS.forEach(([key]) => {
        const gRows = axisRows.filter(r => r.task_group === key);
        if (!editable && !gRows.length) return;
        section(tb, 'group-row', GROUP_TITLES[key], cols);
        gRows.forEach((r, i) => {
          const tr = make('tr');
          tr.append(td('ctr', String(i + 1)));
          if (editable) {
            const c = (el, cls) => { const x = td(cls || ''); [].concat(el).forEach(e => x.append(e)); return x; };
            tr.append(c(input(r, 'content', 'textarea', null, { maxLength: 2000 })),
              c([input(r, 'product', 'text', null, { maxLength: 300, placeholder: 'Sản phẩm' }), input(r, 'unit', 'text', null, { maxLength: 50, placeholder: 'ĐVT' })], 'stack-cell'),
              c(input(r, 'annual_target', 'number', null, { min: 0, step: 'any' })), c(input(r, 'quarter_target', 'number', null, { min: 0, step: 'any' })),
              c(input(r, 'difficulty', 'textarea', null, { maxLength: 1000 })),
              c(input(r, 'lead_agency', 'text', null, { maxLength: 255 })), c(input(r, 'support_agency', 'text', null, { maxLength: 255 })),
              c(input(r, 'leader_id', 'leader')),
              c([input(r, 'deadline_text', 'text', null, { maxLength: 200, placeholder: 'Diễn giải' }), input(r, 'deadline_date', 'date')], 'stack-cell'));
            const del = make('button', 'small danger icon', '✕'); del.type = 'button'; del.title = 'Xóa';
            del.addEventListener('click', () => {
              if (r.content && !confirm('Xóa chỉ tiêu này (kể cả kết quả đã nhập)?')) return;
              rows.splice(rows.indexOf(r), 1); markDirty(); render();
            });
            tr.append(c(del, 'ctr'));
          } else {
            const leader = D.leaders.find(l => l.id === r.leader_id);
            tr.append(td('', r.content), td('', [r.product, r.unit].filter(Boolean).join(' · ')), td('num', fmtN(r.annual_target)),
              td('num', fmtN(r.quarter_target)), td('', r.difficulty), td('', r.lead_agency), td('', r.support_agency),
              td('', leader ? leader.name : ''), td('', [r.deadline_text, dmy(r.deadline_date)].filter(Boolean).join(' · ')));
          }
          tb.append(tr);
        });
        if (editable) {
          const tr = make('tr', 'add-row'), cell = td(); cell.colSpan = cols;
          const add = make('button', 'small secondary', '+ Thêm nhiệm vụ'); add.type = 'button';
          add.addEventListener('click', () => addRow(axis.id, key));
          const wrap = make('span', 'sticky-label'); wrap.append(add);
          cell.append(wrap); tr.append(cell); tb.append(tr);
        }
      });
    });
    if (!rows.length && !editable) { box.append(make('p', 'muted', 'Chưa có chỉ tiêu, nhiệm vụ nào.')); return; }
    table.append(tb); box.append(table);
  }

  // ---------- Mẫu 2: kết quả thực hiện (bố cục theo Mẫu 2, Hướng dẫn 07) ----------
  // (1) STT | (2) Trục/Nhóm nhiệm vụ | (3) Chỉ tiêu/Nội dung/Sản phẩm đầu ra | (4) ĐVT | (5) Chỉ tiêu năm |
  // (6) Chỉ tiêu quý | (7) Kết quả quý | (8)=(7)/(6)*100 | (9)=(7)/(5)*100 | (10) Thời gian theo quy định | (11) Thực tế
  function renderM2() {
    const box = $('#m2-table'); if (!box) return; box.replaceChildren();
    if (!rows.length) { box.append(make('p', 'muted', 'Mẫu 1 chưa có chỉ tiêu nào.')); return; }
    const table = make('table', 'form-table m2');
    const thead = make('thead'), hr = make('tr'), nr = make('tr', 'colnos');
    ['STT', 'Trục/Nhóm nhiệm vụ', 'Chỉ tiêu/Nội dung nhiệm vụ/Sản phẩm đầu ra', 'Đơn vị tính', 'Chỉ tiêu nhiệm vụ năm',
      'Chỉ tiêu nhiệm vụ quý', 'Kết quả thực hiện quý', 'Tỷ lệ (%) so với chỉ tiêu quý', 'Tỷ lệ (%) so với chỉ tiêu năm',
      'Thời gian hoàn thành theo quy định (nếu có)', 'Thời gian hoàn thành thực tế']
      .forEach((h, i) => { const t = make('th', i === 2 ? 'w-task' : '', h); hr.append(t); });
    ['(1)', '(2)', '(3)', '(4)', '(5)', '(6)', '(7)', '(8)=(7)/(6)*100', '(9)=(7)/(5)*100', '(10)', '(11)']
      .forEach(n => nr.append(make('th', '', n)));
    thead.append(hr, nr); table.append(thead);
    const tb = make('tbody');
    let no = 0;
    D.axes.forEach(axis => {
      GROUPS.forEach(([key]) => {
        const gRows = rows.filter(r => r.axis_id === axis.id && r.task_group === key);
        gRows.forEach((r, i) => {
          const tr = make('tr', 'm2-row');
          const pq = td('num out'), py = td('num out');
          const fill = () => {
            compute(r);
            pq.textContent = r.pct_quarter == null ? '' : fmt(r.pct_quarter);
            py.textContent = r.pct_year == null ? '' : fmt(r.pct_year);
          };
          const cRes = td('num'), cAct = td();
          if (editM2) { cRes.append(input(r, 'result', 'number', fill, { min: 0, step: 'any' })); cAct.append(input(r, 'actual_date', 'date', fill)); }
          else { cRes.textContent = fmtN(r.result); cAct.textContent = dmy(r.actual_date); }
          tr.append(td('ctr', String(++no)));
          if (i === 0) {
            const g = td('grp-cell', `Trục ${axis.number}. ${axis.name}\n${GROUP_TITLES[key].replace(/^[IV]+\. /, '')}`);
            g.rowSpan = gRows.length; tr.append(g);
          }
          tr.append(td('', r.content || '(chưa nhập nội dung)'), td('', r.unit || ''), td('num', fmtN(r.annual_target)),
            td('num', fmtN(r.quarter_target)), cRes, pq, py,
            td('', [r.deadline_text, dmy(r.deadline_date)].filter(Boolean).join(' · ')), cAct);
          fill(); tb.append(tr);
        });
      });
    });
    table.append(tb); box.append(table);
  }

  function render() {
    renderM1(); renderM2();
    const ok = $('#other-key'), md = $('#models');
    if (ok) ok.value = otherKey; if (md) md.value = models;
    summary();
  }

  function addRow(axisId, key) {
    rows.push({
      id: null, axis_id: axisId, task_group: key, content: '', product: '', unit: '', annual_target: null, quarter_target: null,
      difficulty: '', lead_agency: '', support_agency: '', leader_id: null, deadline_text: '', deadline_date: '', note: '',
      result: null, actual_date: '', result_note: '',
    });
    markDirty(); render();
  }

  function showErrors(list) {
    const box = $('#save-errors'); box.replaceChildren();
    if (!list || !list.length) { box.hidden = true; return; }
    box.append(make('b', '', 'Chưa lưu được:'));
    const ul = make('ul'); list.forEach(w => ul.append(make('li', '', w))); box.append(ul); box.hidden = false;
    box.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function buildPayload() {
    if (editM2) {                       // Mẫu 2: chỉ cột kết quả và mục II, III
      return {
        other_key_tasks: otherKey, innovative_models: models,
        indicators: rows.map(r => ({ id: r.id, result: r.result, actual_date: r.actual_date, result_note: r.result_note })),
      };
    }
    return {
      indicators: rows.map(r => ({
        id: r.id, axis_id: r.axis_id, task_group: r.task_group, content: r.content, product: r.product, unit: r.unit,
        annual_target: r.annual_target, quarter_target: r.quarter_target, difficulty: r.difficulty,
        lead_agency: r.lead_agency, support_agency: r.support_agency, leader_id: r.leader_id,
        deadline_text: r.deadline_text, deadline_date: r.deadline_date, note: r.note,
      })),
    };
  }

  async function save() {
    const btns = document.querySelectorAll('.savebar button'); btns.forEach(b => b.disabled = true);
    $('#bar-state').textContent = 'Đang lưu…';
    try {
      const res = await fetch(editM2 ? D.saveResultsUrl : D.saveUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(buildPayload()),
      });
      let body = null; try { body = await res.json(); } catch (_) { /* không phải JSON */ }
      if (!res.ok || !body || !body.ok) {
        showErrors((body && body.errors) || [res.status === 400 ? 'Phiên làm việc đã hết hạn, hãy tải lại trang.' : 'Không lưu được, vui lòng thử lại.']);
        $('#bar-state').textContent = 'Lưu thất bại'; return false;
      }
      showErrors(null); load(body.data); render(); dirty = false;
      $('#bar-state').textContent = 'Đã lưu ' + new Date().toLocaleTimeString('vi-VN');
      return true;
    } catch (_) {
      showErrors(['Mất kết nối tới máy chủ, vui lòng thử lại.']); $('#bar-state').textContent = 'Lưu thất bại'; return false;
    } finally { btns.forEach(b => b.disabled = false); }
  }

  // ---------- chuyển thẻ Mẫu 1 / Mẫu 2 ----------
  function showStep(n) {
    document.querySelectorAll('.step-panel').forEach(p => { p.hidden = p.dataset.panel !== String(n); });
    document.querySelectorAll('#stepper .step').forEach(s => s.classList.toggle('active', s.dataset.step === String(n)));
  }
  document.querySelectorAll('#stepper .step').forEach(a => a.addEventListener('click', e => {
    e.preventDefault(); history.replaceState(null, '', a.getAttribute('href')); showStep(a.dataset.step);
  }));
  const hashStep = location.hash === '#m2' ? 2 : (location.hash === '#m1' ? 1 : null);
  showStep(hashStep || (D.col.result_open ? 2 : 1));

  load(D.col);
  render();
  const ok = $('#other-key'), md = $('#models');
  if (ok) { ok.disabled = !editM2; ok.addEventListener('input', () => { otherKey = ok.value; markDirty(); }); }
  if (md) { md.disabled = !editM2; md.addEventListener('input', () => { models = md.value; markDirty(); }); }

  if (editM1 || editM2) {
    $('#btn-save').addEventListener('click', save);
    const sub = $('#btn-submit');
    sub.addEventListener('click', async () => {
      if (!confirm(sub.dataset.confirm)) return;
      if (await save()) { dirty = false; $('#submit-form').submit(); }
    });
    document.addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save(); } });
    window.addEventListener('beforeunload', e => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
  }
})();
