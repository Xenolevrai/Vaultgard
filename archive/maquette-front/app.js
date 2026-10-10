// Vaultgard Dashboard UI Controller
(function () {
  'use strict';

  const VG = window.Vaultgard;
  if (!VG) return;

  const state = VG.createInitialState();
  const ui = {
    activeTab: 'overview',
    sankeyMode: 'lifecycle', // 'lifecycle' or 'supplier'
    filterInvoiceIds: null, // Set of invoice IDs when filtered from Sankey
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

  function initSelectors() {
    loadSavedViewsFromStorage();

    const statusSel = document.getElementById('f-status');
    if (statusSel) {
      statusSel.innerHTML =
        `<option value="all">All Statuses (10)</option>` +
        VG.ALL_STATUS_KEYS.map((k) => `<option value="${esc(k)}">${esc(VG.STATUS_META[k].label)}</option>`).join('');
    }

    syncDynamicFilterOptions();
  }

  // ===========================================================================
  // DIALOG HELPERS (ON-DEMAND SECONDARY DETAILS)
  // ===========================================================================
  function openDialog(dlgId) {
    const dlg = document.getElementById(dlgId);
    if (!dlg) return;
    if (typeof dlg.showModal === 'function') {
      dlg.showModal();
    } else {
      dlg.open = true;
      dlg.setAttribute('open', 'open');
    }
  }

  function closeDialog(dlgId) {
    const dlg = document.getElementById(dlgId);
    if (!dlg) return;
    if (typeof dlg.close === 'function') {
      dlg.close();
    } else {
      dlg.open = false;
      dlg.removeAttribute('open');
    }
  }

  // ===========================================================================
  // TAB 1: OVERVIEW & KPIs, SANKEY & COMPANION CHARTS
  // ===========================================================================
  function renderOverview() {
    const kpis = VG.computeKPIs(state);
    const cur = kpis.baseCurrency;
    const fmt = (val) => VG.formatMoney(val, cur);

    // 1. Top KPI Summary Cards (At most 4 clean, spacious cards)
    const topCards = document.getElementById('kpi-top-cards');
    if (topCards) {
      topCards.innerHTML = `
        <div class="card">
          <div class="card-title">Ready to Pay</div>
          <div class="kpi-value" style="color: var(--teal) !important;">${esc(fmt(kpis.readyToPay.thisMonth))}</div>
          <div class="kpi-sub">
            <span>${kpis.readyToPay.count} invoices ready for disbursement</span>
          </div>
        </div>

        <div class="card">
          <div class="card-title">In Audit Queue</div>
          <div class="kpi-value" style="color: var(--warning) !important;">${esc(fmt(kpis.pendingVerification.totalAmount))}</div>
          <div class="kpi-sub">
            <span>${kpis.pendingVerification.count} invoices pending review</span>
          </div>
        </div>

        <div class="card">
          <div class="card-title">Fraud Prevented</div>
          <div class="kpi-value" style="color: var(--danger) !important;">${esc(fmt(kpis.flagged.moneySaved))}</div>
          <div class="kpi-sub">
            <span>${kpis.flagged.rejectedCount} scam(s) intercepted</span>
          </div>
        </div>

        <div class="card">
          <div class="card-title">Total Pipeline Volume</div>
          <div class="kpi-value">${esc(fmt(kpis.totalAmount))}</div>
          <div class="kpi-sub">
            <span>${kpis.totalInvoices} active invoices tracked</span>
          </div>
        </div>
      `;
    }

    // 2. Interactive Dual-Mode Sankey Diagram
    renderSankey();

    // 3. At most 2 Clean Companion SVG Charts
    renderMonthlyTrendsChart(kpis);
    renderSupplierTrendsChart(kpis);

    // 4. Full Status Breakdown (10 Lifecycle Stages inside collapsible details)
    const statusGrid = document.getElementById('kpi-status-grid');
    if (statusGrid) {
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
          const statusInput = document.getElementById('f-status');
          if (statusInput) statusInput.value = st;
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
    }
  }

  // ===========================================================================
  // INTERACTIVE DUAL-MODE SANKEY DIAGRAM RENDERING
  // ===========================================================================
  function renderSankey() {
    const wrapper = document.getElementById('sankey-diagram-wrapper');
    if (!wrapper) return;

    const theme = document.documentElement.getAttribute('data-theme') || 'dark';
    const sankeyData = VG.computeSankeyData(state, { mode: ui.sankeyMode, metric: 'amount' });
    const svgMarkup = VG.renderSankeySVG(sankeyData, { theme, width: 920, height: 340 });

    // Inject SVG preserving svg id if needed
    wrapper.innerHTML = svgMarkup.includes('id="sankey-svg"')
      ? svgMarkup
      : svgMarkup.replace('<svg ', '<svg id="sankey-svg" ');

    // Update button active states
    const isLifecycle = ui.sankeyMode === 'lifecycle';
    const btnLife = document.getElementById('btn-sankey-lifecycle');
    const btnDept = document.getElementById('btn-sankey-dept');
    const btnSup = document.getElementById('btn-sankey-supplier');
    if (btnLife) btnLife.classList.toggle('active', isLifecycle);
    if (btnDept) btnDept.classList.toggle('active', !isLifecycle);
    if (btnSup) btnSup.classList.toggle('active', !isLifecycle);

    // Wire up interactive click and hover handlers on nodes and links
    const container = document.getElementById('sankey-container');
    const tooltip = document.getElementById('sankey-tooltip');

    wrapper.querySelectorAll('.sankey-link, .sankey-node-group, .sankey-node-rect').forEach((el) => {
      const idsStr =
        el.getAttribute('data-invoice-ids') ||
        (el.parentElement && el.parentElement.getAttribute('data-invoice-ids')) ||
        '';

      // Hover: show tooltip
      el.addEventListener('mouseenter', (evt) => {
        const titleEl = el.querySelector('title') || (el.parentElement && el.parentElement.querySelector('title'));
        const text = titleEl ? titleEl.textContent : (el.getAttribute('data-node-id') || 'Flow item');
        if (tooltip) {
          tooltip.innerHTML = `<strong>${esc(text)}</strong><div style="font-size:0.7rem;color:var(--text-muted);margin-top:2px;">Click to filter related invoices in queue</div>`;
          tooltip.style.display = 'block';
        }
      });

      el.addEventListener('mousemove', (evt) => {
        if (tooltip && container && typeof evt.clientX === 'number' && container.getBoundingClientRect) {
          const rect = container.getBoundingClientRect();
          const x = evt.clientX - rect.left + 14;
          const y = evt.clientY - rect.top + 14;
          tooltip.style.left = `${Math.max(8, Math.min(rect.width - 240, x))}px`;
          tooltip.style.top = `${Math.max(8, y)}px`;
        }
      });

      el.addEventListener('mouseleave', () => {
        if (tooltip) tooltip.style.display = 'none';
      });

      // Click: filter invoices by invoiceIds and switch to Invoices tab
      el.addEventListener('click', (evt) => {
        evt.stopPropagation();
        const ids = idsStr.split(',').filter(Boolean);
        if (ids.length > 0) {
          resetQueryFilters();
          ui.filterInvoiceIds = new Set(ids);
          switchTab('invoices');
          showToast(`Filtered ${ids.length} invoice(s) from flow diagram`);
        }
      });
    });
  }

  // ===========================================================================
  // COMPANION CHARTS: MONTHLY VOLUME & SUPPLIER VOLUME/RISK
  // ===========================================================================
  function renderMonthlyTrendsChart(kpis) {
    const container = document.getElementById('chart-monthly-trends');
    if (!container) return;
    const data = (kpis.trends && kpis.trends.byMonth) || [];
    const cur = kpis.baseCurrency || 'EUR';
    const width = 460;
    const height = 220;
    const pad = { top: 32, right: 24, bottom: 36, left: 54 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;

    if (data.length === 0) {
      container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" class="chart-svg"><text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="var(--text-muted)">No monthly trend data</text></svg>`;
      return;
    }

    const maxVal = Math.max(1, ...data.map((m) => m.totalAmount)) * 1.15;
    const bandW = plotW / data.length;
    const barW = Math.min(48, Math.max(16, bandW * 0.52));

    // Grid lines
    const gridLines = [];
    const yTicks = [0, maxVal * 0.5, maxVal];
    yTicks.forEach((val) => {
      const y = pad.top + plotH - (val / maxVal) * plotH;
      const label = VG.formatMoney(val, cur).replace(/,00|\.00/, '');
      gridLines.push(`
        <line x1="${pad.left}" y1="${y.toFixed(1)}" x2="${(width - pad.right).toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(--border, rgba(0,0,0,0.08))" stroke-dasharray="3 3"/>
        <text x="${(pad.left - 8).toFixed(1)}" y="${(y + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--text-muted)">${esc(label)}</text>
      `);
    });

    const bars = data.map((m, idx) => {
      const x = pad.left + idx * bandW + (bandW - barW) / 2;
      const cleanAmt = m.verifiedAmount + m.paidAmount;
      const cleanH = (cleanAmt / maxVal) * plotH;
      const flagH = (m.flaggedAmount / maxVal) * plotH;
      const totalH = (m.totalAmount / maxVal) * plotH;
      const yBase = pad.top + plotH;
      const yTotal = yBase - totalH;

      const cleanRect = cleanH > 0
        ? `<rect x="${x.toFixed(1)}" y="${(yBase - cleanH).toFixed(1)}" width="${barW.toFixed(1)}" height="${cleanH.toFixed(1)}" fill="var(--teal, #14b8a6)" rx="3" ry="3">
             <title>${esc(m.month)} Approved/Paid: ${esc(VG.formatMoney(cleanAmt, cur))}</title>
           </rect>`
        : '';

      const flagRect = flagH > 0
        ? `<rect x="${x.toFixed(1)}" y="${(yBase - cleanH - flagH).toFixed(1)}" width="${barW.toFixed(1)}" height="${flagH.toFixed(1)}" fill="var(--danger, #ef4444)" rx="3" ry="3">
             <title>${esc(m.month)} Flagged/Rejected: ${esc(VG.formatMoney(m.flaggedAmount, cur))}</title>
           </rect>`
        : '';

      const labelX = x + barW / 2;
      const valText = `<text x="${labelX.toFixed(1)}" y="${(yTotal - 6).toFixed(1)}" text-anchor="middle" font-size="11" font-weight="600" fill="var(--text)">${esc(VG.formatMoney(m.totalAmount, cur).replace(/,00|\.00/, ''))}</text>`;
      const monthText = `<text x="${labelX.toFixed(1)}" y="${(yBase + 18).toFixed(1)}" text-anchor="middle" font-size="11" fill="var(--text-secondary)">${esc(m.month)}</text>`;

      return cleanRect + flagRect + valText + monthText;
    }).join('');

    // Legend at top
    const legend = `
      <g transform="translate(${(width - 210).toFixed(1)}, 14)">
        <rect x="0" y="0" width="10" height="10" rx="2" fill="var(--teal, #14b8a6)"/>
        <text x="14" y="9" font-size="10" fill="var(--text-secondary)">Approved / Paid</text>
        <rect x="110" y="0" width="10" height="10" rx="2" fill="var(--danger, #ef4444)"/>
        <text x="124" y="9" font-size="10" fill="var(--text-secondary)">Flagged / Risk</text>
      </g>
    `;

    container.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" class="chart-svg" role="img" aria-label="Monthly Invoice Volume & Status Breakdown">
        ${gridLines.join('')}
        ${bars}
        ${legend}
      </svg>
    `;
  }

  function renderSupplierTrendsChart(kpis) {
    const container = document.getElementById('chart-supplier-trends');
    if (!container) return;
    const suppliers = (kpis.trends && kpis.trends.bySupplier ? kpis.trends.bySupplier.slice(0, 5) : []);
    const cur = kpis.baseCurrency || 'EUR';
    const width = 460;
    const height = 220;
    const pad = { top: 24, right: 90, bottom: 18, left: 130 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;

    if (suppliers.length === 0) {
      container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" class="chart-svg"><text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="var(--text-muted)">No supplier data available</text></svg>`;
      return;
    }

    const maxVal = Math.max(1, ...suppliers.map((s) => s.totalAmount)) * 1.08;
    const rowH = plotH / suppliers.length;
    const barH = Math.min(22, rowH * 0.58);

    const rows = suppliers.map((s, idx) => {
      const y = pad.top + idx * rowH + (rowH - barH) / 2;
      const barW = Math.max(4, (s.totalAmount / maxVal) * plotW);
      const isRisky = s.maxRiskScore >= 65 || s.flaggedCount > 0;
      const fillColor = isRisky ? 'var(--danger, #ef4444)' : 'var(--accent, #0284c7)';
      const truncatedName = s.supplierName.length > 17 ? s.supplierName.slice(0, 16) + '…' : s.supplierName;

      // Supplier label on left
      const nameLabel = `
        <text x="${(pad.left - 10).toFixed(1)}" y="${(y + barH / 2 + 4).toFixed(1)}" text-anchor="end" font-size="11" font-weight="500" fill="var(--text)" title="${esc(s.supplierName)}">
          ${esc(truncatedName)}
        </text>
      `;

      // Background track
      const track = `
        <rect x="${pad.left}" y="${y.toFixed(1)}" width="${plotW.toFixed(1)}" height="${barH.toFixed(1)}" fill="var(--bg-elevated, rgba(0,0,0,0.04))" rx="4" ry="4"/>
      `;

      // Filled bar
      const bar = `
        <rect x="${pad.left}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${barH.toFixed(1)}" fill="${fillColor}" rx="4" ry="4">
          <title>${esc(s.supplierName)}: ${esc(VG.formatMoney(s.totalAmount, cur))} (Max Risk: ${s.maxRiskScore}, Flagged: ${s.flaggedCount})</title>
        </rect>
      `;

      // Amount label on right
      const riskIndicator = isRisky ? ' ⚠' : '';
      const valLabel = `
        <text x="${(pad.left + barW + 8).toFixed(1)}" y="${(y + barH / 2 + 4).toFixed(1)}" text-anchor="start" font-size="11" font-weight="600" fill="${isRisky ? 'var(--danger, #ef4444)' : 'var(--text-secondary)'}">
          ${esc(VG.formatMoney(s.totalAmount, cur).replace(/,00|\.00/, ''))}${riskIndicator}
        </text>
      `;

      return nameLabel + track + bar + valLabel;
    }).join('');

    container.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" class="chart-svg" role="img" aria-label="Top Suppliers Volume and Risk">
        ${rows}
      </svg>
    `;
  }

  // ===========================================================================
  // TAB 2: INVOICES LIST, FILTERS, SAVED VIEWS & BULK ACTIONS
  // ===========================================================================
  function renderSavedViewsBar() {
    const bar = document.getElementById('saved-views-bar');
    if (!bar) return;
    const views = state.savedViews;
    bar.innerHTML = `
      <div class="saved-views-chips">
        ${views
          .map(
            (v) => `
          <button type="button" class="view-chip${v.id === ui.activeViewId ? ' active' : ''}" data-view-id="${esc(v.id)}">
            ${esc(v.name)}
            ${
              v.id.startsWith('custom_')
                ? `<span class="chip-del" data-del-view="${esc(v.id)}" title="Delete view">&times;</span>`
                : ''
            }
          </button>
        `
          )
          .join('')}
      </div>
    `;

    bar.querySelectorAll('[data-view-id]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        if (e.target.classList.contains('chip-del')) return;
        const vid = btn.getAttribute('data-view-id');
        const viewObj = state.savedViews.find((v) => v.id === vid);
        if (!viewObj) return;
        ui.activeViewId = vid;
        ui.filterInvoiceIds = null;
        ui.query = { ...ui.query, ...viewObj.query };
        syncFilterInputsFromQuery();
        renderInvoicesTable();
      });
    });

    bar.querySelectorAll('[data-del-view]').forEach((delBtn) => {
      delBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const vid = delBtn.getAttribute('data-del-view');
        state.savedViews = state.savedViews.filter((v) => v.id !== vid);
        if (ui.activeViewId === vid) {
          ui.activeViewId = 'all';
          resetQueryFilters();
        }
        saveViewsToStorage();
        showToast('Deleted saved view');
        renderSavedViewsBar();
      });
    });
  }

  function resetQueryFilters() {
    ui.activeViewId = 'all';
    ui.filterInvoiceIds = null;
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
    const elSearch = document.getElementById('f-search');
    if (elSearch) elSearch.value = ui.query.search || '';
    const elStatus = document.getElementById('f-status');
    if (elStatus) elStatus.value = ui.query.status || 'all';
    const elSupplier = document.getElementById('f-supplier');
    if (elSupplier) elSupplier.value = ui.query.supplierId || 'all';
    const elRisk = document.getElementById('f-risk');
    if (elRisk) elRisk.value = ui.query.riskLevel || 'all';
    const elDept = document.getElementById('f-dept');
    if (elDept) elDept.value = ui.query.department || 'all';
    const elAssignee = document.getElementById('f-assignee');
    if (elAssignee) elAssignee.value = ui.query.assignee || 'all';
    const elMethod = document.getElementById('f-method');
    if (elMethod) elMethod.value = ui.query.paymentMethod || 'all';
    const elDateFrom = document.getElementById('f-date-from');
    if (elDateFrom) elDateFrom.value = ui.query.dateFrom || '';
    const elDateTo = document.getElementById('f-date-to');
    if (elDateTo) elDateTo.value = ui.query.dateTo || '';
    const elAmtMin = document.getElementById('f-amt-min');
    if (elAmtMin) elAmtMin.value = ui.query.amountMin || '';
    const elAmtMax = document.getElementById('f-amt-max');
    if (elAmtMax) elAmtMax.value = ui.query.amountMax || '';
  }

  function renderInvoicesTable() {
    renderSavedViewsBar();
    let filtered = VG.queryInvoices(state, ui.query);
    if (ui.filterInvoiceIds && ui.filterInvoiceIds.size > 0) {
      filtered = filtered.filter((i) => ui.filterInvoiceIds.has(i.id));
    }
    const nowStr = state.referenceDate.slice(0, 10);
    const badgeInvoices = document.getElementById('badge-invoices-count');
    if (badgeInvoices) badgeInvoices.textContent = String(filtered.length);

    const tbody = document.getElementById('invoices-tbody');
    if (!tbody) return;

    if (filtered.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; padding: 2rem; color: var(--text-muted);">No invoices match the current filters.</td></tr>`;
      return;
    }

    // Render exactly 7 columns
    tbody.innerHTML = filtered
      .map((inv) => {
        const isOverdue =
          inv.dueDate < nowStr && inv.status !== VG.STATUSES.PAID && inv.status !== VG.STATUSES.REJECTED;
        const checked = ui.selectedInvoiceIds.has(inv.id) ? 'checked' : '';
        const overdueBadge = isOverdue
          ? '<span class="badge badge-red" style="margin-left:0.25rem;">OVERDUE</span>'
          : '';
        const statusBadge = renderStatusBadge(inv.status);
        const riskPill = renderRiskBadge(inv.riskLevel, inv.riskScore);

        return `
          <tr data-inv-row="${esc(inv.id)}" style="cursor: pointer;">
            <td style="width: 42px;"><input type="checkbox" class="chk-inv" data-id="${esc(inv.id)}" ${checked} aria-label="Select ${esc(inv.invoiceNumber)}" /></td>
            <td class="mono"><strong>${esc(inv.invoiceNumber)}</strong><br><small class="text-muted">${esc(inv.id)}</small></td>
            <td><strong>${esc(inv.supplierName)}</strong></td>
            <td class="mono"><strong>${esc(VG.formatMoney(inv.amount, inv.currency))}</strong></td>
            <td class="mono">${esc(inv.dueDate)}${overdueBadge}</td>
            <td>${statusBadge} ${riskPill}</td>
            <td style="text-align: right;">
              <button type="button" class="btn btn-sm btn-primary" data-inspect-id="${esc(inv.id)}">Inspect</button>
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
        const countLabel = document.getElementById('selected-count-label');
        if (countLabel) countLabel.textContent = `${ui.selectedInvoiceIds.size} selected`;
      });
    });

    tbody.querySelectorAll('tr[data-inv-row]').forEach((tr) => {
      tr.addEventListener('click', (e) => {
        if (e.target.closest('input[type="checkbox"]') || e.target.closest('button')) return;
        const invId = tr.getAttribute('data-inv-row');
        if (invId) openInvoiceDetail(invId);
      });
    });

    tbody.querySelectorAll('[data-inspect-id]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        openInvoiceDetail(btn.getAttribute('data-inspect-id'));
      });
    });
  }

  // ===========================================================================
  // INVOICE DETAIL MODAL (FULL 9-POINT CHECKLIST & WORKFLOW)
  // ===========================================================================
  function openInvoiceDetail(invoiceId) {
    ui.activeDetailInvoiceId = invoiceId;
    renderInvoiceDetailModal();
    openDialog('dialog-invoice-detail');
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

    const titleEl = document.getElementById('detail-dialog-title');
    if (titleEl) {
      titleEl.innerHTML = `${esc(inv.invoiceNumber)} — ${esc(inv.supplierName)} ${renderStatusBadge(inv.status)} ${renderRiskBadge(inv.riskLevel, inv.riskScore)}`;
    }
    const subEl = document.getElementById('detail-dialog-subtitle');
    if (subEl) {
      subEl.textContent = `ID: ${inv.id} • Department: ${inv.department} • Entity: ${inv.entity} • Approval Levels: ${curApprovals}/${reqLevels} • Active Actor: ${state.currentUser.name} (${state.currentUser.role})`;
    }

    const body = document.getElementById('detail-dialog-body');
    if (!body) return;

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

          <div style="margin-top: 1rem;">
            <div class="card-title">Supporting Documents &amp; Attachments</div>
            <div style="display:flex;flex-direction:column;gap:0.35rem;font-size:0.8rem;">
              ${(inv.attachments || [])
                .map(
                  (att) => `
                <div style="display:flex;justify-content:space-between;background:var(--bg-elevated);padding:0.4rem 0.6rem;border-radius:6px;">
                  <span>📎 ${esc(att.name)} (${esc(att.type)})</span>
                  <span style="color:var(--text-muted);font-size:0.75rem;">${esc(att.uploadedAt.slice(0, 10))}</span>
                </div>
              `
                )
                .join('')}
              <div style="margin-top:0.35rem;">
                <button type="button" class="btn btn-sm" id="btn-detail-attach">+ Attach Supporting File</button>
              </div>
            </div>
          </div>

          <div style="margin-top: 1rem;">
            <div class="card-title">Internal Audit Comments &amp; Notes</div>
            <div style="display:flex;flex-direction:column;gap:0.4rem;font-size:0.8rem;margin-bottom:0.5rem;">
              ${(inv.comments || [])
                .map(
                  (c) => `
                <div style="background:var(--bg-elevated);padding:0.5rem 0.65rem;border-radius:6px;">
                  <div style="display:flex;justify-content:space-between;color:var(--text-muted);font-size:0.72rem;margin-bottom:0.2rem;">
                    <strong>${esc(c.author)} (${esc(c.role)})</strong>
                    <span>${esc(c.timestamp.slice(0, 16).replace('T', ' '))}</span>
                  </div>
                  <div>${esc(c.text)}</div>
                </div>
              `
                )
                .join('')}
            </div>
            <div style="display:flex;gap:0.5rem;">
              <input type="text" id="input-detail-comment" placeholder="Add an internal audit note..." style="flex:1;" />
              <button type="button" class="btn btn-sm btn-primary" id="btn-detail-comment">Post Note</button>
            </div>
          </div>
        </div>

        <!-- Right Column: 9-Point Fraud Checklist, Timeline & Actions -->
        <div>
          <div class="card-title">9-Point Fraud &amp; Compliance Audit Checklist</div>
          <div class="checklist-list" style="margin-bottom: 1.25rem;">
            ${inv.checklist
              .map((check) => {
                const statusBadge =
                  check.status === 'pass'
                    ? '<span class="badge badge-emerald">✓ PASS</span>'
                    : check.status === 'fail'
                    ? '<span class="badge badge-red">✕ FAIL</span>'
                    : check.status === 'warning'
                    ? '<span class="badge badge-amber">⚠ WARN</span>'
                    : '<span class="badge badge-slate">⏳ PENDING</span>';

                return `
                  <div class="check-item">
                    <div style="flex:1;">
                      <div style="display:flex;align-items:center;gap:0.5rem;">
                        <strong>${esc(check.id)}. ${esc(check.name)}</strong>
                        ${statusBadge}
                      </div>
                      <div class="check-desc">${esc(check.description)}</div>
                      <div class="check-details">${esc(check.details || 'Check not yet evaluated.')}</div>
                    </div>
                  </div>
                `;
              })
              .join('')}
          </div>

          <!-- Workflow Actions & Phone Callback Verification -->
          <div class="card" style="margin-bottom: 1.25rem;">
            <div class="card-title">Auditor &amp; Approver Actions</div>
            <div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:0.75rem;">
              <button type="button" class="btn btn-sm btn-primary" data-wf="run_checks">Run 9-Point Checks</button>
              <button type="button" class="btn btn-sm" data-wf="callback_verify">📞 Log Out-of-Band Phone Callback</button>
              <button type="button" class="btn btn-sm btn-success" data-wf="approve">✓ Approve</button>
              <button type="button" class="btn btn-sm" data-wf="hold">⏸ Hold</button>
              <button type="button" class="btn btn-sm" data-wf="flag">🚩 Flag Suspicious</button>
              <button type="button" class="btn btn-sm btn-danger" data-wf="reject">✕ Reject (Confirmed Fraud)</button>
            </div>
            <div style="font-size:0.78rem;color:var(--text-muted);">
              <label for="input-wf-note" style="display:block;margin-bottom:0.2rem;">Action reason / audit note:</label>
              <input type="text" id="input-wf-note" placeholder="Required for Hold, Flag, or Reject actions..." style="width:100%;" />
            </div>
          </div>

          <!-- Audit Timeline -->
          <div class="card">
            <div class="card-title">Lifecycle Audit Trail &amp; Approvals</div>
            <div class="timeline" style="margin-top:0.6rem;">
              ${(inv.timeline || [])
                .map(
                  (evt) => `
                <div class="timeline-step">
                  <div class="timeline-dot"></div>
                  <div class="timeline-content">
                    <div style="display:flex;justify-content:space-between;">
                      <strong>${esc(((evt.action || evt.event || 'EVENT')).toUpperCase())}</strong>
                      <span class="mono" style="font-size:0.72rem;color:var(--text-muted);">${esc(evt.timestamp.slice(0, 16).replace('T', ' '))}</span>
                    </div>
                    <div style="font-size:0.78rem;color:var(--text-secondary);">${esc(evt.actorName || evt.actor)} (${esc(evt.actorRole || 'System')})</div>
                    ${evt.details ? `<div style="font-size:0.75rem;color:var(--text-muted);margin-top:2px;">${esc(evt.details)}</div>` : ''}
                  </div>
                </div>
              `
                )
                .join('')}
            </div>
          </div>
        </div>
      </div>
    `;

    // Bind event handlers inside dialog body
    const attachBtn = document.getElementById('btn-detail-attach');
    if (attachBtn) {
      attachBtn.addEventListener('click', () => {
        inv.attachments = inv.attachments || [];
        inv.attachments.push({
          id: `att_${Date.now()}`,
          name: `Supporting_Doc_${inv.attachments.length + 1}.pdf`,
          type: 'application/pdf',
          uploadedAt: new Date().toISOString()
        });
        showToast('Attached supporting document');
        renderInvoiceDetailModal();
      });
    }

    const commentBtn = document.getElementById('btn-detail-comment');
    if (commentBtn) {
      commentBtn.addEventListener('click', () => {
        const input = document.getElementById('input-detail-comment');
        const text = input ? input.value.trim() : '';
        if (!text) return;
        inv.comments = inv.comments || [];
        inv.comments.push({
          id: `cmt_${Date.now()}`,
          author: state.currentUser.name,
          role: state.currentUser.role,
          text,
          timestamp: new Date().toISOString()
        });
        showToast('Added internal audit comment');
        renderInvoiceDetailModal();
      });
    }

    body.querySelectorAll('[data-wf]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const action = btn.getAttribute('data-wf');
        const noteInput = document.getElementById('input-wf-note');
        const note = noteInput ? noteInput.value.trim() : '';
        try {
          if (action === 'callback_verify') {
            VG.verifyPhoneCallback(state, inv.id, {
              contactPerson: supplier ? supplier.officialPhoneContact : 'Authorized CFO',
              phoneNumber: supplier ? supplier.officialPhone : '+49 89 2345 6789',
              notes: note || 'Verified bank account authenticity via official switchboard'
            });
            showToast(`Phone callback logged for ${inv.invoiceNumber}`);
          } else {
            VG.performWorkflowAction(state, inv.id, action, { reason: note, notes: note });
            showToast(`Action "${action}" recorded on ${inv.invoiceNumber}`);
          }
          renderAll();
          renderInvoiceDetailModal();
        } catch (err) {
          showToast(err.message, true);
        }
      });
    });
  }

  // ===========================================================================
  // TAB 3: PAYMENTS, CASH FLOW FORECAST & SEPA BATCHES
  // ===========================================================================
  function renderPaymentsTab() {
    const forecast = VG.computeCashFlowForecast(state);
    const cur = forecast.baseCurrency;
    const fmt = (v) => VG.formatMoney(v, cur);

    const cashCards = document.getElementById('cashflow-cards');
    if (cashCards) {
      cashCards.innerHTML = `
        <div class="card">
          <div class="card-title">Overdue &amp; Due Today</div>
          <div class="kpi-value" style="color: var(--orange) !important;">${esc(fmt(forecast.overdue + forecast.dueToday))}</div>
          <div class="kpi-sub">
            <span>Overdue: <strong>${esc(fmt(forecast.overdue))}</strong></span>
            <span>Due Today: <strong>${esc(fmt(forecast.dueToday))}</strong></span>
          </div>
        </div>
        <div class="card">
          <div class="card-title">Next 7 Days Forecast</div>
          <div class="kpi-value" style="color: var(--teal) !important;">${esc(fmt(forecast.next7Days))}</div>
          <div class="kpi-sub"><span>Scheduled &amp; Ready to Pay</span></div>
        </div>
        <div class="card">
          <div class="card-title">Next 30 Days Forecast</div>
          <div class="kpi-value">${esc(fmt(forecast.next30Days))}</div>
          <div class="kpi-sub"><span>Beyond 30d: ${esc(fmt(forecast.beyond30Days))}</span></div>
        </div>
        <div class="card">
          <div class="card-title">Early-Payment Discount Opportunity</div>
          <div class="kpi-value" style="color: var(--success) !important;">${esc(fmt(forecast.potentialEarlyDiscountSavings))}</div>
          <div class="kpi-sub"><span>Schedule before discount deadline to capture</span></div>
        </div>
      `;
    }

    // Render Companion SVG Chart on Payments
    renderCashFlowChart(forecast);

    // Payable queue: verified_approved, ready_to_pay, scheduled, paid
    const payableList = state.invoices.filter((inv) =>
      [VG.STATUSES.VERIFIED_APPROVED, VG.STATUSES.READY_TO_PAY, VG.STATUSES.SCHEDULED, VG.STATUSES.PAID].includes(inv.status)
    );
    const activePayableCount = payableList.filter((i) => i.status !== VG.STATUSES.PAID).length;
    const badgePayable = document.getElementById('badge-payable-count');
    if (badgePayable) badgePayable.textContent = String(activePayableCount);

    const tbody = document.getElementById('payable-tbody');
    if (!tbody) return;

    if (payableList.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 2rem; color: var(--text-muted);">No invoices ready for payment.</td></tr>`;
      return;
    }

    // Render exactly 6 columns
    tbody.innerHTML = payableList
      .map((inv) => {
        const rem = VG.getRemainingAmount(inv);
        const check = VG.canPayInvoice(state, inv);
        const sodBadge =
          inv.status === VG.STATUSES.PAID
            ? `<span class="badge badge-green">✓ Paid (${esc(inv.paymentReference || 'Reconciled')})</span>`
            : check.allowed
            ? `<span class="badge badge-emerald">✓ Eligible to Pay</span>`
            : `<span class="badge badge-red" title="${esc(check.reason)}">Blocked: ${esc(check.reason.slice(0, 36))}...</span>`;

        return `
          <tr data-payable-row="${esc(inv.id)}">
            <td class="mono"><strong>${esc(inv.invoiceNumber)}</strong><br><small class="text-muted">${esc(inv.id)}</small></td>
            <td><strong>${esc(inv.supplierName)}</strong></td>
            <td class="mono">
              ${esc(inv.dueDate)}
              ${inv.scheduledPaymentDate ? `<br><small style="color:var(--accent);">Sched: ${esc(inv.scheduledPaymentDate)}</small>` : ''}
            </td>
            <td class="mono">
              <strong>${esc(VG.formatMoney(rem, inv.currency))}</strong>
              <br><small class="text-muted">of ${esc(VG.formatMoney(inv.amount, inv.currency))}</small>
            </td>
            <td>${sodBadge}</td>
            <td style="text-align: right;">
              ${
                inv.status !== VG.STATUSES.PAID
                  ? `<div style="display:flex;flex-wrap:wrap;justify-content:flex-end;gap:0.3rem;">
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

    renderBatchesContainer();
  }

  function renderCashFlowChart(forecast) {
    const svgEl = document.getElementById('chart-cashflow-svg');
    if (!svgEl) return;
    const cur = forecast.baseCurrency || 'EUR';
    const width = 900;
    const height = 220;
    const pad = { top: 36, right: 36, bottom: 48, left: 70 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;

    const buckets = [
      { id: 'overdue', label: 'Overdue (Past Due)', amount: forecast.overdue, color: 'var(--danger, #ef4444)', sub: 'Action Required' },
      { id: 'today', label: 'Due Today', amount: forecast.dueToday, color: 'var(--orange, #f97316)', sub: 'Immediate Payout' },
      { id: 'week', label: 'Next 7 Days', amount: forecast.next7Days, color: 'var(--teal, #14b8a6)', sub: 'Capture Discounts' },
      { id: 'month', label: '8–30 Days', amount: forecast.next30Days, color: 'var(--accent, #0284c7)', sub: 'Planned Cash Out' },
      { id: 'future', label: 'Beyond 30 Days', amount: forecast.beyond30Days, color: 'var(--text-muted, #8b5cf6)', sub: 'Future Commitments' }
    ];

    const maxVal = Math.max(1, ...buckets.map((b) => b.amount)) * 1.18;
    const bandW = plotW / buckets.length;
    const barW = Math.min(84, bandW * 0.58);

    // Grid lines
    const gridLines = [];
    const yTicks = [0, maxVal * 0.5, maxVal];
    yTicks.forEach((val) => {
      const y = pad.top + plotH - (val / maxVal) * plotH;
      const label = VG.formatMoney(val, cur).replace(/,00|\.00/, '');
      gridLines.push(`
        <line x1="${pad.left}" y1="${y.toFixed(1)}" x2="${(width - pad.right).toFixed(1)}" y2="${y.toFixed(1)}" stroke="var(--border, rgba(0,0,0,0.08))" stroke-dasharray="3 3"/>
        <text x="${(pad.left - 10).toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--text-muted)">${esc(label)}</text>
      `);
    });

    const bars = buckets.map((b, idx) => {
      const x = pad.left + idx * bandW + (bandW - barW) / 2;
      const barH = (b.amount / maxVal) * plotH;
      const yBase = pad.top + plotH;
      const yTop = yBase - barH;
      const labelX = x + barW / 2;

      const rect = `
        <rect x="${x.toFixed(1)}" y="${yTop.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(2, barH).toFixed(1)}" fill="${b.color}" rx="5" ry="5">
          <title>${esc(b.label)}: ${esc(VG.formatMoney(b.amount, cur))}</title>
        </rect>
      `;

      const amtLabel = `
        <text x="${labelX.toFixed(1)}" y="${(yTop - 8).toFixed(1)}" text-anchor="middle" font-size="12" font-weight="700" fill="var(--text)">
          ${esc(VG.formatMoney(b.amount, cur).replace(/,00|\.00/, ''))}
        </text>
      `;

      const nameLabel = `
        <text x="${labelX.toFixed(1)}" y="${(yBase + 20).toFixed(1)}" text-anchor="middle" font-size="11" font-weight="600" fill="var(--text)">
          ${esc(b.label)}
        </text>
      `;

      const subLabel = `
        <text x="${labelX.toFixed(1)}" y="${(yBase + 34).toFixed(1)}" text-anchor="middle" font-size="10" fill="var(--text-muted)">
          ${esc(b.sub)}
        </text>
      `;

      return rect + amtLabel + nameLabel + subLabel;
    }).join('');

    // Discount highlight note
    const discNote = forecast.potentialEarlyDiscountSavings > 0
      ? `<g transform="translate(${(width - 290).toFixed(1)}, 14)">
           <rect x="0" y="0" width="250" height="22" rx="4" fill="var(--bg-elevated, rgba(0,0,0,0.05))" stroke="var(--teal, #14b8a6)" stroke-width="1"/>
           <text x="125" y="15" text-anchor="middle" font-size="11" fill="var(--teal, #14b8a6)" font-weight="600">⚡ Early Discount Available: ${esc(VG.formatMoney(forecast.potentialEarlyDiscountSavings, cur))}</text>
         </g>`
      : '';

    svgEl.innerHTML = `
      ${gridLines.join('')}
      ${bars}
      ${discNote}
    `;
  }

  function renderBatchesContainer() {
    const batchCont = document.getElementById('batches-container');
    if (!batchCont) return;
    if (state.paymentBatches.length === 0) {
      batchCont.innerHTML = `<div style="font-size:0.8rem;color:var(--text-muted);padding:0.75rem 0;">No SEPA XML payment batches generated yet. Click "Generate SEPA XML Batch" above to batch all eligible approved invoices.</div>`;
      return;
    }

    batchCont.innerHTML = state.paymentBatches
      .slice()
      .reverse()
      .map(
        (b) => `
        <div style="background:var(--bg-elevated);padding:0.75rem;border-radius:8px;margin-bottom:0.6rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
          <div>
            <div style="display:flex;align-items:center;gap:0.5rem;">
              <strong class="mono">${esc(b.id)}</strong>
              <span class="badge ${b.status === 'reconciled' ? 'badge-emerald' : 'badge-accent'}">${esc(b.status.toUpperCase())}</span>
            </div>
            <div style="font-size:0.75rem;color:var(--text-muted);margin-top:2px;">
              Created by ${esc(b.createdByName)} • Invoices: ${b.invoiceCount} • Total: <strong class="mono">${esc(VG.formatMoney(b.totalAmount, 'EUR'))}</strong> • Exec: ${esc(b.executionDate)}
            </div>
          </div>
          <div style="display:flex;gap:0.4rem;">
            <button type="button" class="btn btn-sm" data-batch-dl="${esc(b.id)}">Download ISO 20022 XML</button>
            ${
              b.status !== 'reconciled'
                ? `<button type="button" class="btn btn-sm btn-success" data-batch-recon="${esc(b.id)}">Reconcile Bank Statement</button>`
                : `<span class="badge badge-green">✓ Bank Reconciled</span>`
            }
          </div>
        </div>
      `
      )
      .join('');

    batchCont.querySelectorAll('[data-batch-dl]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const bid = btn.getAttribute('data-batch-dl');
        const b = state.paymentBatches.find((item) => item.id === bid);
        if (b) {
          downloadFile(`${b.id}.xml`, b.sepaXml, 'application/xml');
          showToast(`Downloaded SEPA pain.001.001.03 XML for ${b.id}`);
        }
      });
    });

    batchCont.querySelectorAll('[data-batch-recon]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const bid = btn.getAttribute('data-batch-recon');
        try {
          VG.reconcilePaymentBatch(state, bid, state.currentUser);
          showToast(`Reconciled batch ${bid} with bank statement`);
          renderAll();
        } catch (err) {
          showToast(err.message, true);
        }
      });
    });
  }

  // ===========================================================================
  // ON-DEMAND DIALOG: SUPPLIERS DIRECTORY
  // ===========================================================================
  function renderSuppliersTab() {
    const grid = document.getElementById('suppliers-grid');
    if (!grid) return;
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
                        (chg) => `
                    <div style="font-size:0.75rem;background:var(--bg-elevated);padding:0.35rem 0.5rem;border-radius:4px;margin-bottom:0.25rem;">
                      <span class="mono">${esc(chg.changedAt.slice(0, 10))}</span>:
                      <span>${esc(VG.maskPII(chg.oldIban, state.settings.gdprMaskPii))} &rarr; <strong>${esc(VG.maskPII(chg.newIban, state.settings.gdprMaskPii))}</strong></span>
                      (${chg.verified ? '<span style="color:var(--teal)">Verified</span>' : '<span style="color:var(--danger)">Unverified</span>'})
                    </div>
                  `
                      )
                      .join('')
              }
            </div>

            <div style="display:flex;gap:0.4rem;">
              <button type="button" class="btn btn-sm" data-sup-act="whitelist" data-id="${esc(s.id)}" ${s.status === 'verified' ? 'disabled' : ''}>Whitelist</button>
              <button type="button" class="btn btn-sm btn-danger" data-sup-act="blacklist" data-id="${esc(s.id)}" ${s.status === 'blacklisted' ? 'disabled' : ''}>Blacklist</button>
            </div>
          </div>
        `;
      })
      .join('');

    grid.querySelectorAll('[data-sup-act]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        const act = btn.getAttribute('data-sup-act');
        const s = state.suppliers.find((item) => item.id === id);
        if (!s) return;
        s.status = act === 'whitelist' ? 'verified' : 'blacklisted';
        VG.appendAuditLog(state, {
          actorId: state.currentUser.id,
          actorName: state.currentUser.name,
          actorRole: state.currentUser.role,
          action: act === 'whitelist' ? 'WHITELIST_SUPPLIER' : 'BLACKLIST_SUPPLIER',
          entityType: 'supplier',
          entityId: s.id,
          summary: `${act === 'whitelist' ? 'Whitelisted' : 'Blacklisted'} supplier ${s.name}`
        });
        showToast(`${act === 'whitelist' ? 'Whitelisted' : 'Blacklisted'} supplier ${s.name}`);
        renderAll();
      });
    });
  }

  // ===========================================================================
  // ON-DEMAND DIALOG: ALERTS & SLA
  // ===========================================================================
  function renderAlertsTab() {
    const alerts = VG.computeAlerts(state);
    const badgeAlerts = document.getElementById('badge-alerts-count');
    if (badgeAlerts) badgeAlerts.textContent = String(alerts.length);

    const listEl = document.getElementById('alerts-list');
    if (listEl) {
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
    }

    const digestBox = document.getElementById('digest-preview-box');
    if (digestBox) {
      const n = state.settings.notifications;
      digestBox.innerHTML = `
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
  }

  // ===========================================================================
  // ON-DEMAND DIALOG: AUDIT TRAIL, ANALYTICS & SETTINGS
  // ===========================================================================
  function renderGovernanceTab() {
    const an = VG.computeAnalytics(state);
    const cur = state.settings.baseCurrency;

    const summaryEl = document.getElementById('analytics-summary');
    if (summaryEl) {
      summaryEl.innerHTML = `
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
    }

    const intgBox = document.getElementById('integrations-box');
    if (intgBox) {
      intgBox.innerHTML = `
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

      const vatLookupBtn = document.getElementById('btn-vat-lookup');
      if (vatLookupBtn) {
        vatLookupBtn.addEventListener('click', () => {
          const inputVat = document.getElementById('input-vat-lookup');
          const v = inputVat ? inputVat.value.trim() : '';
          const valid = /^[A-Z]{2}[A-Z0-9]{8,12}$/i.test(v);
          const matchSup = state.suppliers.find((s) => s.vatNumber.toLowerCase() === v.toLowerCase());
          const resEl = document.getElementById('vat-lookup-result');
          if (resEl) {
            resEl.innerHTML = valid
              ? `✓ VIES Format Valid (${esc(v.toUpperCase())}) — ${matchSup ? `Registered to ${esc(matchSup.name)} (${esc(matchSup.regNumber)})` : 'Active EU VAT Registration'}`
              : `✕ Invalid VAT number format (${esc(v)})`;
          }
        });
      }
    }

    // Settings Box
    const s = state.settings;
    const settingsBox = document.getElementById('settings-box');
    if (settingsBox) {
      settingsBox.innerHTML = `
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

      const saveSettingsBtn = document.getElementById('btn-save-settings');
      if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', () => {
          const t1 = document.getElementById('set-t1');
          const t2 = document.getElementById('set-t2');
          const sla = document.getElementById('set-sla');
          const hr = document.getElementById('set-high-risk');
          const sod = document.getElementById('set-sod');
          const gdpr = document.getElementById('set-gdpr');

          s.approvalThresholds.level1 = (t1 && Number(t1.value)) || 10000;
          s.approvalThresholds.level2 = (t2 && Number(t2.value)) || 50000;
          s.slaHours = (sla && Number(sla.value)) || 48;
          s.highRiskThreshold = (hr && Number(hr.value)) || 65;
          s.enforceSegregationOfDuties = sod ? sod.value === 'true' : true;
          s.gdprMaskPii = gdpr ? gdpr.value === 'true' : false;

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
      }
    }

    // Audit Log Table
    const auditTbody = document.getElementById('audit-log-tbody');
    if (auditTbody) {
      auditTbody.innerHTML = state.auditLog
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
  }

  // ===========================================================================
  // TAB SWITCHING & GLOBAL RENDER
  // ===========================================================================
  function switchTab(tabId) {
    // If opening an on-demand dialog via switchTab fallback
    if (tabId === 'alerts' || tabId === 'suppliers' || tabId === 'governance') {
      openDialog(`dialog-${tabId}`);
      return;
    }

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
    // Primary Tabs
    document.querySelectorAll('.nav-tab').forEach((btn) => {
      btn.addEventListener('click', () => switchTab(btn.getAttribute('data-tab')));
    });

    // Theme Switch
    const themeBtn = document.getElementById('btn-theme-toggle');
    if (themeBtn) {
      themeBtn.addEventListener('click', () => {
        const html = document.documentElement;
        const next = html.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
        html.setAttribute('data-theme', next);
        state.settings.darkMode = next === 'dark';
        renderOverview();
        renderPaymentsTab();
      });
    }

    // Sidebar Toggle
    const toggleSidebarBtn = document.getElementById('btn-toggle-sidebar');
    function handleToggleSidebar() {
      const sb = document.getElementById('app-sidebar');
      if (!sb) return;
      const isCollapsed = sb.classList.toggle('collapsed');
      if (toggleSidebarBtn) {
        toggleSidebarBtn.classList.toggle('is-collapsed', isCollapsed);
        toggleSidebarBtn.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
      }
    }
    if (toggleSidebarBtn) {
      toggleSidebarBtn.addEventListener('click', handleToggleSidebar);
    }

    // Quick Search button
    const focusSearchBtn = document.getElementById('btn-focus-search');
    if (focusSearchBtn) {
      focusSearchBtn.addEventListener('click', () => {
        switchTab('invoices');
        const searchEl = document.getElementById('f-search');
        if (searchEl && typeof searchEl.focus === 'function') searchEl.focus();
      });
    }

    // Sankey Flow Perspective Mode Switchers
    const btnSankeyLife = document.getElementById('btn-sankey-lifecycle');
    if (btnSankeyLife) {
      btnSankeyLife.addEventListener('click', () => {
        ui.sankeyMode = 'lifecycle';
        renderOverview();
      });
    }

    const btnSankeyDept = document.getElementById('btn-sankey-dept');
    if (btnSankeyDept) {
      btnSankeyDept.addEventListener('click', () => {
        ui.sankeyMode = 'supplier';
        renderOverview();
      });
    }

    const btnSankeySup = document.getElementById('btn-sankey-supplier');
    if (btnSankeySup) {
      btnSankeySup.addEventListener('click', () => {
        ui.sankeyMode = 'supplier';
        renderOverview();
      });
    }

    // On-Demand Dialog Triggers & Close buttons
    const bindDialogBtn = (btnId, dlgId, isClose = false) => {
      const btn = document.getElementById(btnId);
      if (btn) {
        btn.addEventListener('click', () => {
          if (isClose) closeDialog(dlgId);
          else openDialog(dlgId);
        });
      }
    };

    bindDialogBtn('btn-open-alerts', 'dialog-alerts');
    bindDialogBtn('btn-sidebar-alerts', 'dialog-alerts');
    bindDialogBtn('btn-close-alerts', 'dialog-alerts', true);

    bindDialogBtn('btn-open-suppliers', 'dialog-suppliers');
    bindDialogBtn('btn-sidebar-suppliers', 'dialog-suppliers');
    bindDialogBtn('btn-close-suppliers', 'dialog-suppliers', true);

    bindDialogBtn('btn-open-governance', 'dialog-governance');
    bindDialogBtn('btn-sidebar-governance', 'dialog-governance');
    bindDialogBtn('btn-close-governance', 'dialog-governance', true);

    bindDialogBtn('btn-close-detail', 'dialog-invoice-detail', true);
    bindDialogBtn('btn-open-ingest', 'dialog-ingest');
    bindDialogBtn('btn-close-ingest', 'dialog-ingest', true);

    // Generic [data-close] buttons
    document.querySelectorAll('[data-close]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const targetId = btn.getAttribute('data-close');
        if (targetId) closeDialog(targetId);
      });
    });

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
      if (el) {
        el.addEventListener('input', () => {
          ui.query.preset = '';
          ui.activeViewId = '';
          ui.filterInvoiceIds = null;
          ui.query[key] = el.value;
          renderInvoicesTable();
        });
      }
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
    const chkSelectAll = document.getElementById('chk-select-all');
    if (chkSelectAll) {
      chkSelectAll.addEventListener('change', (e) => {
        let visible = VG.queryInvoices(state, ui.query);
        if (ui.filterInvoiceIds && ui.filterInvoiceIds.size > 0) {
          visible = visible.filter((i) => ui.filterInvoiceIds.has(i.id));
        }
        if (e.target.checked) {
          visible.forEach((i) => ui.selectedInvoiceIds.add(i.id));
        } else {
          visible.forEach((i) => ui.selectedInvoiceIds.delete(i.id));
        }
        const lbl = document.getElementById('selected-count-label');
        if (lbl) lbl.textContent = `${ui.selectedInvoiceIds.size} selected`;
        renderInvoicesTable();
      });
    }

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

    const bulkChecksBtn = document.getElementById('btn-bulk-checks');
    if (bulkChecksBtn) bulkChecksBtn.addEventListener('click', () => runBulk('run_checks'));

    const bulkAssignBtn = document.getElementById('btn-bulk-assign');
    if (bulkAssignBtn) {
      bulkAssignBtn.addEventListener('click', () => runBulk('assign', { assignee: 'Sophie Mercier' }));
    }

    const bulkApproveBtn = document.getElementById('btn-bulk-approve');
    if (bulkApproveBtn) bulkApproveBtn.addEventListener('click', () => runBulk('approve'));

    const bulkHoldBtn = document.getElementById('btn-bulk-hold');
    if (bulkHoldBtn) bulkHoldBtn.addEventListener('click', () => runBulk('hold', { reason: 'Bulk hold for review' }));

    const bulkFlagBtn = document.getElementById('btn-bulk-flag');
    if (bulkFlagBtn) bulkFlagBtn.addEventListener('click', () => runBulk('flag', { reason: 'Flagged in bulk audit' }));

    // Save View & Reset
    const saveViewBtn = document.getElementById('btn-save-view');
    if (saveViewBtn) {
      saveViewBtn.addEventListener('click', () => {
        const name = `Custom View #${state.savedViews.length + 1}`;
        const id = `custom_${Date.now()}`;
        state.savedViews.push({ id, name, query: { ...ui.query } });
        ui.activeViewId = id;
        saveViewsToStorage();
        showToast(`Saved filter view "${name}"`);
        renderSavedViewsBar();
      });
    }

    const resetFiltersBtn = document.getElementById('btn-reset-filters');
    if (resetFiltersBtn) {
      resetFiltersBtn.addEventListener('click', () => {
        resetQueryFilters();
        renderAll();
      });
    }

    // Exports
    const expCsvBtn = document.getElementById('btn-export-csv');
    if (expCsvBtn) {
      expCsvBtn.addEventListener('click', () => {
        const rows = VG.queryInvoices(state, ui.query);
        const csv = VG.exportInvoicesCSV(rows);
        downloadFile('vaultgard-invoices.csv', csv, 'text/csv;charset=utf-8');
        showToast(`Exported ${rows.length} invoices to CSV`);
      });
    }

    const expXlsBtn = document.getElementById('btn-export-xls');
    if (expXlsBtn) {
      expXlsBtn.addEventListener('click', () => {
        const rows = VG.queryInvoices(state, ui.query);
        const csv = VG.exportInvoicesCSV(rows);
        downloadFile('vaultgard-invoices.xls', csv, 'application/vnd.ms-excel');
        showToast(`Exported ${rows.length} invoices to Excel (.xls)`);
      });
    }

    const expPdfBtn = document.getElementById('btn-export-pdf');
    if (expPdfBtn) {
      expPdfBtn.addEventListener('click', () => {
        window.print();
      });
    }

    // SEPA Batch Creation
    const createBatchBtn = document.getElementById('btn-create-sepa-batch');
    if (createBatchBtn) {
      createBatchBtn.addEventListener('click', () => {
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
    }

    // Audit Chain Integrity Verification & Export
    const verifyChainBtn = document.getElementById('btn-verify-audit-chain');
    if (verifyChainBtn) {
      verifyChainBtn.addEventListener('click', () => {
        const res = VG.verifyAuditLogIntegrity(state.auditLog);
        if (res.valid) {
          showToast(`✓ Cryptographic hash chain verified intact across ${res.count} audit records`);
        } else {
          showToast(`✕ Audit chain integrity broken at index ${res.brokenAtIndex}`, true);
        }
      });
    }

    const expComplianceBtn = document.getElementById('btn-export-compliance');
    if (expComplianceBtn) {
      expComplianceBtn.addEventListener('click', () => {
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
    }

    // OCR Parser & Scam Preset in Ingest Modal
    const parseOcrBtn = document.getElementById('btn-parse-ocr');
    if (parseOcrBtn) {
      parseOcrBtn.addEventListener('click', () => {
        const rawEl = document.getElementById('ocr-raw-input');
        const raw = rawEl ? rawEl.value : '';
        const parsed = VG.parseOcrText(raw);
        const setVal = (id, val) => {
          const el = document.getElementById(id);
          if (el) el.value = val;
        };
        setVal('ing-number', parsed.invoiceNumber);
        setVal('ing-supplier', parsed.supplierName);
        setVal('ing-vat', parsed.vatNumber);
        setVal('ing-iban', parsed.iban);
        setVal('ing-amount', parsed.amount);
        setVal('ing-currency', parsed.currency);
        setVal('ing-po', parsed.poNumber);
        setVal('ing-due', parsed.dueDate);
        setVal('ing-email', parsed.senderEmail);
        showToast('OCR fields extracted from raw invoice text');
      });
    }

    const loadScamPresetBtn = document.getElementById('btn-load-scam-preset');
    if (loadScamPresetBtn) {
      loadScamPresetBtn.addEventListener('click', () => {
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
        const rawEl = document.getElementById('ocr-raw-input');
        if (rawEl) rawEl.value = scamText;
        const ocrBtn = document.getElementById('btn-parse-ocr');
        if (ocrBtn) ocrBtn.click();
      });
    }

    const formIngest = document.getElementById('form-ingest-invoice');
    if (formIngest) {
      formIngest.addEventListener('submit', (e) => {
        e.preventDefault();
        try {
          const getVal = (id) => {
            const el = document.getElementById(id);
            return el ? el.value.trim() : '';
          };
          const inv = VG.ingestInvoice(
            state,
            {
              invoiceNumber: getVal('ing-number'),
              supplierName: getVal('ing-supplier'),
              vatNumber: getVal('ing-vat'),
              iban: getVal('ing-iban'),
              amount: Number(getVal('ing-amount')),
              currency: getVal('ing-currency'),
              poNumber: getVal('ing-po'),
              dueDate: getVal('ing-due'),
              senderEmail: getVal('ing-email')
            },
            'ocr_upload'
          );
          closeDialog('dialog-ingest');
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
  }

  initSelectors();
  bindEvents();
  renderAll();
})();
