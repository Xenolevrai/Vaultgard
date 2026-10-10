// Vaultgard Dashboard UI Controller
(function () {
  'use strict';

  const VG = window.Vaultgard;
  if (!VG) return;

  const state = VG.createInitialState();
  const ui = {
    activeTab: 'overview',
    activeViewId: 'all',
    selectedInvoiceIds: new Set(),
    activeDetailInvoiceId: null,
    query: {
      search: '',
      status: 'all',
      supplierId: 'all',
      riskLevel: 'all',
      department: 'all',
      assignee: 'all',
      paymentMethod: 'all',
      dateFrom: '',
      dateTo: '',
      amountMin: '',
      amountMax: '',
      preset: '',
      sortBy: 'dueDate',
      sortDir: 'asc'
    }
  };

  const I18N = {
    en: {
      title: 'Vaultgard Invoice Audit & Payment',
      subtitle: 'Fraud Detection • 3-Way Match • Segregation of Duties • SEPA Execution'
    },
    fr: {
      title: 'Vaultgard — Audit de Factures & Paiements',
      subtitle: 'Détection de Fraude • Rapprochement 3 Voies • Séparation des Tâches • SEPA'
    }
  };

  function esc(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function showToast(message, isError = false) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast-banner${isError ? ' error' : ''}`;
    el.textContent = message;
    container.innerHTML = '';
    container.appendChild(el);
    setTimeout(() => {
      if (el.parentNode) el.remove();
    }, 4200);
  }

  function downloadFile(filename, content, mimeType = 'text/plain;charset=utf-8') {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  const BADGE_ICONS = {
    clock: `<svg class="badge-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
    'calendar-days': `<svg class="badge-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="18" x="3" y="4" rx="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/><path d="M8 14h.01"/><path d="M12 14h.01"/><path d="M16 14h.01"/><path d="M8 18h.01"/><path d="M12 18h.01"/><path d="M16 18h.01"/></svg>`,
    'pie-chart': `<svg class="badge-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/></svg>`,
    flame: `<svg class="badge-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>`,
    'badge-check': `<svg class="badge-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/><path d="m9 12 2 2 4-4"/></svg>`,
    timer: `<svg class="badge-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="10" x2="14" y1="2" y2="2"/><line x1="12" x2="15" y1="14" y2="11"/><circle cx="12" cy="14" r="8"/></svg>`,
    'pause-octagon': `<svg class="badge-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 15V9"/><path d="M14 15V9"/><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/></svg>`,
    'file-search': `<svg class="badge-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M4.268 21a2 2 0 0 0 1.727 1H18a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v3"/><path d="m9 18-1.5-1.5"/><circle cx="5" cy="14" r="3"/></svg>`
  };

  function renderDesignBadgePill(badgeSpec) {
    const iconSvg = BADGE_ICONS[badgeSpec.icon] || '';
    return `<span class="badge badge-${esc(badgeSpec.id)}" data-badge-id="${esc(badgeSpec.id)}" style="color: ${esc(badgeSpec.textColor)}; background-color: ${esc(badgeSpec.backgroundColor)};">${iconSvg}<span>${esc(badgeSpec.label)}</span></span>`;
  }

  function renderStatusBadge(statusKey) {
    const meta = VG.STATUS_META[statusKey] || {
      label: statusKey,
      badgeId: 'queued',
      badgeLabel: statusKey,
      icon: 'clock',
      textColor: '#A855F7',
      backgroundColor: '#F3E8FF',
      color: 'queued'
    };
    const label = state.settings.language === 'fr' ? meta.labelFr : meta.label;
    const iconSvg = BADGE_ICONS[meta.icon] || '';
    return `<span class="badge badge-${esc(meta.color)}" data-badge-id="${esc(meta.badgeId || meta.color)}" style="color: ${esc(meta.textColor || '#A855F7')}; background-color: ${esc(meta.backgroundColor || '#F3E8FF')};" title="${esc(label)}">${iconSvg}<span>${esc(meta.badgeLabel || label)}</span><span class="badge-sublabel">· ${esc(label)}</span></span>`;
  }

  function renderRiskBadge(level, score) {
    const lvl = level || 'low';
    const map = {
      high: { icon: 'flame', textColor: '#EF4444', backgroundColor: '#FEE2E2', label: 'High Priority' },
      medium: { icon: 'pie-chart', textColor: '#F59E0B', backgroundColor: '#FEF3C7', label: 'In progress' },
      low: { icon: 'badge-check', textColor: '#14B8A6', backgroundColor: '#CCFBF1', label: 'Ready' }
    };
    const cfg = map[lvl] || map.low;
    const iconSvg = BADGE_ICONS[cfg.icon] || '';
    return `<span class="badge risk-${esc(lvl)}" style="color: ${cfg.textColor}; background-color: ${cfg.backgroundColor};">${iconSvg}<span>${esc(lvl.toUpperCase())} (${Number(score) || 0})</span></span>`;
  }

  function getStorage() {
    try {
      if (window.vgStorage) return window.vgStorage;
      if (typeof Storage !== 'undefined' && window.localStorage) return window.localStorage;
    } catch (_) {
      // Ignore storage access errors
    }
    return null;
  }

  function loadSavedViewsFromStorage() {
    try {
      const store = getStorage();
      const raw = store && store.getItem('vaultgard_saved_views');
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length > 0) {
          state.savedViews = parsed;
        }
      }
    } catch (_) {
      // Ignore storage access errors in restricted environments
    }
  }

  function saveViewsToStorage() {
    try {
      const store = getStorage();
      if (store) {
        store.setItem('vaultgard_saved_views', JSON.stringify(state.savedViews));
      }
    } catch (_) {
      // Ignore storage access errors
    }
  }

  function syncDynamicFilterOptions() {
    const supSel = document.getElementById('f-supplier');
    if (supSel) {
      const curSup = ui.query.supplierId || 'all';
      const supOptions = new Map();
      state.suppliers.forEach((s) => supOptions.set(s.id, s.name));
      state.invoices.forEach((i) => {
        if (i.supplierId && !supOptions.has(i.supplierId)) {
          supOptions.set(i.supplierId, i.supplierName || i.supplierId);
        }
      });
      supSel.innerHTML =
        `<option value="all">All Suppliers</option>` +
        Array.from(supOptions.entries())
          .map(([id, name]) => `<option value="${esc(id)}" ${id === curSup ? 'selected' : ''}>${esc(name)}</option>`)
          .join('');
    }

    const assSel = document.getElementById('f-assignee');
    if (assSel) {
      const curAss = ui.query.assignee || 'all';
      const assignees = new Set(['Sophie Mercier', 'Elena Rostova', 'Claire Dubois', 'Unassigned']);
      state.invoices.forEach((i) => {
        if (i.assignee) assignees.add(i.assignee);
      });
      assSel.innerHTML =
        `<option value="all">All Assignees</option>` +
        Array.from(assignees)
          .map((a) => `<option value="${esc(a)}" ${a === curAss ? 'selected' : ''}>${esc(a)}</option>`)
          .join('');
    }
  }

  // ===========================================================================
  // RENDER HEADER & FILTERS INIT
  // ===========================================================================
  function initSelectors() {
    loadSavedViewsFromStorage();

    const userSel = document.getElementById('select-user');
    userSel.innerHTML = state.users
      .map(
        (u) =>
          `<option value="${esc(u.id)}" ${u.id === state.currentUser.id ? 'selected' : ''}>${esc(u.name)} [${esc(u.role.toUpperCase())}]</option>`
      )
      .join('');

    const statusSel = document.getElementById('f-status');
    statusSel.innerHTML =
      `<option value="all">All Statuses (10)</option>` +
      VG.ALL_STATUS_KEYS.map((k) => `<option value="${esc(k)}">${esc(VG.STATUS_META[k].label)}</option>`).join('');

    syncDynamicFilterOptions();
  }

  // ===========================================================================
  // TAB 1: OVERVIEW & KPIs
  // ===========================================================================
  function renderOverview() {
    const kpis = VG.computeKPIs(state);
    const cur = kpis.baseCurrency;
    const fmt = (val) => VG.formatMoney(val, cur);

    const topCards = document.getElementById('kpi-top-cards');
    const oldest = kpis.pendingVerification.oldestInvoice;
    topCards.innerHTML = `
      <div class="card">
        <div class="card-title">Ready to Pay (${esc(cur)})</div>
        <div class="kpi-value" style="color: var(--teal);">${esc(fmt(kpis.readyToPay.thisMonth))}</div>
        <div class="kpi-sub">
          <span>Today: <strong>${esc(fmt(kpis.readyToPay.today))}</strong></span>
          <span>This Week: <strong>${esc(fmt(kpis.readyToPay.thisWeek))}</strong></span>
          <span>This Month: <strong>${esc(fmt(kpis.readyToPay.thisMonth))}</strong> (${kpis.readyToPay.count} invoices)</span>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Pending Verification Queue</div>
        <div class="kpi-value" style="color: var(--warning);">${esc(fmt(kpis.pendingVerification.totalAmount))}</div>
        <div class="kpi-sub">
          <span>Invoices in queue: <strong>${kpis.pendingVerification.count}</strong></span>
          <span>Oldest item: <strong>${oldest ? `${esc(oldest.invoiceNumber)} (${oldest.ageHours}h old)` : 'None'}</strong></span>
          <span>Avg verification time: <strong>${kpis.avgVerificationTimeHours}h</strong></span>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Flagged &amp; Fraud Risk Prevented</div>
        <div class="kpi-value" style="color: var(--danger);">${esc(fmt(kpis.flagged.amountAtRisk))}</div>
        <div class="kpi-sub">
          <span>Flagged suspicious: <strong>${kpis.flagged.count}</strong> (${esc(fmt(kpis.flagged.amountAtRisk))} at risk)</span>
          <span>Confirmed scam blocked: <strong>${kpis.flagged.rejectedCount}</strong> (${esc(fmt(kpis.flagged.confirmedScamAmount))})</span>
          <span>Total fraud exposure caught: <strong>${esc(fmt(kpis.flagged.moneySaved))}</strong></span>
        </div>
      </div>

      <div class="card">
        <div class="card-title">Overdue Invoices (Past Due, Unpaid)</div>
        <div class="kpi-value" style="color: ${kpis.overdue.count > 0 ? 'var(--orange)' : 'var(--success)'};">
          ${kpis.overdue.count} (${esc(fmt(kpis.overdue.totalAmount))})
        </div>
        <div class="kpi-sub">
          <span>Reference Date: <strong>${esc(state.referenceDate.slice(0, 10))}</strong></span>
          <span>SLA Threshold: <strong>${state.settings.slaHours}h</strong></span>
          <span>Total tracked invoices: <strong>${kpis.totalInvoices}</strong></span>
        </div>
      </div>
    `;

    // 10 Status Cards
    const statusGrid = document.getElementById('kpi-status-grid');
    statusGrid.innerHTML = VG.ALL_STATUS_KEYS.map((key) => {
      const meta = VG.STATUS_META[key];
      const stat = kpis.byStatus[key] || { count: 0, totalAmount: 0 };
      return `
        <div class="status-card" data-filter-status="${esc(key)}" role="button" tabindex="0">
          <div class="status-card-header">
            ${renderStatusBadge(key)}
            <span class="status-count">${stat.count}</span>
          </div>
          <div class="status-amount">${esc(fmt(stat.totalAmount))}</div>
          <div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 0.2rem;">${esc(meta.description)}</div>
        </div>
      `;
    }).join('');

    statusGrid.querySelectorAll('[data-filter-status]').forEach((card) => {
      const activateFilter = () => {
        const st = card.getAttribute('data-filter-status');
        resetQueryFilters();
        ui.query.status = st;
        document.getElementById('f-status').value = st;
        switchTab('invoices');
      };
      card.addEventListener('click', activateFilter);
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          activateFilter();
        }
      });
    });

    // Trend Charts
    const maxMonth = Math.max(1, ...kpis.trends.byMonth.map((m) => m.totalAmount));
    document.getElementById('chart-monthly-trends').innerHTML = kpis.trends.byMonth
      .map((m) => {
        const pct = Math.min(100, Math.round((m.totalAmount / maxMonth) * 100));
        const flagPct = m.totalAmount > 0 ? Math.round((m.flaggedAmount / m.totalAmount) * pct) : 0;
        const cleanPct = Math.max(0, pct - flagPct);
        return `
          <div class="bar-item">
            <span><strong>${esc(m.month)}</strong> (${m.count})</span>
            <div class="bar-track" title="Verified/Paid: ${esc(fmt(m.verifiedAmount + m.paidAmount))} | Flagged/Rejected: ${esc(fmt(m.flaggedAmount))}">
              <div class="bar-fill success" style="width: ${cleanPct}%"></div>
              <div class="bar-fill danger" style="width: ${flagPct}%"></div>
            </div>
            <span class="mono" style="text-align: right;">${esc(fmt(m.totalAmount))}</span>
          </div>
        `;
      })
      .join('');

    const maxSup = Math.max(1, ...kpis.trends.bySupplier.map((s) => s.totalAmount));
    document.getElementById('chart-supplier-trends').innerHTML = kpis.trends.bySupplier
      .map((s) => {
        const pct = Math.min(100, Math.round((s.totalAmount / maxSup) * 100));
        const isRisky = s.maxRiskScore >= 65 || s.flaggedCount > 0;
        return `
          <div class="bar-item">
            <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${esc(s.supplierName)}">
              ${esc(s.supplierName)}
            </span>
            <div class="bar-track">
              <div class="bar-fill ${isRisky ? 'danger' : ''}" style="width: ${pct}%"></div>
            </div>
            <span class="mono" style="text-align: right;">${esc(fmt(s.totalAmount))}</span>
          </div>
        `;
      })
      .join('');
  }

  // ===========================================================================
  // TAB 2: INVOICES LIST, FILTERS, SAVED VIEWS & BULK ACTIONS
  // ===========================================================================
  function renderSavedViewsBar() {
    const bar = document.getElementById('saved-views-bar');
    const viewsHtml = state.savedViews
      .map(
        (v) =>
          `<button type="button" class="view-pill ${ui.activeViewId === v.id ? 'active' : ''}" data-view-id="${esc(v.id)}">${esc(v.name)}</button>`
      )
      .join('');

    const badgesHtml = (VG.BADGE_DESIGN_SPEC || [])
      .map((b) => {
        const iconSvg = BADGE_ICONS[b.icon] || '';
        return `<button type="button" class="badge badge-${esc(b.id)} badge-filter-btn" data-badge-filter="${esc(b.id)}" style="color: ${esc(b.textColor)}; background-color: ${esc(b.backgroundColor)}; border: 1px solid ${esc(b.textColor)}33; cursor: pointer;">${iconSvg}<span>${esc(b.label)}</span></button>`;
      })
      .join('');

    bar.innerHTML = `${viewsHtml}<span style="margin: 0 0.25rem; color: var(--border);">|</span>${badgesHtml}`;

    bar.querySelectorAll('[data-view-id]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const vid = btn.getAttribute('data-view-id');
        const view = state.savedViews.find((v) => v.id === vid);
        if (!view) return;
        resetQueryFilters();
        ui.activeViewId = vid;
        Object.assign(ui.query, view.query);
        syncFilterInputsFromQuery();
        renderAll();
      });
    });

    bar.querySelectorAll('[data-badge-filter]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const bid = btn.getAttribute('data-badge-filter');
        const spec = (VG.BADGE_DESIGN_SPEC || []).find((b) => b.id === bid);
        if (!spec) return;
        resetQueryFilters();
        ui.activeViewId = `badge_${bid}`;
        ui.query.status = spec.mappedStatuses.length === 1 ? spec.mappedStatuses[0] : spec.mappedStatuses;
        if (typeof ui.query.status === 'string') {
          document.getElementById('f-status').value = ui.query.status;
        }
        renderAll();
      });
    });
  }

  function resetQueryFilters() {
    ui.activeViewId = 'all';
    ui.query = {
      search: '',
      status: 'all',
      supplierId: 'all',
      riskLevel: 'all',
      department: 'all',
      assignee: 'all',
      paymentMethod: 'all',
      dateFrom: '',
      dateTo: '',
      amountMin: '',
      amountMax: '',
      preset: '',
      sortBy: ui.query.sortBy || 'dueDate',
      sortDir: ui.query.sortDir || 'asc'
    };
    syncFilterInputsFromQuery();
  }

  function syncFilterInputsFromQuery() {
    document.getElementById('f-search').value = ui.query.search || '';
    document.getElementById('f-status').value = ui.query.status || 'all';
    document.getElementById('f-supplier').value = ui.query.supplierId || 'all';
    document.getElementById('f-risk').value = ui.query.riskLevel || 'all';
    document.getElementById('f-dept').value = ui.query.department || 'all';
    document.getElementById('f-assignee').value = ui.query.assignee || 'all';
    document.getElementById('f-method').value = ui.query.paymentMethod || 'all';
    document.getElementById('f-date-from').value = ui.query.dateFrom || '';
    document.getElementById('f-date-to').value = ui.query.dateTo || '';
    document.getElementById('f-amt-min').value = ui.query.amountMin || '';
    document.getElementById('f-amt-max').value = ui.query.amountMax || '';
  }

  function renderInvoicesTable() {
    renderSavedViewsBar();
    const filtered = VG.queryInvoices(state, ui.query);
    const nowStr = state.referenceDate.slice(0, 10);
    document.getElementById('badge-invoices-count').textContent = String(filtered.length);

    const tbody = document.getElementById('invoices-tbody');
    if (filtered.length === 0) {
      tbody.innerHTML = `<tr><td colspan="11" style="text-align: center; padding: 2rem; color: var(--text-muted);">No invoices match the current filters.</td></tr>`;
      return;
    }

    tbody.innerHTML = filtered
      .map((inv) => {
        const isOverdue =
          inv.dueDate < nowStr && inv.status !== VG.STATUSES.PAID && inv.status !== VG.STATUSES.REJECTED;
        const checked = ui.selectedInvoiceIds.has(inv.id) ? 'checked' : '';
        return `
          <tr data-inv-row="${esc(inv.id)}">
            <td><input type="checkbox" class="chk-inv" data-id="${esc(inv.id)}" ${checked} aria-label="Select ${esc(inv.invoiceNumber)}" /></td>
            <td class="mono"><strong>${esc(inv.invoiceNumber)}</strong><div style="font-size:0.7rem;color:var(--text-muted);">${esc(inv.id)}</div></td>
            <td>
              <strong>${esc(inv.supplierName)}</strong>
              <div style="font-size: 0.72rem; color: var(--text-muted);">${esc(inv.department)} • ${esc(inv.paymentMethod)}</div>
            </td>
            <td class="mono"><strong>${esc(VG.formatMoney(inv.amount, inv.currency))}</strong></td>
            <td class="mono">${esc(inv.issueDate)}</td>
            <td class="mono">
              ${esc(inv.dueDate)}
              ${isOverdue ? '<span class="badge badge-red" style="margin-left:0.25rem;">OVERDUE</span>' : ''}
            </td>
            <td>${renderStatusBadge(inv.status)}</td>
            <td>${renderRiskBadge(inv.riskLevel, inv.riskScore)}</td>
            <td class="mono">${inv.poNumber ? esc(inv.poNumber) : '<span style="color:var(--danger)">No PO</span>'}</td>
            <td>${esc(inv.assignee)}</td>
            <td>
              <button type="button" class="btn btn-sm btn-primary" data-inspect-id="${esc(inv.id)}">Inspect / Audit</button>
            </td>
          </tr>
        `;
      })
      .join('');

    tbody.querySelectorAll('.chk-inv').forEach((chk) => {
      chk.addEventListener('change', (e) => {
        const id = e.target.getAttribute('data-id');
        if (e.target.checked) ui.selectedInvoiceIds.add(id);
        else ui.selectedInvoiceIds.delete(id);
        document.getElementById('selected-count-label').textContent = `${ui.selectedInvoiceIds.size} selected`;
      });
    });

    tbody.querySelectorAll('[data-inspect-id]').forEach((btn) => {
      btn.addEventListener('click', () => {
        openInvoiceDetail(btn.getAttribute('data-inspect-id'));
      });
    });
  }

  // ===========================================================================
  // INVOICE DETAIL MODAL (SECTIONS 4, 5, 6)
  // ===========================================================================
  function openInvoiceDetail(invoiceId) {
    ui.activeDetailInvoiceId = invoiceId;
    renderInvoiceDetailModal();
    const dlg = document.getElementById('dialog-invoice-detail');
    if (dlg && !dlg.open) {
      if (typeof dlg.showModal === 'function') dlg.showModal();
      else dlg.setAttribute('open', 'open');
    }
  }

  function renderInvoiceDetailModal() {
    const inv = state.invoices.find((i) => i.id === ui.activeDetailInvoiceId);
    if (!inv) return;

    const supplier = state.suppliers.find((s) => s.id === inv.supplierId);
    const mask = state.settings.gdprMaskPii;
    const reqLevels = inv.requiredApprovalLevels || VG.getRequiredApprovalLevels(
      VG.convertCurrency(inv.amount, inv.currency, 'EUR'),
      state.settings
    );
    const curApprovals = (inv.approvals || []).length;

    document.getElementById('detail-dialog-title').innerHTML = `
      ${esc(inv.invoiceNumber)} — ${esc(inv.supplierName)} ${renderStatusBadge(inv.status)} ${renderRiskBadge(inv.riskLevel, inv.riskScore)}
    `;
    document.getElementById('detail-dialog-subtitle').textContent =
      `ID: ${inv.id} • Department: ${inv.department} • Entity: ${inv.entity} • Approval Levels: ${curApprovals}/${reqLevels} • Active Actor: ${state.currentUser.name} (${state.currentUser.role})`;

    const body = document.getElementById('detail-dialog-body');
    body.innerHTML = `
      <div class="detail-split">
        <!-- Left Column: Original Document Viewer & Linked Docs -->
        <div>
          <div class="card-title">Original Document Viewer (PDF / OCR Overlay) &amp; Extracted Fields</div>
          <div class="doc-preview">
            <div style="display:flex;justify-content:space-between;border-bottom:1px solid var(--border);padding-bottom:0.5rem;margin-bottom:0.6rem;">
              <span><strong>ORIGINAL INVOICE PDF</strong> (${esc(inv.invoiceNumber)}.pdf)</span>
              <span>Source: ${esc(inv.ingestionSource || 'Email / OCR')}</span>
            </div>
            ${
              inv.documentMeta && (inv.documentMeta.tampered || inv.documentMeta.fontMismatch || inv.documentMeta.modifiedAfterIssue)
                ? `<div style="background:#FEE2E2;border:1px solid #FECACA;color:#B91C1C;padding:0.45rem 0.6rem;border-radius:6px;margin-bottom:0.6rem;font-family:var(--font);font-weight:500;">
                    Forensic PDF Alert: Layer tampering or font glyph mismatch detected on IBAN &amp; Total block.
                   </div>`
                : `<div style="background:#CCFBF1;border:1px solid #99F6E4;color:#0F766E;padding:0.35rem 0.6rem;border-radius:6px;margin-bottom:0.6rem;font-family:var(--font);font-weight:500;">
                    Digital signature &amp; PDF XMP metadata verified clean.
                   </div>`
            }
            <div><strong>VENDOR:</strong> ${esc(inv.supplierName)}</div>
            <div><strong>VAT / TAX ID:</strong> ${esc(inv.vatNumber || 'MISSING')}</div>
            <div><strong>SENDER EMAIL:</strong> ${esc(VG.maskPII(inv.senderEmail || 'N/A', mask))}</div>
            <div><strong>BANK IBAN:</strong> ${esc(VG.maskPII(inv.iban, mask))} ${
              inv.callbackVerified ? '<span class="badge badge-ready">Callback Verified</span>' : ''
            }</div>
            <div><strong>INVOICE DATE:</strong> ${esc(inv.issueDate)} | <strong>DUE DATE:</strong> ${esc(inv.dueDate)}</div>
            <div><strong>PO REFERENCE:</strong> ${esc(inv.poNumber || 'NONE')} (PO Amt: ${esc(VG.formatMoney(inv.poAmount || 0, inv.currency))})</div>
            <div><strong>DELIVERY NOTE (GRN):</strong> ${esc(inv.grnNumber || 'NONE')} [${esc(inv.grnStatus || 'missing')}]</div>
            <div style="margin-top:0.6rem;padding-top:0.5rem;border-top:1px solid var(--border);font-size:0.92rem;">
              <strong>TOTAL AMOUNT: ${esc(VG.formatMoney(inv.amount, inv.currency))}</strong>
              (Remaining: ${esc(VG.formatMoney(VG.getRemainingAmount(inv), inv.currency))})
            </div>
          </div>

          <div class="card" style="margin-top: 0.9rem;">
            <div class="card-title">Linked Documents &amp; 3-Way Match Artifacts</div>
            <div style="font-size: 0.82rem; display: flex; flex-direction: column; gap: 0.35rem;">
              <div><strong>Purchase Order:</strong> ${inv.poNumber ? `${esc(inv.poNumber)} (${esc(VG.formatMoney(inv.poAmount, inv.currency))})` : 'Missing PO'}</div>
              <div><strong>Goods Received / Delivery Note:</strong> ${inv.grnNumber ? `${esc(inv.grnNumber)} (${esc(inv.grnStatus)})` : 'Missing GRN'}</div>
              <div><strong>Supplier Master Record:</strong> ${supplier ? `${esc(supplier.name)} — Status: ${esc(supplier.status.toUpperCase())}, Avg Invoice: ${esc(VG.formatMoney(supplier.avgInvoiceAmount, 'EUR'))}` : 'Not in Approved Vendor List'}</div>
              <div><strong>Attachments (${(inv.attachments || []).length}):</strong>
                ${(inv.attachments || []).map((a) => `<span class="badge badge-slate">${esc(a.name)}</span>`).join(' ')}
                <button type="button" class="btn btn-sm" id="btn-detail-attach" style="margin-left:0.4rem;">+ Attach Proof</button>
              </div>
            </div>
          </div>

          <div class="card" style="margin-top: 0.9rem;">
            <div class="card-title">Internal Comments &amp; @Mentions</div>
            <div style="max-height: 140px; overflow-y: auto; margin-bottom: 0.5rem; display: flex; flex-direction: column; gap: 0.4rem;">
              ${(inv.comments || [])
                .map((c) => {
                  const formatted = esc(c.text).replace(/(@[a-zA-Z0-9_.-]+)/g, '<span class="mention">$1</span>');
                  return `<div style="font-size:0.8rem;background:var(--bg-subtle);padding:0.45rem 0.65rem;border-radius:6px;border:1px solid var(--border);">
                    <strong>${esc(c.authorName)}</strong> <span style="color:var(--text-muted);font-size:0.72rem;">(${esc(c.timestamp.slice(0, 16).replace('T', ' '))})</span>:
                    <div>${formatted}</div>
                  </div>`;
                })
                .join('')}
            </div>
            <div style="display: flex; gap: 0.4rem;">
              <input type="text" id="input-detail-comment" placeholder="Write comment with @claire.dubois or @fraud-team..." style="flex:1;" />
              <button type="button" class="btn btn-sm btn-primary" id="btn-detail-comment">Post Comment</button>
            </div>
          </div>
        </div>

        <!-- Right Column: Workflow Actions, 9 Fraud Checks & Timeline -->
        <div>
          <div class="card" style="margin-bottom: 0.9rem;">
            <div class="card-title">Workflow &amp; Audit Actions (Multi-Level Approval: ${curApprovals}/${reqLevels})</div>
            <div style="display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.5rem;">
              <button type="button" class="btn btn-sm" data-wf-action="run_checks">Re-run 9 Checks</button>
              <button type="button" class="btn btn-sm" data-wf-action="assign">Assign to Auditor</button>
              <button type="button" class="btn btn-sm" data-wf-action="verify_callback">Verify by Callback</button>
              <button type="button" class="btn btn-sm btn-primary" data-wf-action="approve">Approve (L${curApprovals + 1}/${reqLevels})</button>
              <button type="button" class="btn btn-sm" data-wf-action="approve_and_schedule">Approve &amp; Schedule</button>
              <button type="button" class="btn btn-sm" data-wf-action="request_info">Request Info</button>
              <button type="button" class="btn btn-sm" data-wf-action="hold">Put On Hold</button>
              <button type="button" class="btn btn-sm" data-wf-action="release">Release Hold</button>
              <button type="button" class="btn btn-sm" data-wf-action="escalate">Escalate</button>
              <button type="button" class="btn btn-sm btn-danger" data-wf-action="flag">Flag Suspicious</button>
              <button type="button" class="btn btn-sm btn-danger" data-wf-action="reject">Reject Scam</button>
            </div>
            <input type="text" id="input-wf-note" placeholder="Optional action note / callback confirmation note / rejection reason..." style="width: 100%;" />
          </div>

          <div class="card" style="margin-bottom: 0.9rem;">
            <div class="card-title">4. 9-Point Fraud &amp; Compliance Checklist</div>
            <div class="checklist-list">
              ${(inv.checklist || [])
                .map((chk) => {
                  const badgeColor =
                    chk.status === 'passed' ? 'emerald' : chk.status === 'failed' ? 'red' : 'amber';
                  return `
                    <div class="check-item">
                      <div>
                        <strong>${esc(chk.label)}</strong>
                        <div style="color: var(--text-muted); font-size: 0.76rem;">${esc(chk.reason)}</div>
                      </div>
                      <span class="badge badge-${badgeColor}">${esc(chk.status.toUpperCase())}</span>
                    </div>
                  `;
                })
                .join('')}
            </div>
          </div>

          <div class="card">
            <div class="card-title">5 &amp; 11. Full Lifecycle Timeline &amp; Version History (${(inv.versionHistory || []).length} versions)</div>
            <div class="timeline-list">
              ${(inv.timeline || [])
                .map(
                  (t) => `
                  <div class="timeline-entry">
                    <strong>${esc(t.event)}</strong>
                    <span style="color:var(--text-muted);"> — ${esc(t.actorName)} (${esc(t.timestamp.slice(0, 16).replace('T', ' '))})</span>
                    ${t.note ? `<div style="color:var(--text-muted);font-size:0.75rem;">Note: ${esc(t.note)}</div>` : ''}
                  </div>
                `
                )
                .join('')}
            </div>
          </div>
        </div>
      </div>
    `;

    // Wire workflow action buttons
    body.querySelectorAll('[data-wf-action]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const act = btn.getAttribute('data-wf-action');
        const note = document.getElementById('input-wf-note').value.trim();
        try {
          VG.performWorkflowAction(state, inv.id, act, {
            note,
            reason: note || undefined,
            assignee: act === 'assign' ? (note || 'Sophie Mercier') : undefined
          });
          showToast(`Action "${act}" executed on ${inv.invoiceNumber}`);
          renderAll();
          renderInvoiceDetailModal();
        } catch (err) {
          showToast(err.message, true);
        }
      });
    });

    document.getElementById('btn-detail-comment').addEventListener('click', () => {
      const text = document.getElementById('input-detail-comment').value.trim();
      if (!text) return;
      try {
        VG.performWorkflowAction(state, inv.id, 'comment', { text });
        showToast('Comment posted');
        renderInvoiceDetailModal();
        renderAll();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    document.getElementById('btn-detail-attach').addEventListener('click', () => {
      try {
        VG.performWorkflowAction(state, inv.id, 'attach', {
          name: `callback-proof-${inv.invoiceNumber}.pdf`,
          type: 'proof_of_verification'
        });
        showToast('Verification attachment added');
        renderInvoiceDetailModal();
        renderAll();
      } catch (err) {
        showToast(err.message, true);
      }
    });
  }

  // ===========================================================================
  // TAB 3: PAYMENTS, BLOCKING RULES, SEPA BATCHES & CASH FLOW
  // ===========================================================================
  function renderPaymentsTab() {
    const forecast = VG.computeCashFlowForecast(state);
    const cur = forecast.baseCurrency;
    const fmt = (v) => VG.formatMoney(v, cur);

    document.getElementById('cashflow-cards').innerHTML = `
      <div class="card">
        <div class="card-title">Overdue &amp; Due Today</div>
        <div class="kpi-value" style="color: var(--orange);">${esc(fmt(forecast.overdue + forecast.dueToday))}</div>
        <div class="kpi-sub">
          <span>Overdue: <strong>${esc(fmt(forecast.overdue))}</strong></span>
          <span>Due Today: <strong>${esc(fmt(forecast.dueToday))}</strong></span>
        </div>
      </div>
      <div class="card">
        <div class="card-title">Next 7 Days Forecast</div>
        <div class="kpi-value" style="color: var(--teal);">${esc(fmt(forecast.next7Days))}</div>
        <div class="kpi-sub"><span>Scheduled &amp; Ready to Pay</span></div>
      </div>
      <div class="card">
        <div class="card-title">Next 30 Days Forecast</div>
        <div class="kpi-value">${esc(fmt(forecast.next30Days))}</div>
        <div class="kpi-sub"><span>Beyond 30d: ${esc(fmt(forecast.beyond30Days))}</span></div>
      </div>
      <div class="card">
        <div class="card-title">Early-Payment Discount Opportunity</div>
        <div class="kpi-value" style="color: var(--success);">${esc(fmt(forecast.potentialEarlyDiscountSavings))}</div>
        <div class="kpi-sub"><span>Schedule before discount deadline to capture</span></div>
      </div>
    `;

    // Payable queue: only audited & approved invoices (verified_approved, ready_to_pay, scheduled) + recently paid
    const payableList = state.invoices.filter((inv) =>
      [VG.STATUSES.VERIFIED_APPROVED, VG.STATUSES.READY_TO_PAY, VG.STATUSES.SCHEDULED, VG.STATUSES.PAID].includes(inv.status)
    );
    const activePayableCount = payableList.filter((i) => i.status !== VG.STATUSES.PAID).length;
    document.getElementById('badge-payable-count').textContent = String(activePayableCount);

    const tbody = document.getElementById('payable-tbody');
    tbody.innerHTML = payableList
      .map((inv) => {
        const rem = VG.getRemainingAmount(inv);
        const check = VG.canPayInvoice(state, inv);
        const disc = VG.computeEarlyDiscount(inv, state.referenceDate.slice(0, 10));
        return `
          <tr>
            <td class="mono"><strong>${esc(inv.invoiceNumber)}</strong></td>
            <td>
              <strong>${esc(inv.supplierName)}</strong>
              <div class="mono" style="font-size:0.72rem;color:var(--text-muted);">${esc(VG.maskPII(inv.iban, state.settings.gdprMaskPii))}</div>
            </td>
            <td>${renderStatusBadge(inv.status)}</td>
            <td class="mono">
              Due: ${esc(inv.dueDate)}
              ${inv.scheduledPaymentDate ? `<div style="color:var(--accent);font-size:0.74rem;">Sched: ${esc(inv.scheduledPaymentDate)}</div>` : ''}
            </td>
            <td class="mono">
              <strong>${esc(VG.formatMoney(rem, inv.currency))}</strong>
              <div style="font-size:0.72rem;color:var(--text-muted);">of ${esc(VG.formatMoney(inv.amount, inv.currency))}</div>
            </td>
            <td>
              ${
                disc.eligible
                  ? `<span class="badge badge-emerald">Save ${esc(VG.formatMoney(disc.discountAmount, inv.currency))} (${disc.discountPercent}%)</span>`
                  : `<span style="font-size:0.75rem;color:var(--text-muted);">None</span>`
              }
            </td>
            <td>${esc(inv.approvedByName || 'Verified')}</td>
            <td>
              ${
                inv.status === VG.STATUSES.PAID
                  ? `<span class="badge badge-green">✓ Paid (${esc(inv.paymentReference)})</span>`
                  : check.allowed
                  ? `<span class="badge badge-emerald">✓ Eligible to Pay</span>`
                  : `<span class="badge badge-red" title="${esc(check.reason)}">Blocked: ${esc(check.reason.slice(0, 42))}...</span>`
              }
            </td>
            <td>
              ${
                inv.status !== VG.STATUSES.PAID
                  ? `<div style="display:flex;flex-wrap:wrap;gap:0.3rem;">
                      <button type="button" class="btn btn-sm" data-pay-act="schedule_discount" data-id="${esc(inv.id)}" ${!check.allowed ? 'disabled' : ''}>Sched (Discount)</button>
                      <button type="button" class="btn btn-sm btn-success" data-pay-act="pay_full" data-id="${esc(inv.id)}" ${!check.allowed ? 'disabled' : ''}>Pay &amp; Reconcile</button>
                      <button type="button" class="btn btn-sm" data-pay-act="partial" data-id="${esc(inv.id)}" ${!check.allowed ? 'disabled' : ''}>50% Partial</button>
                      <button type="button" class="btn btn-sm" data-pay-act="credit_note" data-id="${esc(inv.id)}">Credit Note</button>
                     </div>`
                  : `<span style="font-size:0.76rem;color:var(--text-muted);">${inv.reconciled ? '✓ Bank Reconciled' : 'Paid'}</span>`
              }
            </td>
          </tr>
        `;
      })
      .join('');

    tbody.querySelectorAll('[data-pay-act]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        const act = btn.getAttribute('data-pay-act');
        const inv = state.invoices.find((i) => i.id === id);
        if (!inv) return;
        try {
          if (act === 'schedule_discount') {
            VG.scheduleInvoicePayment(state, id, { useEarlyDiscount: true });
            showToast(`Scheduled ${inv.invoiceNumber} capturing early payment discount`);
          } else if (act === 'pay_full') {
            VG.recordPaymentOrCredit(state, id, { reconciled: true, reference: `SEPA-RECON-${inv.invoiceNumber}` });
            showToast(`Paid & bank-reconciled ${inv.invoiceNumber}`);
          } else if (act === 'partial') {
            const half = Number((VG.getRemainingAmount(inv) / 2).toFixed(2));
            VG.recordPaymentOrCredit(state, id, { amount: half, reference: `PART-${inv.invoiceNumber}` });
            showToast(`Recorded partial payment of ${VG.formatMoney(half, inv.currency)}`);
          } else if (act === 'credit_note') {
            const cnAmt = Math.min(500, VG.getRemainingAmount(inv));
            VG.recordPaymentOrCredit(state, id, { type: 'credit_note', amount: cnAmt, reference: `CN-${inv.invoiceNumber}` });
            showToast(`Applied credit note of ${VG.formatMoney(cnAmt, inv.currency)}`);
          }
          renderAll();
        } catch (err) {
          showToast(err.message, true);
        }
      });
    });

    const batchesBox = document.getElementById('batches-container');
    if (!state.paymentBatches || state.paymentBatches.length === 0) {
      batchesBox.innerHTML = `<div style="font-size:0.82rem;color:var(--text-muted);">No SEPA batches generated yet. Click "Generate SEPA XML Batch" above while acting as Payer or Admin.</div>`;
    } else {
      batchesBox.innerHTML = state.paymentBatches
        .map(
          (b) => `
          <div class="check-item" style="margin-top:0.4rem;">
            <div>
              <strong>${esc(b.id)}</strong> — ${b.invoiceCount} invoices (${esc(VG.formatMoney(b.totalAmountEur, 'EUR'))})
              <span class="badge ${b.status === 'reconciled' ? 'badge-emerald' : 'badge-amber'}" style="margin-left:0.35rem;">${esc((b.status || 'generated').toUpperCase())}</span>
              <div style="font-size:0.75rem;color:var(--text-muted);">Created by ${esc(b.createdBy)} • Exec Date: ${esc(b.executionDate)} • Ref: ${esc(b.paymentReference)}</div>
            </div>
            <div style="display:flex;gap:0.4rem;flex-wrap:wrap;">
              ${
                b.status !== 'reconciled'
                  ? `<button type="button" class="btn btn-sm btn-success" data-reconcile-batch="${esc(b.id)}">✓ Mark Batch Paid &amp; Reconciled</button>`
                  : ''
              }
              <button type="button" class="btn btn-sm btn-primary" data-dl-batch="${esc(b.id)}">Download SEPA pain.001 XML</button>
            </div>
          </div>
        `
        )
        .join('');

      batchesBox.querySelectorAll('[data-dl-batch]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const bid = btn.getAttribute('data-dl-batch');
          const batch = state.paymentBatches.find((b) => b.id === bid);
          if (batch) {
            downloadFile(`${batch.id}.xml`, batch.sepaXml, 'application/xml');
            showToast(`Downloaded ${batch.id}.xml`);
          }
        });
      });

      batchesBox.querySelectorAll('[data-reconcile-batch]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const bid = btn.getAttribute('data-reconcile-batch');
          try {
            VG.reconcilePaymentBatch(state, bid);
            showToast(`Batch ${bid} marked as Paid & Bank-Reconciled`);
            renderAll();
          } catch (err) {
            showToast(err.message, true);
          }
        });
      });
    }
  }

  // ===========================================================================
  // TAB 4: SUPPLIERS VIEW
  // ===========================================================================
  function renderSuppliersTab() {
    const grid = document.getElementById('suppliers-grid');
    grid.innerHTML = state.suppliers
      .map((s) => {
        const supInvoices = state.invoices.filter((i) => i.supplierId === s.id);
        const flagCount = supInvoices.filter(
          (i) => i.status === VG.STATUSES.FLAGGED || i.status === VG.STATUSES.REJECTED
        ).length;
        const statusColor =
          s.status === 'verified' ? 'emerald' : s.status === 'blacklisted' ? 'red' : 'amber';
        return `
          <div class="card">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.5rem;">
              <div>
                <h3 style="font-size:1rem;">${esc(s.name)}</h3>
                <div class="mono" style="font-size:0.75rem;color:var(--text-muted);">
                  ID: ${esc(s.id)} • VAT: ${esc(s.vatNumber)} • Reg: ${esc(s.regNumber)} • Domain: @${esc(s.officialDomain)}
                </div>
              </div>
              <span class="badge badge-${statusColor}">${esc(s.status.toUpperCase())}</span>
            </div>

            <div style="font-size:0.82rem;margin-bottom:0.6rem;">
              <div><strong>Current IBAN:</strong> <span class="mono">${esc(VG.maskPII(s.iban, state.settings.gdprMaskPii))}</span>
                ${s.bankChangedRecently ? '<span class="badge badge-orange">Recent Unverified IBAN Change</span>' : ''}
              </div>
              <div><strong>Risk Rating:</strong> ${esc(s.riskRating.toUpperCase())} • <strong>Historical Avg:</strong> ${esc(VG.formatMoney(s.avgInvoiceAmount, 'EUR'))}</div>
              <div><strong>History:</strong> ${supInvoices.length} invoices (${flagCount} flagged/rejected)</div>
            </div>

            <div style="margin-bottom:0.65rem;">
              <div class="card-title" style="font-size:0.7rem;">Bank Detail Change Log</div>
              ${
                (s.bankChangeLog || []).length === 0
                  ? `<div style="font-size:0.75rem;color:var(--text-muted);">No bank account changes recorded.</div>`
                  : s.bankChangeLog
                      .map(
                        (log) =>
                          `<div class="mono" style="font-size:0.73rem;color:var(--text-muted);">
                            ${esc(log.changedAt)}: ${esc(log.previousIban)} → ${esc(log.newIban)} (${log.verified ? 'Verified' : 'Unverified'})
                          </div>`
                      )
                      .join('')
              }
            </div>

            <div style="display:flex;flex-wrap:wrap;gap:0.4rem;">
              <button type="button" class="btn btn-sm btn-success" data-sup-act="whitelist" data-id="${esc(s.id)}">Whitelist / Verify</button>
              <button type="button" class="btn btn-sm btn-danger" data-sup-act="blacklist" data-id="${esc(s.id)}">Blacklist Supplier</button>
              <button type="button" class="btn btn-sm" data-sup-act="change_iban" data-id="${esc(s.id)}">Simulate IBAN Change</button>
            </div>
          </div>
        `;
      })
      .join('');

    grid.querySelectorAll('[data-sup-act]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const sid = btn.getAttribute('data-id');
        const act = btn.getAttribute('data-sup-act');
        try {
          if (act === 'whitelist') {
            VG.setSupplierStatus(state, sid, 'verified', null, 'Manual whitelist');
            showToast(`Supplier ${sid} whitelisted & verified`);
          } else if (act === 'blacklist') {
            VG.setSupplierStatus(state, sid, 'blacklisted', null, 'Fraud risk blacklist');
            showToast(`Supplier ${sid} added to blacklist`);
          } else if (act === 'change_iban') {
            const newIban = `FR76999900001111${Math.floor(100000 + Math.random() * 899999)}`;
            VG.updateSupplierBankDetails(state, sid, newIban, null, false);
            showToast(`Logged unverified IBAN change (${newIban}) for ${sid}`);
          }
          renderAll();
        } catch (err) {
          showToast(err.message, true);
        }
      });
    });
  }

  // ===========================================================================
  // TAB 5: ALERTS & SLA
  // ===========================================================================
  function renderAlertsTab() {
    const alerts = VG.computeAlerts(state);
    document.getElementById('badge-alerts-count').textContent = String(alerts.length);

    const listEl = document.getElementById('alerts-list');
    listEl.innerHTML = alerts
      .map((a) => {
        const col = a.severity === 'critical' ? 'red' : a.severity === 'high' ? 'orange' : 'amber';
        return `
          <div class="check-item">
            <div>
              <span class="badge badge-${col}" style="margin-right:0.35rem;">${esc(a.type.toUpperCase())}</span>
              <strong>${esc(a.title)}</strong>
              <div style="font-size:0.76rem;color:var(--text-muted);margin-top:0.15rem;">${esc(a.message)}</div>
            </div>
            ${
              a.invoiceId
                ? `<button type="button" class="btn btn-sm" data-alert-inv="${esc(a.invoiceId)}">Inspect</button>`
                : ''
            }
          </div>
        `;
      })
      .join('');

    listEl.querySelectorAll('[data-alert-inv]').forEach((btn) => {
      btn.addEventListener('click', () => {
        openInvoiceDetail(btn.getAttribute('data-alert-inv'));
      });
    });

    const n = state.settings.notifications;
    document.getElementById('digest-preview-box').innerHTML = `
      <div style="display:flex;flex-wrap:wrap;gap:0.6rem;margin-bottom:0.85rem;">
        <span class="badge ${n.email ? 'badge-emerald' : 'badge-slate'}">Email: ${n.email ? 'ON' : 'OFF'}</span>
        <span class="badge ${n.inApp ? 'badge-emerald' : 'badge-slate'}">In-App: ${n.inApp ? 'ON' : 'OFF'}</span>
        <span class="badge ${n.slack ? 'badge-emerald' : 'badge-slate'}">Slack (#ap-fraud-alerts): ${n.slack ? 'ON' : 'OFF'}</span>
        <span class="badge ${n.teams ? 'badge-emerald' : 'badge-slate'}">MS Teams: ${n.teams ? 'ON' : 'OFF'}</span>
      </div>
      <div class="doc-preview">
        <div><strong>[${esc(n.digestFrequency.toUpperCase())} SECURITY &amp; AP DIGEST — ${esc(state.referenceDate.slice(0, 10))}]</strong></div>
        <div>• Total Active Alerts: ${alerts.length}</div>
        <div>• High-Risk / Fraud Alerts: ${alerts.filter((a) => a.type === 'high_risk').length}</div>
        <div>• SLA Verification Breaches (&gt;${state.settings.slaHours}h): ${alerts.filter((a) => a.type === 'sla_breach').length}</div>
        <div>• Unverified Supplier Bank Changes: ${alerts.filter((a) => a.type === 'bank_change').length}</div>
        <div>• Overdue / Upcoming Due Invoices: ${alerts.filter((a) => a.type === 'overdue' || a.type === 'upcoming_due').length}</div>
      </div>
    `;
  }

  // ===========================================================================
  // TAB 6: ANALYTICS, AUDIT TRAIL, INTEGRATIONS & SETTINGS
  // ===========================================================================
  function renderGovernanceTab() {
    const an = VG.computeAnalytics(state);
    const cur = state.settings.baseCurrency;

    document.getElementById('analytics-summary').innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-bottom:0.8rem;">
        <div style="background:var(--bg-elevated);padding:0.7rem;border-radius:8px;">
          <div class="card-title">Fraud Caught &amp; Money Saved</div>
          <div style="font-size:1.3rem;font-weight:800;color:var(--success);">
            ${esc(VG.formatMoney(an.moneySaved, cur))}
          </div>
          <div style="font-size:0.75rem;color:var(--text-muted);">${an.fraudCaughtCount} fraudulent/suspicious invoices intercepted</div>
        </div>
        <div style="background:var(--bg-elevated);padding:0.7rem;border-radius:8px;">
          <div class="card-title">On-Time Payment Performance</div>
          <div style="font-size:1.3rem;font-weight:800;color:var(--accent);">${an.paymentPerformance.onTimeRatePercent}%</div>
          <div style="font-size:0.75rem;color:var(--text-muted);">On-time: ${an.paymentPerformance.paidOnTime} • Late: ${an.paymentPerformance.paidLate}</div>
        </div>
      </div>
      <div class="card-title">Verification Turnaround Time by Auditor</div>
      <div style="font-size:0.8rem;margin-bottom:0.65rem;">
        ${an.turnaroundByAuditor
          .map(
            (a) =>
              `<div style="display:flex;justify-content:space-between;padding:0.22rem 0;border-bottom:1px solid var(--border);">
                <span>${esc(a.auditor)} (${a.count} assigned)</span>
                <strong>${a.avgHours}h avg turnaround</strong>
              </div>`
          )
          .join('')}
      </div>
      <div class="card-title">Verification Turnaround Time by Supplier</div>
      <div style="font-size:0.8rem;margin-bottom:0.65rem;">
        ${(an.turnaroundBySupplier || [])
          .map(
            (s) =>
              `<div style="display:flex;justify-content:space-between;padding:0.22rem 0;border-bottom:1px solid var(--border);">
                <span>${esc(s.supplierName)} (${s.count} inv)</span>
                <strong>${s.avgHours}h avg turnaround</strong>
              </div>`
          )
          .join('')}
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;">
        <div>
          <div class="card-title">Top Suppliers by Volume</div>
          <div style="font-size:0.78rem;">
            ${(an.topSuppliersByVolume || [])
              .map(
                (s) =>
                  `<div style="display:flex;justify-content:space-between;padding:0.2rem 0;border-bottom:1px solid var(--border);">
                    <span>${esc(s.supplierName)}</span>
                    <strong class="mono">${esc(VG.formatMoney(s.totalAmount, cur))}</strong>
                  </div>`
              )
              .join('')}
          </div>
        </div>
        <div>
          <div class="card-title">Top Suppliers by Risk Score</div>
          <div style="font-size:0.78rem;">
            ${(an.topSuppliersByRisk || [])
              .map(
                (s) =>
                  `<div style="display:flex;justify-content:space-between;padding:0.2rem 0;border-bottom:1px solid var(--border);">
                    <span>${esc(s.supplierName)}</span>
                    <strong class="mono" style="color:${s.maxRiskScore >= 65 ? 'var(--danger)' : 'var(--text)'};">Risk ${s.maxRiskScore} (${s.flaggedCount} flagged)</strong>
                  </div>`
              )
              .join('')}
          </div>
        </div>
      </div>
    `;

    document.getElementById('integrations-box').innerHTML = `
      <div style="display:flex;flex-direction:column;gap:0.4rem;margin-bottom:0.75rem;">
        ${state.integrations
          .map(
            (intg) => `
            <div style="display:flex;justify-content:space-between;align-items:center;font-size:0.8rem;background:var(--bg-elevated);padding:0.4rem 0.65rem;border-radius:6px;">
              <span><strong>${esc(intg.name)}</strong> (${esc(intg.category)})</span>
              <span class="badge ${intg.status === 'connected' ? 'badge-emerald' : 'badge-amber'}">${esc(intg.status.toUpperCase())}</span>
            </div>
          `
          )
          .join('')}
      </div>
      <div style="display:flex;gap:0.4rem;align-items:center;">
        <input type="text" id="input-vat-lookup" value="DE812345678" placeholder="Enter EU VAT ID (e.g. DE812345678)" style="flex:1;" />
        <button type="button" class="btn btn-sm btn-primary" id="btn-vat-lookup">Lookup VIES VAT Registry</button>
      </div>
      <div id="vat-lookup-result" style="font-size:0.78rem;color:var(--text-muted);margin-top:0.35rem;"></div>
    `;

    document.getElementById('btn-vat-lookup').addEventListener('click', () => {
      const v = document.getElementById('input-vat-lookup').value.trim();
      const valid = /^[A-Z]{2}[A-Z0-9]{8,12}$/i.test(v);
      const matchSup = state.suppliers.find((s) => s.vatNumber.toLowerCase() === v.toLowerCase());
      document.getElementById('vat-lookup-result').innerHTML = valid
        ? `✓ VIES Format Valid (${esc(v.toUpperCase())}) — ${matchSup ? `Registered to ${esc(matchSup.name)} (${esc(matchSup.regNumber)})` : 'Active EU VAT Registration'}`
        : `✕ Invalid VAT number format (${esc(v)})`;
    });

    // Settings Box
    const s = state.settings;
    document.getElementById('settings-box').innerHTML = `
      <div class="filters-grid" style="margin-bottom:0;">
        <div class="filter-field">
          <label for="set-t1">Level 1 Approval Threshold (EUR)</label>
          <input type="number" id="set-t1" value="${s.approvalThresholds.level1}" />
        </div>
        <div class="filter-field">
          <label for="set-t2">Level 2 CFO Threshold (EUR)</label>
          <input type="number" id="set-t2" value="${s.approvalThresholds.level2}" />
        </div>
        <div class="filter-field">
          <label for="set-sla">Verification SLA (Hours)</label>
          <input type="number" id="set-sla" value="${s.slaHours}" />
        </div>
        <div class="filter-field">
          <label for="set-high-risk">High Risk Cutoff (0-100)</label>
          <input type="number" id="set-high-risk" value="${s.highRiskThreshold}" />
        </div>
        <div class="filter-field">
          <label for="set-sod">Segregation of Duties (SoD)</label>
          <select id="set-sod">
            <option value="true" ${s.enforceSegregationOfDuties ? 'selected' : ''}>Enforced (Approver ≠ Payer)</option>
            <option value="false" ${!s.enforceSegregationOfDuties ? 'selected' : ''}>Disabled</option>
          </select>
        </div>
        <div class="filter-field">
          <label for="set-gdpr">GDPR PII Masking (IBAN / Email)</label>
          <select id="set-gdpr">
            <option value="false" ${!s.gdprMaskPii ? 'selected' : ''}>Unmasked</option>
            <option value="true" ${s.gdprMaskPii ? 'selected' : ''}>Masked (••••)</option>
          </select>
        </div>
        <div class="filter-field" style="justify-content:flex-end;">
          <button type="button" class="btn btn-primary" id="btn-save-settings">Apply Risk &amp; Compliance Rules</button>
        </div>
      </div>
    `;

    document.getElementById('btn-save-settings').addEventListener('click', () => {
      s.approvalThresholds.level1 = Number(document.getElementById('set-t1').value) || 10000;
      s.approvalThresholds.level2 = Number(document.getElementById('set-t2').value) || 50000;
      s.slaHours = Number(document.getElementById('set-sla').value) || 48;
      s.highRiskThreshold = Number(document.getElementById('set-high-risk').value) || 65;
      s.enforceSegregationOfDuties = document.getElementById('set-sod').value === 'true';
      s.gdprMaskPii = document.getElementById('set-gdpr').value === 'true';
      if (typeof VG.refreshInvoicesAuditState === 'function') {
        VG.refreshInvoicesAuditState(state);
      }
      VG.appendAuditLog(state, {
        actorId: state.currentUser.id,
        actorName: state.currentUser.name,
        actorRole: state.currentUser.role,
        action: 'UPDATE_SETTINGS',
        entityType: 'settings',
        entityId: 'GLOBAL',
        summary: `Updated risk thresholds (L1: ${s.approvalThresholds.level1}, L2: ${s.approvalThresholds.level2}, SoD: ${s.enforceSegregationOfDuties})`
      });
      showToast('Updated risk thresholds, SoD rules, and GDPR settings');
      renderAll();
    });

    // Audit Log Table
    document.getElementById('audit-log-tbody').innerHTML = state.auditLog
      .slice()
      .reverse()
      .map(
        (entry) => `
        <tr>
          <td class="mono">${esc(entry.id)}</td>
          <td class="mono">${esc(entry.timestamp.slice(0, 19).replace('T', ' '))}</td>
          <td><strong>${esc(entry.actorName)}</strong> <span class="badge badge-slate">${esc(entry.actorRole)}</span></td>
          <td class="mono">${esc(entry.action)}</td>
          <td class="mono">${esc(entry.entityId)}</td>
          <td>${esc(entry.summary)}</td>
          <td class="mono" style="color:var(--teal);">${esc(entry.hash)}</td>
        </tr>
      `
      )
      .join('');
  }

  // ===========================================================================
  // TAB SWITCHING & GLOBAL RENDER
  // ===========================================================================
  function switchTab(tabId) {
    ui.activeTab = tabId;
    document.querySelectorAll('.nav-tab').forEach((btn) => {
      const isMatch = btn.getAttribute('data-tab') === tabId;
      btn.classList.toggle('active', isMatch);
      btn.setAttribute('aria-selected', isMatch ? 'true' : 'false');
    });
    document.querySelectorAll('.tab-panel').forEach((panel) => {
      panel.classList.toggle('active', panel.id === `panel-${tabId}`);
    });
    renderAll();
  }

  function renderAll() {
    const lang = state.settings.language || 'en';
    document.getElementById('app-title').textContent = I18N[lang].title;
    document.getElementById('app-subtitle').textContent = I18N[lang].subtitle;

    syncDynamicFilterOptions();
    renderOverview();
    renderInvoicesTable();
    renderPaymentsTab();
    renderSuppliersTab();
    renderAlertsTab();
    renderGovernanceTab();
  }

  // ===========================================================================
  // EVENT LISTENERS BINDING
  // ===========================================================================
  function bindEvents() {
    // Tabs
    document.querySelectorAll('.nav-tab').forEach((btn) => {
      btn.addEventListener('click', () => switchTab(btn.getAttribute('data-tab')));
    });

    // Header Controls
    document.getElementById('select-user').addEventListener('change', (e) => {
      const found = state.users.find((u) => u.id === e.target.value);
      if (found) {
        state.currentUser = found;
        showToast(`Switched active actor to ${found.name} (${found.role.toUpperCase()})`);
        renderAll();
      }
    });

    document.getElementById('select-currency').addEventListener('change', (e) => {
      state.settings.baseCurrency = e.target.value;
      renderAll();
    });

    document.getElementById('select-lang').addEventListener('change', (e) => {
      state.settings.language = e.target.value;
      renderAll();
    });

    document.getElementById('btn-theme-toggle').addEventListener('click', () => {
      const html = document.documentElement;
      const next = html.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      html.setAttribute('data-theme', next);
      state.settings.darkMode = next === 'dark';
    });

    const toggleSidebarBtn = document.getElementById('btn-toggle-sidebar');
    if (toggleSidebarBtn) {
      toggleSidebarBtn.addEventListener('click', () => {
        const sb = document.getElementById('app-sidebar');
        if (sb) sb.classList.toggle('collapsed');
      });
    }

    const focusSearchBtn = document.getElementById('btn-focus-search');
    if (focusSearchBtn) {
      focusSearchBtn.addEventListener('click', () => {
        switchTab('invoices');
        const searchEl = document.getElementById('f-search');
        if (searchEl && typeof searchEl.focus === 'function') searchEl.focus();
      });
    }

    // Filter inputs
    const filterBindings = [
      ['f-search', 'search'],
      ['f-status', 'status'],
      ['f-supplier', 'supplierId'],
      ['f-risk', 'riskLevel'],
      ['f-dept', 'department'],
      ['f-assignee', 'assignee'],
      ['f-method', 'paymentMethod'],
      ['f-date-from', 'dateFrom'],
      ['f-date-to', 'dateTo'],
      ['f-amt-min', 'amountMin'],
      ['f-amt-max', 'amountMax']
    ];
    for (const [elId, key] of filterBindings) {
      const el = document.getElementById(elId);
      el.addEventListener('input', () => {
        ui.query.preset = '';
        ui.activeViewId = '';
        ui.query[key] = el.value;
        renderInvoicesTable();
      });
    }

    // Table sorting
    document.querySelectorAll('#invoices-table th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const col = th.getAttribute('data-sort');
        if (ui.query.sortBy === col) {
          ui.query.sortDir = ui.query.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
          ui.query.sortBy = col;
          ui.query.sortDir = 'asc';
        }
        renderInvoicesTable();
      });
    });

    // Select All checkbox
    document.getElementById('chk-select-all').addEventListener('change', (e) => {
      const visible = VG.queryInvoices(state, ui.query);
      if (e.target.checked) {
        visible.forEach((i) => ui.selectedInvoiceIds.add(i.id));
      } else {
        visible.forEach((i) => ui.selectedInvoiceIds.delete(i.id));
      }
      document.getElementById('selected-count-label').textContent = `${ui.selectedInvoiceIds.size} selected`;
      renderInvoicesTable();
    });

    // Bulk actions
    function runBulk(action, payload = {}) {
      if (ui.selectedInvoiceIds.size === 0) {
        showToast('Select at least one invoice first', true);
        return;
      }
      let ok = 0;
      let lastErr = '';
      for (const id of ui.selectedInvoiceIds) {
        try {
          VG.performWorkflowAction(state, id, action, payload);
          ok += 1;
        } catch (err) {
          lastErr = err.message;
        }
      }
      if (ok > 0) {
        showToast(`Executed "${action}" on ${ok} invoice(s)${lastErr ? ` (Some skipped: ${lastErr})` : ''}`);
      } else {
        showToast(lastErr || 'Bulk action failed', true);
      }
      renderAll();
    }

    document.getElementById('btn-bulk-checks').addEventListener('click', () => runBulk('run_checks'));
    document.getElementById('btn-bulk-assign').addEventListener('click', () =>
      runBulk('assign', { assignee: 'Sophie Mercier' })
    );
    document.getElementById('btn-bulk-approve').addEventListener('click', () => runBulk('approve'));
    document.getElementById('btn-bulk-hold').addEventListener('click', () =>
      runBulk('hold', { reason: 'Bulk hold for review' })
    );
    document.getElementById('btn-bulk-flag').addEventListener('click', () =>
      runBulk('flag', { reason: 'Flagged in bulk audit' })
    );

    document.getElementById('btn-save-view').addEventListener('click', () => {
      const name = `Custom View #${state.savedViews.length + 1}`;
      const id = `custom_${Date.now()}`;
      state.savedViews.push({ id, name, query: { ...ui.query } });
      ui.activeViewId = id;
      saveViewsToStorage();
      showToast(`Saved filter view "${name}"`);
      renderSavedViewsBar();
    });

    document.getElementById('btn-reset-filters').addEventListener('click', () => {
      resetQueryFilters();
      renderAll();
    });

    // Exports
    document.getElementById('btn-export-csv').addEventListener('click', () => {
      const rows = VG.queryInvoices(state, ui.query);
      const csv = VG.exportInvoicesCSV(rows);
      downloadFile('vaultgard-invoices.csv', csv, 'text/csv;charset=utf-8');
      showToast(`Exported ${rows.length} invoices to CSV`);
    });

    document.getElementById('btn-export-xls').addEventListener('click', () => {
      const rows = VG.queryInvoices(state, ui.query);
      const csv = VG.exportInvoicesCSV(rows);
      downloadFile('vaultgard-invoices.xls', csv, 'application/vnd.ms-excel');
      showToast(`Exported ${rows.length} invoices to Excel (.xls)`);
    });

    document.getElementById('btn-export-pdf').addEventListener('click', () => {
      window.print();
    });

    // SEPA Batch creation button
    document.getElementById('btn-create-sepa-batch').addEventListener('click', () => {
      const eligibleIds = state.invoices
        .filter((inv) => VG.canPayInvoice(state, inv, null, { forBatch: true }).allowed)
        .map((inv) => inv.id);
      try {
        const batch = VG.createPaymentBatch(state, eligibleIds, {
          executionDate: state.referenceDate.slice(0, 10)
        });
        showToast(`Created SEPA Batch ${batch.id} (${batch.invoiceCount} invoices)`);
        renderAll();
      } catch (err) {
        showToast(err.message, true);
      }
    });

    // Audit chain verification & compliance export
    document.getElementById('btn-verify-audit-chain').addEventListener('click', () => {
      const res = VG.verifyAuditLogIntegrity(state.auditLog);
      if (res.valid) {
        showToast(`✓ Cryptographic hash chain verified intact across ${res.count} audit records`);
      } else {
        showToast(`✕ Audit chain integrity broken at index ${res.brokenAtIndex}`, true);
      }
    });

    document.getElementById('btn-export-compliance').addEventListener('click', () => {
      const report = JSON.stringify(
        {
          generatedAt: new Date().toISOString(),
          integrity: VG.verifyAuditLogIntegrity(state.auditLog),
          auditLog: state.auditLog
        },
        null,
        2
      );
      downloadFile('vaultgard-compliance-report.json', report, 'application/json');
      showToast('Exported compliance report JSON');
    });

    // Dialog Close & Open
    document.getElementById('btn-close-detail').addEventListener('click', () => {
      const dlg = document.getElementById('dialog-invoice-detail');
      if (dlg.open) dlg.close();
    });

    const ingestDlg = document.getElementById('dialog-ingest');
    document.getElementById('btn-open-ingest').addEventListener('click', () => {
      if (typeof ingestDlg.showModal === 'function') ingestDlg.showModal();
      else ingestDlg.setAttribute('open', 'open');
    });
    document.getElementById('btn-close-ingest').addEventListener('click', () => {
      if (ingestDlg.open) ingestDlg.close();
    });

    // OCR Parser & Scam Preset in Ingest Modal
    document.getElementById('btn-parse-ocr').addEventListener('click', () => {
      const raw = document.getElementById('ocr-raw-input').value;
      const parsed = VG.parseOcrText(raw);
      document.getElementById('ing-number').value = parsed.invoiceNumber;
      document.getElementById('ing-supplier').value = parsed.supplierName;
      document.getElementById('ing-vat').value = parsed.vatNumber;
      document.getElementById('ing-iban').value = parsed.iban;
      document.getElementById('ing-amount').value = parsed.amount;
      document.getElementById('ing-currency').value = parsed.currency;
      document.getElementById('ing-po').value = parsed.poNumber;
      document.getElementById('ing-due').value = parsed.dueDate;
      document.getElementById('ing-email').value = parsed.senderEmail;
      showToast('OCR fields extracted from raw invoice text');
    });

    document.getElementById('btn-load-scam-preset').addEventListener('click', () => {
      const scamText = `Invoice Number: CS-2026-999
Supplier: CloudScale Infrastructure GmbH
VAT: DE812345678
IBAN: DE99000099998888777766
Total: 9950.00
Currency: EUR
PO: 
Issue Date: 2026-10-10
Due Date: 2026-10-12
Email: urgent@c1oudscale.de`;
      document.getElementById('ocr-raw-input').value = scamText;
      document.getElementById('btn-parse-ocr').click();
    });

    document.getElementById('form-ingest-invoice').addEventListener('submit', (e) => {
      e.preventDefault();
      try {
        const inv = VG.ingestInvoice(
          state,
          {
            invoiceNumber: document.getElementById('ing-number').value.trim(),
            supplierName: document.getElementById('ing-supplier').value.trim(),
            vatNumber: document.getElementById('ing-vat').value.trim(),
            iban: document.getElementById('ing-iban').value.trim(),
            amount: Number(document.getElementById('ing-amount').value),
            currency: document.getElementById('ing-currency').value,
            poNumber: document.getElementById('ing-po').value.trim(),
            dueDate: document.getElementById('ing-due').value,
            senderEmail: document.getElementById('ing-email').value.trim()
          },
          'ocr_upload'
        );
        if (ingestDlg.open) ingestDlg.close();
        showToast(
          `Ingested ${inv.invoiceNumber} -> Status: ${VG.STATUS_META[inv.status].label} (Risk: ${inv.riskLevel.toUpperCase()} / ${inv.riskScore})`
        );
        renderAll();
        openInvoiceDetail(inv.id);
      } catch (err) {
        showToast(err.message, true);
      }
    });
  }

  initSelectors();
  bindEvents();
  renderAll();
})();
