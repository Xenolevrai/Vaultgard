// VaultGuard — espace de travail (/app).
// Tout ce qui s'affiche vient du serveur (agent/server.py, routes /api/app/*) : rien n'est simulé dans le navigateur.
// Sécurité : aucune donnée n'est insérée dans la page sans passer par esc() ; aucun style ni script en ligne (CSP) ;
// chaque requête POST porte le jeton CSRF de la session.
(function () {
  'use strict';

  const Charts = window.VGCharts;
  const ROLE_LEVELS = { viewer: 1, approver: 2, admin: 3, owner: 4 };
  const REFRESH_MS = 20000;
  const MAX_UPLOAD_BYTES = 2000000;
  const MAX_AUDIT_BYTES = 250000;

  const state = {
    csrf: '',
    user: null,
    role: 'viewer',
    orgs: [],
    box: null,          // réponse de /api/app/inbox
    issued: null,       // réponse de /api/app/einvoices
    invoices: [],       // factures reçues, mises en forme pour l'affichage
    journal: null,
    views: []
  };

  const ui = {
    tab: 'overview',
    sankeyMode: 'lifecycle',
    detailId: null,
    viewId: 'all',
    ids: null,          // sélection venue du schéma de parcours
    query: defaultQuery()
  };

  function defaultQuery() {
    return { search: '', status: 'all', supplier: 'all', dateFrom: '', dateTo: '', amountMin: '', amountMax: '',
             sortBy: 'received', sortDir: 'desc' };
  }

  // ------------------------------------------------------------------ États d'une facture reçue
  const STATUS = {
    review:   { label: 'À vérifier', badge: 'badge-paused', icon: 'clock', color: '#d97706',
                hint: 'Votre décision est attendue avant tout paiement.' },
    refused:  { label: 'Refusée', badge: 'badge-high-priority', icon: 'shield', color: '#dc2626',
                hint: 'Signes de fraude ou refus de votre part : rien ne doit être payé.' },
    ready:    { label: 'Bonne à payer', badge: 'badge-ready', icon: 'check', color: '#14b8a6',
                hint: 'Acceptée, pas encore dans un fichier de virements.' },
    batched:  { label: 'Virement préparé', badge: 'badge-scheduled', icon: 'file', color: '#3b82f6',
                hint: 'Déjà dans un fichier de virements.' },
    accepted: { label: 'Acceptée, à payer à la main', badge: 'badge-in-progress', icon: 'hand', color: '#f59e0b',
                hint: 'Acceptée par vous, mais le fournisseur n\'est pas dans votre liste : elle n\'entre pas dans le fichier.' }
  };
  const STATUS_KEYS = ['review', 'refused', 'ready', 'batched', 'accepted'];

  const LEVEL = {
    ok:      { label: 'Conforme', badge: 'badge-ready' },
    review:  { label: 'À vérifier', badge: 'badge-paused' },
    refused: { label: 'Fraude probable', badge: 'badge-high-priority' }
  };

  const ICONS = {
    clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><line x1="9" x2="15" y1="9" y2="15"/><line x1="15" x2="9" y1="9" y2="15"/>',
    check: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><polyline points="9 15 11 17 15 13"/>',
    hand: '<path d="M18 11V6a2 2 0 0 0-4 0v5"/><path d="M14 10V4a2 2 0 0 0-4 0v6"/><path d="M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>'
  };

  const ACTIONS = {
    'invoice.check': 'Facture contrôlée',
    'invoice.upload': 'Facture déposée à la main',
    'invoice.approve': 'Facture acceptée',
    'invoice.reject': 'Facture refusée',
    'payee.add': 'Fournisseur ajouté',
    'payee.remove': 'Fournisseur retiré',
    'inbox.sender_add': 'Expéditeur autorisé',
    'inbox.sender_remove': 'Expéditeur retiré',
    'inbox.threshold': 'Seuil d\'accord modifié',
    'inbox.ignored': 'Mail ignoré',
    'bank.set': 'Compte bancaire de l\'entreprise modifié',
    'transfer.batch': 'Fichier de virements préparé',
    'transfer.seal': 'Empreinte du fichier inscrite',
    'transfer.audit': 'Fichier de virements contrôlé',
    'einvoice.profile': 'Identité de l\'entreprise modifiée',
    'einvoice.issue': 'Facture émise',
    'einvoice.receive': 'Facture reçue par la plateforme',
    'audit.anchor': 'Journal scellé',
    'auth.login': 'Connexion',
    'auth.logout': 'Déconnexion',
    'org.switch': 'Changement d\'entreprise'
  };

  const IGNORED = { sender: 'expéditeur non autorisé', auto: 'réponse automatique', malformed: 'mail illisible',
                    size: 'mail trop volumineux' };

  // ------------------------------------------------------------------ Outils
  function $(id) { return document.getElementById(id); }

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  const EUR = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' });
  const EUR_SHORT = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 });

  function money(euros, short) { return (short ? EUR_SHORT : EUR).format(Number(euros) || 0); }
  function cents(value) { return value == null ? '—' : money(value / 100); }
  function plural(n, word) { return n + ' ' + word + (n > 1 ? 's' : ''); }

  function day(epoch) {
    return epoch ? new Date(epoch * 1000).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '—';
  }
  function dayTime(epoch) {
    return epoch ? new Date(epoch * 1000).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric',
                                                                    hour: '2-digit', minute: '2-digit' }) : '—';
  }
  function isoDay(epoch) {
    const d = new Date(epoch * 1000);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  const FORMATS = { mail: 'mail', facturx: 'facture électronique (page + données)', ubl: 'facture électronique (données seules)',
                    cii: 'facture électronique (données seules)', xml: 'fichier de données', pdf: 'PDF', texte: 'texte',
                    html: 'page web', image: 'image (lue par reconnaissance de texte)', office: 'document bureautique' };
  function formatName(fmt) {
    return fmt ? String(fmt).split('+').map((part) => FORMATS[part] || part).join(', ') : 'non reconnu';
  }
  function spacedIban(iban) { return String(iban || '').replace(/(.{4})/g, '$1 ').trim(); }
  function shortHash(hash) { return hash ? String(hash).slice(0, 10) + '…' : '—'; }
  function can(minRole) { return (ROLE_LEVELS[state.role] || 0) >= ROLE_LEVELS[minRole]; }

  function badge(cls, text, icon) {
    const svg = icon && ICONS[icon]
      ? `<svg class="badge-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[icon]}</svg>`
      : '';
    return `<span class="badge ${cls}">${svg}<span>${esc(text)}</span></span>`;
  }
  function statusBadge(key) {
    const meta = STATUS[key];
    return meta ? badge(meta.badge, meta.label, meta.icon) : badge('badge-slate', key);
  }

  function toast(message, isError) {
    const box = $('toast-container');
    const el = document.createElement('div');
    el.className = 'toast-banner' + (isError ? ' error' : '');
    el.textContent = message;
    box.textContent = '';
    box.appendChild(el);
    setTimeout(() => { if (el.parentNode) el.remove(); }, isError ? 7000 : 4200);
  }

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (_) { /* stockage indisponible : l'interface fonctionne sans */ }
    return null;
  }

  function openDialog(id) { const d = $(id); if (d && !d.open) d.showModal(); }
  function closeDialog(id) { const d = $(id); if (d && d.open) d.close(); }
  function anyDialogOpen() { return Boolean(document.querySelector('dialog[open]')); }

  let confirmResolve = null;
  function confirmAction(title, text, yesLabel) {
    $('confirm-title').textContent = title;
    $('confirm-text').textContent = text;
    $('btn-confirm-yes').textContent = yesLabel || 'Confirmer';
    openDialog('dialog-confirm');
    return new Promise((resolve) => { confirmResolve = resolve; });
  }
  function settleConfirm(answer) {
    closeDialog('dialog-confirm');
    if (confirmResolve) { confirmResolve(answer); confirmResolve = null; }
  }

  // ------------------------------------------------------------------ Appels au serveur
  async function api(path, body) {
    const opts = { credentials: 'same-origin', headers: {} };
    if (body !== undefined) {
      opts.method = 'POST';
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-CSRF-Token'] = state.csrf;
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (res.status === 401) {
      window.location.href = '/login';
      throw new Error('Session expirée');
    }
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok) throw new Error((data && data.error) || 'Erreur du serveur (' + res.status + ')');
    return data;
  }

  // Lance une action déclenchée par un bouton : bouton désactivé pendant l'appel, erreur affichée en clair.
  async function run(button, task) {
    if (button) button.disabled = true;
    try {
      await task();
    } catch (err) {
      toast(err.message || 'Action impossible', true);
    } finally {
      if (button && button.isConnected) button.disabled = false;
    }
  }

  // ------------------------------------------------------------------ Mise en forme des factures reçues
  function adapt(check, box) {
    const payees = box.payees || [];
    const payee = check.payee_id ? payees.find((p) => p.id === check.payee_id) : null;
    const platform = (box.platform || {})[check.id];
    const amount = check.amount_cents == null ? 0 : check.amount_cents / 100;
    let status;
    if (check.verdict === 'review') status = 'review';
    else if (check.verdict === 'refused') status = 'refused';
    else if (check.batch_id) status = 'batched';
    else if (payee && check.currency === 'EUR' && amount > 0) status = 'ready';
    else status = 'accepted';
    return {
      id: check.id,
      number: check.invoice_number || 'Sans numéro',
      supplier: check.payee_name || (platform && platform.seller_name) || 'Fournisseur non reconnu',
      known: Boolean(check.payee_name),
      cents: check.amount_cents,
      amount,
      currency: check.currency || '',
      received: check.created_at,
      ibanTail: check.iban_tail || '',
      payeeIban: payee ? payee.iban : '',
      fmt: check.fmt || '',
      sha: check.file_sha256 || '',
      verdict: check.verdict,
      // Verdict du contrôle automatique : si une personne a tranché, la facture était « à vérifier ».
      auto: check.review_action ? 'review' : check.verdict,
      reviewAction: check.review_action || '',
      reasons: check.reasons || [],
      proof: check.proof || [],
      batchId: check.batch_id || '',
      platform: platform || null,
      status
    };
  }

  function mainReason(inv) {
    const r = inv.reasons[0];
    if (inv.reviewAction === 'approved') return 'Acceptée par vous après vérification.';
    if (inv.reviewAction === 'rejected') return 'Refusée par vous.';
    return r ? r.title : '';
  }

  function filtered() {
    const q = ui.query;
    const needle = q.search.trim().toLowerCase();
    const min = q.amountMin === '' ? null : Number(q.amountMin);
    const max = q.amountMax === '' ? null : Number(q.amountMax);
    const rows = state.invoices.filter((inv) => {
      if (ui.ids && !ui.ids.has(inv.id)) return false;
      if (q.status !== 'all' && inv.status !== q.status) return false;
      if (q.supplier !== 'all' && inv.supplier !== q.supplier) return false;
      if (q.dateFrom && isoDay(inv.received) < q.dateFrom) return false;
      if (q.dateTo && isoDay(inv.received) > q.dateTo) return false;
      if (min != null && inv.amount < min) return false;
      if (max != null && inv.amount > max) return false;
      if (needle) {
        const hay = (inv.number + ' ' + inv.supplier + ' ' + inv.amount.toFixed(2) + ' ' + money(inv.amount)).toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
    const dir = q.sortDir === 'asc' ? 1 : -1;
    const key = { number: (i) => i.number.toLowerCase(), supplier: (i) => i.supplier.toLowerCase(), amount: (i) => i.amount,
                  received: (i) => i.received, status: (i) => STATUS_KEYS.indexOf(i.status) }[q.sortBy] || ((i) => i.received);
    return rows.sort((a, b) => { const x = key(a), y = key(b); return x < y ? -dir : x > y ? dir : 0; });
  }

  function sumBy(status) {
    const rows = state.invoices.filter((i) => i.status === status);
    return { count: rows.length, total: rows.reduce((s, i) => s + i.amount, 0), ids: rows.map((i) => i.id) };
  }

  // ------------------------------------------------------------------ Écran 1 : vue d'ensemble
  function renderOverview() {
    const ready = sumBy('ready'), review = sumBy('review'), refused = sumBy('refused');
    const total = state.invoices.reduce((s, i) => s + i.amount, 0);
    $('kpi-top-cards').innerHTML = `
      <div class="card kpi-card" data-go-status="ready" role="button" tabindex="0">
        <div class="card-title">Bonnes à payer</div>
        <div class="kpi-value kpi-teal">${esc(money(ready.total))}</div>
        <div class="kpi-sub">${esc(plural(ready.count, 'facture'))} acceptée${ready.count > 1 ? 's' : ''}, en attente de virement</div>
      </div>
      <div class="card kpi-card" data-go-status="review" role="button" tabindex="0">
        <div class="card-title">À vérifier par vous</div>
        <div class="kpi-value kpi-warning">${esc(money(review.total))}</div>
        <div class="kpi-sub">${esc(plural(review.count, 'facture'))} en attente de votre décision</div>
      </div>
      <div class="card kpi-card" data-go-status="refused" role="button" tabindex="0">
        <div class="card-title">Fraudes arrêtées</div>
        <div class="kpi-value kpi-danger">${esc(money(refused.total))}</div>
        <div class="kpi-sub">${esc(plural(refused.count, 'facture'))} refusée${refused.count > 1 ? 's' : ''} avant paiement</div>
      </div>
      <div class="card kpi-card" data-go-status="all" role="button" tabindex="0">
        <div class="card-title">Factures contrôlées</div>
        <div class="kpi-value">${esc(money(total))}</div>
        <div class="kpi-sub">${esc(plural(state.invoices.length, 'facture'))} reçue${state.invoices.length > 1 ? 's' : ''}</div>
      </div>`;
    bindActivate($('kpi-top-cards'), '[data-go-status]', (el) => goToStatus(el.getAttribute('data-go-status')));

    renderSankey();
    $('chart-monthly-trends').innerHTML = Charts.monthly(monthlyData(), { money });
    $('chart-supplier-trends').innerHTML = Charts.suppliers(supplierData(), { money });

    $('kpi-status-grid').innerHTML = STATUS_KEYS.map((key) => {
      const s = sumBy(key);
      return `
        <div class="status-card" data-go-status="${key}" role="button" tabindex="0">
          <div class="status-card-header">${statusBadge(key)}<span class="status-count">${s.count}</span></div>
          <div class="status-amount">${esc(money(s.total))}</div>
          <div class="status-hint">${esc(STATUS[key].hint)}</div>
        </div>`;
    }).join('');
    bindActivate($('kpi-status-grid'), '[data-go-status]', (el) => goToStatus(el.getAttribute('data-go-status')));
  }

  function bindActivate(rootEl, selector, handler) {
    rootEl.querySelectorAll(selector).forEach((el) => {
      el.addEventListener('click', () => handler(el));
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(el); }
      });
    });
  }

  function goToStatus(status) {
    resetQuery();
    ui.query.status = status;
    ui.viewId = ['all', 'review', 'refused', 'ready'].includes(status) ? status : '';
    syncFilters();
    switchTab('invoices');
  }

  function monthlyData() {
    const months = new Map();
    for (const inv of state.invoices) {
      const d = new Date(inv.received * 1000);
      const key = d.getFullYear() * 12 + d.getMonth();
      if (!months.has(key)) {
        months.set(key, { label: d.toLocaleDateString('fr-FR', { month: 'short', year: '2-digit' }), ok: 0, review: 0, refused: 0 });
      }
      months.get(key)[inv.verdict] += inv.amount;
    }
    return Array.from(months.entries()).sort((a, b) => a[0] - b[0]).slice(-6).map((e) => e[1]);
  }

  function supplierData() {
    const map = new Map();
    for (const inv of state.invoices) {
      if (!map.has(inv.supplier)) map.set(inv.supplier, { name: inv.supplier, total: 0, risky: false });
      const row = map.get(inv.supplier);
      row.total += inv.amount;
      if (inv.status === 'refused') row.risky = true;
    }
    return Array.from(map.values()).filter((r) => r.total > 0).sort((a, b) => b.total - a.total).slice(0, 5);
  }

  function sankeyData() {
    const nodes = new Map();
    const links = new Map();
    const node = (id, label, stage, color) => {
      if (!nodes.has(id)) nodes.set(id, { id, label, stage, color, value: 0, count: 0, ids: [] });
      return nodes.get(id);
    };
    const add = (n, inv) => { n.value += inv.amount; n.count += 1; n.ids.push(inv.id); };
    const link = (a, b, inv) => {
      const key = a.id + '>' + b.id;
      if (!links.has(key)) links.set(key, { source: a.id, target: b.id, value: 0, ids: [] });
      const l = links.get(key);
      l.value += inv.amount;
      l.ids.push(inv.id);
    };
    const AUTO = {
      ok: ['auto_ok', 'Rien d\'anormal', '#14b8a6'],
      review: ['auto_review', 'À vérifier', '#d97706'],
      refused: ['auto_refused', 'Signes de fraude', '#dc2626']
    };
    const END = {
      ready: ['end_ready', 'Bonnes à payer', '#14b8a6'],
      batched: ['end_batched', 'Virement préparé', '#3b82f6'],
      accepted: ['end_accepted', 'À payer à la main', '#f59e0b'],
      review: ['end_review', 'En attente de vous', '#d97706'],
      refused: ['end_refused', 'Refusées', '#dc2626']
    };
    const bySupplier = ui.sankeyMode === 'supplier';
    const top = supplierData().map((r) => r.name);
    const palette = ['#0284c7', '#0d9488', '#6366f1', '#8b5cf6', '#ec4899', '#64748b'];
    let total = 0;
    for (const inv of state.invoices) {
      if (!(inv.amount > 0)) continue;
      total += inv.amount;
      let first;
      if (bySupplier) {
        const index = top.indexOf(inv.supplier);
        first = index >= 0 ? node('sup_' + index, inv.supplier, 0, palette[index]) : node('sup_other', 'Autres', 0, palette[5]);
      } else {
        first = node('received', 'Factures reçues', 0, '#14b8a6');
      }
      const a = AUTO[inv.auto] || AUTO.review;
      const e = END[inv.status];
      const mid = node(a[0], a[1], 1, a[2]);
      const end = node(e[0], e[1], 2, e[2]);
      add(first, inv); add(mid, inv); add(end, inv);
      link(first, mid, inv); link(mid, end, inv);
    }
    return {
      stages: [bySupplier ? 'Fournisseur' : 'Réception', 'Contrôle automatique', 'Où elles en sont'],
      nodes: Array.from(nodes.values()),
      links: Array.from(links.values()),
      total
    };
  }

  function renderSankey() {
    const wrapper = $('sankey-diagram-wrapper');
    wrapper.innerHTML = Charts.sankey(sankeyData(), { width: 920, height: 340, money });
    $('btn-sankey-lifecycle').classList.toggle('active', ui.sankeyMode === 'lifecycle');
    $('btn-sankey-supplier').classList.toggle('active', ui.sankeyMode === 'supplier');

    const tooltip = $('sankey-tooltip');
    const container = $('sankey-container');
    wrapper.querySelectorAll('[data-ids]').forEach((el) => {
      el.addEventListener('mouseenter', () => {
        const title = el.querySelector('title');
        tooltip.textContent = title ? title.textContent : '';
        tooltip.classList.remove('is-hidden');
      });
      el.addEventListener('mousemove', (evt) => {
        const rect = container.getBoundingClientRect();
        tooltip.style.left = Math.max(8, Math.min(rect.width - 260, evt.clientX - rect.left + 14)) + 'px';
        tooltip.style.top = Math.max(8, evt.clientY - rect.top + 14) + 'px';
      });
      el.addEventListener('mouseleave', () => tooltip.classList.add('is-hidden'));
      el.addEventListener('click', () => {
        const ids = (el.getAttribute('data-ids') || '').split(',').filter(Boolean);
        if (!ids.length) return;
        resetQuery();
        ui.viewId = '';
        ui.ids = new Set(ids);
        switchTab('invoices');
        toast(plural(ids.length, 'facture') + ' de cette étape');
      });
    });
  }

  // ------------------------------------------------------------------ Écran 2 : factures reçues
  const BUILT_IN_VIEWS = [
    { id: 'all', name: 'Toutes', query: {} },
    { id: 'review', name: 'À vérifier', query: { status: 'review' } },
    { id: 'refused', name: 'Refusées', query: { status: 'refused' } },
    { id: 'ready', name: 'Bonnes à payer', query: { status: 'ready' } }
  ];

  function loadViews() {
    let custom = [];
    try {
      const parsed = JSON.parse(store('vaultguard_views') || '[]');
      if (Array.isArray(parsed)) custom = parsed.filter((v) => v && typeof v.id === 'string' && v.id.startsWith('custom_') && v.query);
    } catch (_) { custom = []; }
    state.views = BUILT_IN_VIEWS.concat(custom.slice(0, 8));
  }
  function saveViews() {
    store('vaultguard_views', JSON.stringify(state.views.filter((v) => v.id.startsWith('custom_'))));
  }

  function renderViews() {
    const bar = $('saved-views-bar');
    bar.innerHTML = state.views.map((v) => `
      <button type="button" class="view-pill${v.id === ui.viewId ? ' active' : ''}" data-view="${esc(v.id)}">
        ${esc(v.name)}${v.id.startsWith('custom_') ? `<span class="pill-del" data-del-view="${esc(v.id)}" title="Supprimer cette vue" role="button" aria-label="Supprimer cette vue">&times;</span>` : ''}
      </button>`).join('');
    bar.querySelectorAll('[data-view]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const del = e.target.closest('[data-del-view]');
        if (del) {
          state.views = state.views.filter((v) => v.id !== del.getAttribute('data-del-view'));
          saveViews();
          if (ui.viewId === del.getAttribute('data-del-view')) { resetQuery(); syncFilters(); }
          renderInvoices();
          return;
        }
        const view = state.views.find((v) => v.id === btn.getAttribute('data-view'));
        if (!view) return;
        resetQuery();
        ui.viewId = view.id;
        Object.assign(ui.query, view.query);
        syncFilters();
        renderInvoices();
      });
    });
  }

  function resetQuery() {
    const keep = { sortBy: ui.query.sortBy, sortDir: ui.query.sortDir };
    ui.query = Object.assign(defaultQuery(), keep);
    ui.ids = null;
    ui.viewId = 'all';
  }

  const FILTERS = [['f-search', 'search'], ['f-status', 'status'], ['f-supplier', 'supplier'], ['f-date-from', 'dateFrom'],
                   ['f-date-to', 'dateTo'], ['f-amt-min', 'amountMin'], ['f-amt-max', 'amountMax']];

  function syncFilters() {
    for (const [id, key] of FILTERS) $(id).value = ui.query[key];
  }

  function renderFilterOptions() {
    $('f-status').innerHTML = '<option value="all">Tous les états</option>' +
      STATUS_KEYS.map((k) => `<option value="${k}">${esc(STATUS[k].label)}</option>`).join('');
    const names = Array.from(new Set(state.invoices.map((i) => i.supplier))).sort((a, b) => a.localeCompare(b, 'fr'));
    if (ui.query.supplier !== 'all' && !names.includes(ui.query.supplier)) ui.query.supplier = 'all';
    $('f-supplier').innerHTML = '<option value="all">Tous les fournisseurs</option>' +
      names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
    $('f-status').value = ui.query.status;
    $('f-supplier').value = ui.query.supplier;
  }

  function renderInvoices() {
    renderViews();
    const rows = filtered();
    $('badge-invoices-count').textContent = String(state.invoices.filter((i) => i.status === 'review').length);
    $('invoices-count-label').textContent = plural(rows.length, 'facture') + (ui.ids ? ' (sélection du schéma)' : '');
    document.querySelectorAll('#invoices-table th.sortable').forEach((th) => {
      const active = th.getAttribute('data-sort') === ui.query.sortBy;
      th.classList.toggle('sorted-asc', active && ui.query.sortDir === 'asc');
      th.classList.toggle('sorted-desc', active && ui.query.sortDir === 'desc');
    });
    const tbody = $('invoices-tbody');
    if (rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-cell">${state.invoices.length === 0
        ? 'Aucune facture reçue pour le moment. Transférez une facture à votre adresse de dépôt, ou utilisez « Déposer une facture ».'
        : 'Aucune facture ne correspond à ces critères.'}</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((inv) => `
      <tr class="row-link" data-open="${esc(inv.id)}">
        <td class="mono"><strong>${esc(inv.number)}</strong></td>
        <td><strong>${esc(inv.supplier)}</strong>${inv.platform ? ' <span class="badge badge-slate">par la plateforme</span>' : ''}</td>
        <td class="mono num"><strong>${esc(cents(inv.cents))}</strong></td>
        <td class="mono cell-date">${esc(dayTime(inv.received))}</td>
        <td>${statusBadge(inv.status)}</td>
        <td class="cell-why">${esc(mainReason(inv))}</td>
        <td class="num"><button type="button" class="btn btn-sm${inv.status === 'review' ? ' btn-primary' : ''}" data-open="${esc(inv.id)}">${inv.status === 'review' ? 'Décider' : 'Voir'}</button></td>
      </tr>`).join('');
    tbody.querySelectorAll('tr[data-open]').forEach((tr) => {
      tr.addEventListener('click', () => openDetail(tr.getAttribute('data-open')));
    });
  }

  function exportCsv() {
    const safe = (v) => {
      let s = String(v == null ? '' : v);
      if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;      // un tableur ne doit pas y lire une formule
      return '"' + s.replace(/"/g, '""') + '"';
    };
    const rows = filtered();
    const lines = [['Facture', 'Fournisseur', 'Montant (EUR)', 'Reçue le', 'État', 'Pourquoi', 'Empreinte du fichier'].map(safe).join(';')];
    for (const inv of rows) {
      lines.push([inv.number, inv.supplier, inv.cents == null ? '' : inv.amount.toFixed(2).replace('.', ','), day(inv.received),
                  STATUS[inv.status].label, mainReason(inv), inv.sha].map(safe).join(';'));
    }
    const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'vaultguard-factures.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast(plural(rows.length, 'facture') + ' exportée' + (rows.length > 1 ? 's' : ''));
  }

  // ------------------------------------------------------------------ Détail d'une facture
  function openDetail(id) {
    ui.detailId = id;
    if (renderDetail()) openDialog('dialog-invoice-detail');
  }

  function renderDetail() {
    const inv = state.invoices.find((i) => i.id === ui.detailId);
    if (!inv) { closeDialog('dialog-invoice-detail'); return false; }
    $('detail-dialog-title').innerHTML = `${esc(inv.number)} — ${esc(inv.supplier)} ${statusBadge(inv.status)}`;
    $('detail-dialog-subtitle').textContent = 'Reçue le ' + dayTime(inv.received) + ' · ' + STATUS[inv.status].hint;

    const steps = { 'invoice.check': 'Contrôle automatique', 'invoice.approve': 'Acceptée par une personne de votre entreprise',
                    'invoice.reject': 'Refusée par une personne de votre entreprise' };
    const decide = inv.status === 'review'
      ? (can('approver')
        ? `<div class="card decision-card">
             <div class="card-title">Votre décision</div>
             <p class="card-text">Avant d'accepter, vérifiez par un autre moyen que ce document : appelez le fournisseur au numéro que vous utilisez d'habitude, jamais à celui de la facture.</p>
             <div class="dialog-actions">
               <button type="button" class="btn btn-danger" data-decide="reject">Refuser cette facture</button>
               <button type="button" class="btn btn-success" data-decide="approve">J'ai vérifié : accepter</button>
             </div>
           </div>`
        : '<div class="card decision-card"><p class="card-text">Cette facture attend la décision d\'une personne autorisée à valider les paiements.</p></div>')
      : '';

    $('detail-dialog-body').innerHTML = `
      <div class="detail-split">
        <div>
          <div class="card-title">Ce que VaultGuard a lu</div>
          <dl class="fact-list">
            <dt>Fournisseur</dt><dd>${esc(inv.supplier)}${inv.known ? '' : ' <span class="badge badge-paused">absent de votre liste</span>'}</dd>
            <dt>Numéro</dt><dd class="mono">${esc(inv.number)}</dd>
            <dt>Montant</dt><dd class="mono"><strong>${esc(cents(inv.cents))}</strong>${inv.currency && inv.currency !== 'EUR' ? ' (' + esc(inv.currency) + ')' : ''}</dd>
            <dt>Compte indiqué</dt><dd class="mono">${inv.ibanTail ? '•••• ' + esc(inv.ibanTail) : 'aucun compte lisible'}</dd>
            <dt>Type de document</dt><dd>${esc(formatName(inv.fmt))}</dd>
            <dt>Arrivée</dt><dd>${inv.platform ? 'par la plateforme VaultGuard, émise par ' + esc(inv.platform.seller_name) : 'par mail ou dépôt'}</dd>
            <dt>Empreinte du fichier</dt><dd class="mono hash" title="${esc(inv.sha)}">${esc(inv.sha || '—')}</dd>
          </dl>
          ${inv.platform
            ? `<p class="form-hint">Facture émise sur la plateforme : son fichier se régénère à l'identique à partir de la saisie de l'émetteur, et son empreinte prouve qu'il n'a pas changé.</p>
               <p class="detail-download"><a class="btn btn-sm" href="/api/app/einvoices/received/${encodeURIComponent(inv.id)}.pdf" download>Télécharger la facture (PDF)</a></p>`
            : '<p class="form-hint">Le contenu de la facture n\'est pas conservé. L\'empreinte permet de prouver plus tard quel fichier a été contrôlé, sans le garder.</p>'}

          <div class="card-title section-title">Historique de cette facture</div>
          <div class="timeline-list">
            ${inv.proof.length === 0 ? '<div class="timeline-entry">Aucune trace enregistrée.</div>' : inv.proof.map((p) => `
              <div class="timeline-entry">
                <strong>${esc(steps[p.action] || p.action)}</strong>
                <div class="timeline-meta">${esc(dayTime(p.created_at))} · preuve <span class="mono" title="${esc(p.entry_hash)}">${esc(shortHash(p.entry_hash))}</span></div>
              </div>`).join('')}
            ${inv.batchId ? '<div class="timeline-entry"><strong>Ajoutée à un fichier de virements</strong></div>' : ''}
          </div>
        </div>
        <div>
          <div class="card-title">Résultat des contrôles</div>
          <div class="checklist-list">
            ${inv.reasons.map((r) => {
              const lvl = LEVEL[r.level] || LEVEL.review;
              return `
                <div class="check-item">
                  <div class="check-main">
                    <strong>${esc(r.title)}</strong>
                    ${r.detail ? `<div class="check-detail">${esc(r.detail)}</div>` : ''}
                    ${r.ref ? `<div class="check-ref">${esc(r.ref)}</div>` : ''}
                  </div>
                  ${badge(lvl.badge, lvl.label)}
                </div>`;
            }).join('')}
          </div>
          ${inv.reviewAction ? `<p class="form-hint">Décision humaine : ${inv.reviewAction === 'approved' ? 'facture acceptée' : 'facture refusée'} après le contrôle automatique.</p>` : ''}
          ${decide}
        </div>
      </div>`;

    $('detail-dialog-body').querySelectorAll('[data-decide]').forEach((btn) => {
      btn.addEventListener('click', () => run(btn, async () => {
        const approve = btn.getAttribute('data-decide') === 'approve';
        const ok = await confirmAction(approve ? 'Accepter cette facture ?' : 'Refuser cette facture ?',
          approve ? 'Elle deviendra bonne à payer. Cette décision est inscrite à votre nom et ne peut pas être annulée.'
                  : 'Elle ne pourra plus être payée. Cette décision est inscrite à votre nom et ne peut pas être annulée.',
          approve ? 'Accepter' : 'Refuser');
        if (!ok) return;
        await api('/api/app/inbox/checks/' + (approve ? 'approve' : 'reject'), { id: inv.id });
        toast(approve ? 'Facture acceptée' : 'Facture refusée');
        await reload();
        renderDetail();
      }));
    });
    return true;
  }

  // ------------------------------------------------------------------ Écran 3 : paiements
  function sealBadge(b) {
    if (b.seal_status === 'anchored') return badge('badge-ready', 'Empreinte inscrite sur Avalanche', 'check');
    if (b.seal_status === 'simulated') return badge('badge-scheduled', 'Empreinte inscrite (mode démonstration)');
    return badge('badge-paused', 'Empreinte pas encore inscrite');
  }

  function renderPayments() {
    const box = state.box;
    const ready = state.invoices.filter((i) => i.status === 'ready');
    const batches = box.batches || [];
    const sealed = batches.filter((b) => b.seal_status === 'anchored' || b.seal_status === 'simulated').length;
    const batchTotal = batches.reduce((s, b) => s + (b.total_cents || 0), 0);
    $('badge-payable-count').textContent = String(box.payable.count);
    $('badge-payable-count').title = 'Factures bonnes à payer';

    $('payment-cards').innerHTML = `
      <div class="card"><div class="card-title">À payer maintenant</div>
        <div class="kpi-value kpi-teal">${esc(cents(box.payable.total_cents))}</div>
        <div class="kpi-sub">${esc(plural(box.payable.count, 'facture'))} prête${box.payable.count > 1 ? 's' : ''} pour le prochain fichier</div></div>
      <div class="card"><div class="card-title">À payer à la main</div>
        <div class="kpi-value${box.payable.skipped ? ' kpi-warning' : ''}">${box.payable.skipped}</div>
        <div class="kpi-sub">acceptée${box.payable.skipped > 1 ? 's' : ''} sans fournisseur enregistré : hors fichier</div></div>
      <div class="card"><div class="card-title">Fichiers préparés</div>
        <div class="kpi-value">${batches.length}</div>
        <div class="kpi-sub">${esc(cents(batchTotal))} au total</div></div>
      <div class="card"><div class="card-title">Preuves inscrites</div>
        <div class="kpi-value">${sealed} / ${batches.length}</div>
        <div class="kpi-sub">fichiers dont l'empreinte est inscrite comme preuve datée</div></div>`;

    const createBtn = $('btn-create-batch');
    const blocked = !can('approver') ? 'Réservé aux personnes autorisées à valider les paiements.'
      : !box.bank ? 'Renseignez d\'abord le compte bancaire de votre entreprise (menu Réglages).'
      : box.payable.count === 0 ? 'Aucune facture bonne à payer pour le moment.' : '';
    createBtn.disabled = Boolean(blocked);
    createBtn.title = blocked;

    $('payable-tbody').innerHTML = ready.length === 0
      ? '<tr><td colspan="6" class="empty-cell">Aucune facture n\'attend de virement.</td></tr>'
      : ready.map((inv) => `
        <tr>
          <td class="mono"><strong>${esc(inv.number)}</strong></td>
          <td><strong>${esc(inv.supplier)}</strong></td>
          <td class="mono">${esc(spacedIban(inv.payeeIban))}</td>
          <td class="mono num"><strong>${esc(cents(inv.cents))}</strong></td>
          <td class="mono">${esc(day(inv.received))}</td>
          <td class="num"><button type="button" class="btn btn-sm" data-open="${esc(inv.id)}">Voir</button></td>
        </tr>`).join('');
    $('payable-tbody').querySelectorAll('[data-open]').forEach((btn) => {
      btn.addEventListener('click', () => openDetail(btn.getAttribute('data-open')));
    });

    const cont = $('batches-container');
    if (batches.length === 0) {
      cont.innerHTML = '<p class="card-text">Aucun fichier préparé. Le bouton « Préparer le fichier de virements » regroupe toutes les factures bonnes à payer.</p>';
      return;
    }
    cont.innerHTML = batches.map((b) => `
      <div class="batch-row">
        <div>
          <div class="batch-head"><strong>Fichier du ${esc(dayTime(b.created_at))}</strong> ${sealBadge(b)}</div>
          <div class="batch-meta">${esc(plural(b.tx_count, 'virement'))} · <strong class="mono">${esc(cents(b.total_cents))}</strong> · empreinte <span class="mono" title="${esc(b.file_sha256)}">${esc(shortHash(b.file_sha256))}</span></div>
        </div>
        <div class="batch-actions">
          ${b.seal_url ? `<a class="btn btn-sm" href="${esc(b.seal_url)}" target="_blank" rel="noopener noreferrer">Voir la preuve</a>` : ''}
          ${b.seal_status !== 'anchored' && b.seal_status !== 'simulated' && can('approver') ? `<button type="button" class="btn btn-sm" data-seal="${esc(b.id)}">Inscrire l'empreinte</button>` : ''}
          ${can('approver') ? `<a class="btn btn-sm btn-primary" href="/api/app/transfers/${encodeURIComponent(b.id)}.xml" download>Télécharger pour la banque</a>` : ''}
        </div>
      </div>`).join('');
    cont.querySelectorAll('[data-seal]').forEach((btn) => {
      btn.addEventListener('click', () => run(btn, async () => {
        const res = await api('/api/app/transfers/seal', { id: btn.getAttribute('data-seal') });
        toast(res.seal_error || 'Empreinte inscrite', Boolean(res.seal_error));
        await reload();
      }));
    });
  }

  async function createBatch(button) {
    const box = state.box;
    const ok = await confirmAction('Préparer le fichier de virements ?',
      plural(box.payable.count, 'facture') + ' pour ' + cents(box.payable.total_cents) + '. Le fichier est créé et son empreinte est inscrite comme preuve datée (sur la blockchain Avalanche quand le site y est relié), sans aucune donnée de facture. Vous l\'envoyez ensuite vous-même à votre banque.',
      'Préparer le fichier');
    if (!ok) return;
    await run(button, async () => {
      const res = await api('/api/app/transfers', {});
      toast(res.seal_error ? 'Fichier préparé. ' + res.seal_error : 'Fichier de virements préparé', Boolean(res.seal_error));
      await reload();
    });
  }

  async function auditFile(button) {
    const file = $('audit-file').files[0];
    if (!file) { toast('Choisissez d\'abord un fichier de virements (.xml)', true); return; }
    if (file.size > MAX_AUDIT_BYTES) { toast('Fichier trop volumineux (250 Ko au plus)', true); return; }
    await run(button, async () => {
      const res = await api('/api/app/transfers/audit', { content: await file.text() });
      const head = { ok: ['badge-ready', 'Rien d\'anormal : ce fichier peut partir à la banque'],
                     review: ['badge-paused', 'À vérifier avant l\'envoi'],
                     refused: ['badge-high-priority', 'Ne pas envoyer ce fichier'] }[res.verdict];
      $('audit-result').innerHTML = `
        <div class="audit-head">${badge(head[0], head[1])}
          <span class="form-hint">${esc(plural(res.lines.length, 'virement'))} · ${esc(cents(res.total_cents))} · ${res.counts.ok} conforme${res.counts.ok > 1 ? 's' : ''}, ${res.counts.review} à vérifier, ${res.counts.refused} refusé${res.counts.refused > 1 ? 's' : ''}</span></div>
        <div class="table-wrapper">
          <table>
            <thead><tr><th>N°</th><th>Bénéficiaire</th><th>Compte</th><th class="num">Montant</th><th>Verdict</th><th>Pourquoi</th></tr></thead>
            <tbody>${res.lines.map((l) => {
              const lvl = LEVEL[l.level] || LEVEL.review;
              return `<tr>
                <td class="mono">${l.position}</td>
                <td><strong>${esc(l.name || '—')}</strong></td>
                <td class="mono">${l.iban_tail ? '•••• ' + esc(l.iban_tail) : '—'}</td>
                <td class="mono num">${esc(cents(l.amount_cents))}</td>
                <td>${badge(lvl.badge, lvl.label)}</td>
                <td class="cell-why">${esc(l.why)}</td>
              </tr>`;
            }).join('')}</tbody>
          </table>
        </div>`;
      loadJournal(true);
    });
  }

  // ------------------------------------------------------------------ Écran 4 : factures émises
  const ISSUED = { undelivered: 'badge-slate', review: 'badge-paused', ok: 'badge-ready', refused: 'badge-high-priority',
                   paid: 'badge-scheduled' };
  const ISSUED_SHORT = { undelivered: 'À transmettre vous-même', review: 'En vérification chez le client', ok: 'Acceptée',
                         refused: 'Refusée', paid: 'Virement préparé' };

  function renderIssued() {
    const data = state.issued;
    const profile = data.profile;
    const list = data.issued || [];
    $('badge-issued-count').textContent = String(list.length);

    const bankLine = data.bank
      ? `<dt>Compte qui reçoit</dt><dd class="mono">${esc(spacedIban(data.bank.iban))}</dd>`
      : '<dt>Compte qui reçoit</dt><dd><span class="badge badge-paused">à renseigner dans Réglages</span></dd>';
    $('issued-profile').innerHTML = `
      <dl class="fact-list">
        <dt>Numéro SIREN</dt><dd class="mono">${profile ? esc(profile.siren) : '<span class="badge badge-paused">à renseigner</span>'}</dd>
        <dt>Adresse</dt><dd>${profile && profile.address ? esc(profile.address) : '—'}</dd>
        ${bankLine}
      </dl>
      <p class="form-hint">Le compte bancaire imprimé sur vos factures est toujours celui enregistré ici : personne ne peut le changer sur une facture.</p>
      ${can('admin') ? `
        <form id="form-profile" class="stack-form" autocomplete="off">
          <div class="form-row">
            <div class="filter-field"><label for="pro-siren">Numéro SIREN (9 chiffres)</label>
              <input type="text" id="pro-siren" inputmode="numeric" maxlength="14" value="${profile ? esc(profile.siren) : ''}" required /></div>
            <div class="filter-field"><label for="pro-address">Adresse</label>
              <input type="text" id="pro-address" maxlength="200" value="${profile ? esc(profile.address || '') : ''}" /></div>
          </div>
          <button class="btn btn-sm" type="submit">Enregistrer</button>
        </form>` : ''}`;
    const form = $('form-profile');
    if (form) {
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        run(form.querySelector('button'), async () => {
          await api('/api/app/einvoices/profile', { siren: $('pro-siren').value.trim(), address: $('pro-address').value.trim() });
          toast('Identité de l\'entreprise enregistrée');
          await reload();
        });
      });
    }

    const blocked = !can('approver') ? 'Réservé aux personnes autorisées à valider.'
      : !profile ? 'Renseignez d\'abord le numéro SIREN de votre entreprise.'
      : !data.bank ? 'Renseignez d\'abord le compte bancaire de votre entreprise (menu Réglages).' : '';
    $('btn-issue').disabled = Boolean(blocked);
    $('btn-issue').title = blocked;
    updateIssueTotal();

    $('issued-tbody').innerHTML = list.length === 0
      ? '<tr><td colspan="6" class="empty-cell">Aucune facture émise pour le moment.</td></tr>'
      : list.map((inv) => `
        <tr>
          <td class="mono"><strong>${esc(inv.number)}</strong></td>
          <td><strong>${esc(inv.buyer_name)}</strong><div class="cell-sub mono">SIREN ${esc(inv.buyer_siren)}</div></td>
          <td class="mono num"><strong>${esc(cents(inv.total_cents))}</strong></td>
          <td class="mono">${esc(day(inv.created_at))}</td>
          <td><span title="${esc(inv.status_text)}">${badge(ISSUED[inv.status] || 'badge-slate', ISSUED_SHORT[inv.status] || inv.status)}</span></td>
          <td class="num"><a class="btn btn-sm" href="/api/app/einvoices/${encodeURIComponent(inv.id)}.pdf" download>PDF</a></td>
        </tr>`).join('');
  }

  function addIssueLine() {
    const wrap = $('iss-lines');
    if (wrap.children.length >= 50) return;
    const row = document.createElement('div');
    row.className = 'line-row';
    row.innerHTML = `
      <div class="filter-field filter-grow"><label>Désignation</label><input type="text" class="iss-label" maxlength="120" placeholder="Par exemple : entretien du véhicule" required /></div>
      <div class="filter-field line-qty"><label>Quantité</label><input type="number" class="iss-qty" min="1" max="9999" step="1" value="1" required /></div>
      <div class="filter-field line-price"><label>Prix unitaire HT (€)</label><input type="text" class="iss-price mono" inputmode="decimal" placeholder="150,00" required /></div>
      <button type="button" class="icon-btn line-del" title="Retirer cette ligne" aria-label="Retirer cette ligne">&times;</button>`;
    row.querySelectorAll('input').forEach((input, index) => {
      // Les libellés visent leur champ sans identifiant fixe : les lignes sont créées à la demande.
      const id = 'iss-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7) + '-' + index;
      input.id = id;
      input.closest('.filter-field').querySelector('label').setAttribute('for', id);
      input.addEventListener('input', updateIssueTotal);
    });
    row.querySelector('.line-del').addEventListener('click', () => {
      if (wrap.children.length > 1) row.remove();
      updateIssueTotal();
    });
    wrap.appendChild(row);
    updateIssueTotal();
  }

  function priceCents(text) {
    const m = /^(\d{1,7})(?:[.,](\d{1,2}))?$/.exec(String(text).trim());
    return m ? Number(m[1]) * 100 + Number((m[2] || '0').padEnd(2, '0')) : null;
  }

  function updateIssueTotal() {
    let ht = 0;
    $('iss-lines').querySelectorAll('.line-row').forEach((row) => {
      const qty = Number(row.querySelector('.iss-qty').value);
      const price = priceCents(row.querySelector('.iss-price').value);
      if (Number.isInteger(qty) && qty > 0 && price) ht += qty * price;
    });
    const rate = (state.issued && state.issued.vat_percent) || 20;
    const tax = Math.floor((ht * rate + 50) / 100);
    $('iss-total').textContent = 'Hors taxes ' + cents(ht) + ' · TVA ' + rate + ' % ' + cents(tax) + ' · Total ' + cents(ht + tax);
  }

  let lookupTimer = null;
  function lookupBuyer() {
    clearTimeout(lookupTimer);
    const siren = $('iss-siren').value.replace(/[\s.]/g, '');
    const hint = $('iss-lookup');
    const name = $('iss-name');
    if (!/^\d{9}$/.test(siren)) { hint.textContent = ''; name.readOnly = false; return; }
    lookupTimer = setTimeout(async () => {
      try {
        const res = await api('/api/app/einvoices/lookup', { siren });
        if (res.found) {
          name.value = res.name;
          name.readOnly = true;
          hint.textContent = 'Ce client est sur VaultGuard : la facture lui sera remise directement, déjà contrôlée.';
        } else {
          name.readOnly = false;
          hint.textContent = 'Ce client n\'est pas sur VaultGuard : indiquez son nom, puis téléchargez la facture pour la lui transmettre.';
        }
      } catch (err) {
        hint.textContent = err.message;
      }
    }, 350);
  }

  async function submitIssue(button) {
    const lines = [];
    $('iss-lines').querySelectorAll('.line-row').forEach((row) => {
      lines.push({ label: row.querySelector('.iss-label').value.trim(), quantity: Number(row.querySelector('.iss-qty').value),
                   unit_price: row.querySelector('.iss-price').value.trim() });
    });
    await run(button, async () => {
      const inv = await api('/api/app/einvoices', { buyer_siren: $('iss-siren').value.trim(), buyer_name: $('iss-name').value.trim(), lines });
      toast('Facture ' + inv.number + ' créée. ' + (ISSUED_SHORT[inv.status] || ''));
      $('form-issue').reset();
      $('iss-name').readOnly = false;
      $('iss-lookup').textContent = '';
      $('iss-lines').textContent = '';
      addIssueLine();
      await reload();
    });
  }

  // ------------------------------------------------------------------ Fenêtre : alertes
  function alerts() {
    const box = state.box;
    const out = [];
    const week = Date.now() / 1000 - 7 * 86400;
    for (const inv of state.invoices) {
      if (inv.status === 'review') {
        out.push({ level: 1, badge: 'badge-paused', tag: 'À vérifier', title: inv.number + ' — ' + inv.supplier + ' (' + cents(inv.cents) + ')',
                   text: mainReason(inv), open: inv.id });
      } else if (inv.status === 'refused' && inv.received >= week) {
        out.push({ level: 0, badge: 'badge-high-priority', tag: 'Fraude arrêtée', title: inv.number + ' — ' + inv.supplier + ' (' + cents(inv.cents) + ')',
                   text: mainReason(inv), open: inv.id });
      }
    }
    if (!box.bank) {
      out.push({ level: 1, badge: 'badge-paused', tag: 'Réglage', title: 'Compte bancaire de votre entreprise non renseigné',
                 text: 'Sans lui, aucun fichier de virements ne peut être préparé.', dialog: 'dialog-settings' });
    }
    if ((box.senders || []).length === 0) {
      out.push({ level: 2, badge: 'badge-slate', tag: 'Réglage', title: 'Aucun expéditeur autorisé',
                 text: 'Les mails envoyés à votre adresse de dépôt sont ignorés tant que vous n\'avez autorisé personne.', dialog: 'dialog-settings' });
    }
    if (box.payable.skipped > 0) {
      out.push({ level: 2, badge: 'badge-in-progress', tag: 'À payer à la main', title: plural(box.payable.skipped, 'facture') + ' acceptée' + (box.payable.skipped > 1 ? 's' : '') + ' hors fichier de virements',
                 text: 'Leur fournisseur n\'est pas dans votre liste : ajoutez-le pour les prochaines.', status: 'accepted' });
    }
    for (const p of box.payees || []) {
      if (!p.is_active) {
        out.push({ level: 2, badge: 'badge-slate', tag: 'Délai de sécurité', title: p.name + ' vient d\'être ajouté',
                   text: 'Ses factures demandent votre accord pendant encore ' + delay(p.remaining_seconds) + '.', dialog: 'dialog-suppliers' });
      }
    }
    const ignored = Object.entries(box.ignored_7d || {});
    if (ignored.length) {
      const n = ignored.reduce((s, e) => s + e[1], 0);
      out.push({ level: 2, badge: 'badge-slate', tag: 'Mails ignorés', title: plural(n, 'mail') + ' ignoré' + (n > 1 ? 's' : '') + ' sur 7 jours',
                 text: ignored.map(([k, v]) => v + ' × ' + (IGNORED[k] || k)).join(', ') + '.', dialog: 'dialog-settings' });
    }
    return out.sort((a, b) => a.level - b.level);
  }

  function delay(seconds) {
    if (seconds >= 3600) return Math.ceil(seconds / 3600) + ' h';
    return Math.max(1, Math.ceil(seconds / 60)) + ' min';
  }

  function renderAlerts() {
    const list = alerts();
    const urgent = list.filter((a) => a.level < 2).length;
    $('badge-alerts-count').textContent = String(urgent);
    $('badge-alerts-count').classList.toggle('tab-badge-alert', urgent > 0);
    $('alerts-list').innerHTML = list.length === 0
      ? '<p class="card-text">Rien à signaler.</p>'
      : list.map((a, i) => `
        <div class="check-item">
          <div class="check-main">
            ${badge(a.badge, a.tag)} <strong>${esc(a.title)}</strong>
            <div class="check-detail">${esc(a.text)}</div>
          </div>
          <button type="button" class="btn btn-sm" data-alert="${i}">${a.open ? 'Ouvrir' : 'Voir'}</button>
        </div>`).join('');
    $('alerts-list').querySelectorAll('[data-alert]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const a = list[Number(btn.getAttribute('data-alert'))];
        closeDialog('dialog-alerts');
        if (a.open) openDetail(a.open);
        else if (a.status) goToStatus(a.status);
        else if (a.dialog) openDialog(a.dialog);
      });
    });
  }

  // ------------------------------------------------------------------ Fenêtre : fournisseurs
  function renderSuppliers() {
    const payees = state.box.payees || [];
    const admin = can('admin');
    $('form-supplier').classList.toggle('is-hidden', !admin);
    $('suppliers-grid').innerHTML = payees.length === 0
      ? '<p class="card-text">Aucun fournisseur enregistré. Ajoutez vos fournisseurs habituels avec le compte bancaire que vous leur connaissez : c\'est la référence de tous les contrôles.</p>'
      : payees.map((p) => {
        const invs = state.invoices.filter((i) => i.supplier === p.name);
        const refused = invs.filter((i) => i.status === 'refused').length;
        return `
          <div class="card">
            <div class="supplier-head">
              <h3 class="supplier-name">${esc(p.name)}</h3>
              ${p.is_active ? badge('badge-ready', 'Habituel', 'check') : badge('badge-paused', 'Délai de sécurité : ' + delay(p.remaining_seconds), 'clock')}
            </div>
            <dl class="fact-list">
              <dt>Compte enregistré</dt><dd class="mono">${esc(spacedIban(p.iban))}</dd>
              <dt>Ajouté le</dt><dd>${esc(day(p.created_at))}</dd>
              <dt>Factures reçues</dt><dd>${invs.length}${refused ? ' dont ' + badge('badge-high-priority', refused + ' refusée' + (refused > 1 ? 's' : '')) : ''}</dd>
            </dl>
            ${admin ? `<button type="button" class="btn btn-sm btn-danger" data-remove-payee="${esc(p.id)}" data-name="${esc(p.name)}">Retirer de la liste</button>` : ''}
          </div>`;
      }).join('');
    $('suppliers-grid').querySelectorAll('[data-remove-payee]').forEach((btn) => {
      btn.addEventListener('click', () => run(btn, async () => {
        const ok = await confirmAction('Retirer ce fournisseur ?', btn.getAttribute('data-name') + ' ne sera plus reconnu : ses prochaines factures vous seront soumises.', 'Retirer');
        if (!ok) return;
        await api('/api/app/payees/remove', { id: btn.getAttribute('data-remove-payee') });
        toast('Fournisseur retiré');
        await reload();
      }));
    });
  }

  // ------------------------------------------------------------------ Fenêtre : réglages
  function renderSettings() {
    const box = state.box;
    const admin = can('admin');
    const off = admin ? '' : 'disabled';
    $('settings-body').innerHTML = `
      ${admin ? '' : '<p class="form-hint block-gap">Seul un administrateur de l\'entreprise peut modifier ces réglages.</p>'}
      <div class="two-col block-gap">
        <div class="card">
          <div class="card-title">Votre adresse de dépôt</div>
          <p class="card-text">Transférez vos factures à cette adresse : elles sont contrôlées à l'arrivée.</p>
          <div class="inline-form">
            <span class="mono address-box" id="inbox-address">${esc(box.address)}</span>
            <button type="button" class="btn btn-sm" id="btn-copy-address">Copier</button>
          </div>
          <div class="card-title section-title">Qui a le droit d'y envoyer des factures</div>
          <div class="checklist-list">
            ${(box.senders || []).length === 0 ? '<p class="card-text">Personne pour l\'instant : tous les mails sont ignorés.</p>' : box.senders.map((s) => `
              <div class="check-item">
                <span class="mono">${esc(s.email)}</span>
                ${admin ? `<button type="button" class="btn btn-sm" data-remove-sender="${esc(s.id)}">Retirer</button>` : ''}
              </div>`).join('')}
          </div>
          <form id="form-sender" class="inline-form" autocomplete="off">
            <input type="email" id="sender-email" class="filter-grow" placeholder="comptabilite@votre-entreprise.fr" aria-label="Adresse mail à autoriser" required ${off} />
            <button type="submit" class="btn btn-sm" ${off}>Autoriser</button>
          </form>
        </div>
        <div class="card">
          <div class="card-title">Accord humain</div>
          <p class="card-text">Au-dessus de ce montant, une facture même conforme attend votre accord.</p>
          <form id="form-threshold" class="inline-form" autocomplete="off">
            <input type="number" id="threshold-euros" min="0" step="1" value="${Math.round((box.review_threshold_cents || 0) / 100)}" aria-label="Seuil en euros" required ${off} />
            <span class="form-hint">euros</span>
            <button type="submit" class="btn btn-sm" ${off}>Enregistrer</button>
          </form>
          <div class="card-title section-title">Compte bancaire de votre entreprise</div>
          <p class="card-text">Le compte qui paie vos fournisseurs et qui reçoit le paiement de vos factures émises.</p>
          <form id="form-bank" class="stack-form" autocomplete="off">
            <div class="filter-field"><label for="bank-holder">Titulaire</label>
              <input type="text" id="bank-holder" maxlength="70" value="${box.bank ? esc(box.bank.holder) : ''}" required ${off} /></div>
            <div class="filter-field"><label for="bank-iban">IBAN</label>
              <input type="text" id="bank-iban" class="mono" maxlength="42" value="${box.bank ? esc(spacedIban(box.bank.iban)) : ''}" required ${off} /></div>
            <button type="submit" class="btn btn-sm" ${off}>Enregistrer le compte</button>
          </form>
        </div>
      </div>
      <p class="form-hint">Équipe, clés d'accès des assistants automatiques, coffre et règles de paiement : <a href="/app/classique">ouvrir l'ancienne interface</a>.</p>`;

    $('btn-copy-address').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(box.address); toast('Adresse copiée'); }
      catch (_) { toast('Copie impossible : sélectionnez l\'adresse à la main', true); }
    });
    $('settings-body').querySelectorAll('[data-remove-sender]').forEach((btn) => {
      btn.addEventListener('click', () => run(btn, async () => {
        await api('/api/app/inbox/senders/remove', { id: btn.getAttribute('data-remove-sender') });
        toast('Expéditeur retiré');
        await reload(true);
      }));
    });
    const submit = (formId, task) => {
      $(formId).addEventListener('submit', (e) => {
        e.preventDefault();
        run(e.target.querySelector('button[type="submit"]'), async () => { await task(); await reload(true); });
      });
    };
    submit('form-sender', async () => {
      await api('/api/app/inbox/senders', { email: $('sender-email').value.trim() });
      toast('Expéditeur autorisé');
    });
    submit('form-threshold', async () => {
      await api('/api/app/inbox/threshold', { cents: Math.round(Number($('threshold-euros').value) * 100) });
      toast('Seuil enregistré');
    });
    submit('form-bank', async () => {
      await api('/api/app/inbox/bank', { holder: $('bank-holder').value.trim(), iban: $('bank-iban').value.trim() });
      toast('Compte bancaire enregistré');
    });
  }

  // ------------------------------------------------------------------ Fenêtre : historique et preuves
  function journalDetail(d) {
    const parts = [];
    if (d.number) parts.push('n° ' + d.number);
    if (d.name) parts.push(d.name);
    if (d.email) parts.push(d.email);
    if (d.verdict) parts.push('verdict : ' + ((LEVEL[d.verdict] || {}).label || d.verdict).toLowerCase());
    if (d.amount_cents != null) parts.push(cents(d.amount_cents));
    if (d.total_cents != null) parts.push(cents(d.total_cents));
    if (d.tx_count != null) parts.push(plural(d.tx_count, 'virement'));
    if (d.review_threshold_cents != null) parts.push('seuil : ' + cents(d.review_threshold_cents));
    if (d.iban_tail) parts.push('compte •••• ' + d.iban_tail);
    if (d.reason) parts.push(IGNORED[d.reason] || d.reason);
    if (d.status) parts.push(d.status === 'anchored' ? 'sur Avalanche' : d.status === 'simulated' ? 'mode démonstration' : d.status);
    return parts.join(' · ');
  }

  async function loadJournal(silent) {
    try {
      state.journal = await api('/api/app/audit');
    } catch (err) {
      if (!silent) toast(err.message, true);
      return;
    }
    $('journal-tbody').innerHTML = state.journal.length === 0
      ? '<tr><td colspan="5" class="empty-cell">Aucune action enregistrée.</td></tr>'
      : state.journal.map((e) => `
        <tr>
          <td class="mono">${esc(dayTime(e.created_at))}</td>
          <td>${e.user_email ? esc(e.user_email) : '<span class="cell-sub">VaultGuard (automatique)</span>'}</td>
          <td><strong>${esc(ACTIONS[e.action] || e.action)}</strong></td>
          <td class="cell-why">${esc(journalDetail(e.details || {}))}</td>
          <td class="mono" title="${esc(e.entry_hash)}">${esc(shortHash(e.entry_hash))}</td>
        </tr>`).join('');
  }

  // ------------------------------------------------------------------ Dépôt d'une facture
  function toBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(binary);
  }

  function pickUpload(file) {
    const tooBig = file && file.size > MAX_UPLOAD_BYTES;
    $('upload-name').textContent = !file ? '' : tooBig ? file.name + ' — trop volumineux (2 Mo au plus)' : file.name;
    $('upload-name').classList.toggle('drop-error', Boolean(tooBig));
    $('btn-upload').disabled = !file || tooBig || !can('approver');
    pickUpload.file = file && !tooBig ? file : null;
  }

  async function upload(button) {
    const file = pickUpload.file;
    if (!file) return;
    await run(button, async () => {
      const res = await api('/api/app/inbox/upload', { name: file.name, content_b64: toBase64(await file.arrayBuffer()) });
      $('upload-file').value = '';
      pickUpload(null);
      closeDialog('dialog-upload');
      await reload();
      toast('Facture contrôlée : ' + ((LEVEL[res.verdict] || {}).label || res.verdict).toLowerCase());
      openDetail(res.id);
    });
  }

  // ------------------------------------------------------------------ Navigation et rafraîchissement
  function switchTab(tab) {
    ui.tab = tab;
    document.querySelectorAll('.nav-tab').forEach((btn) => {
      const on = btn.getAttribute('data-tab') === tab;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.toggle('active', panel.id === 'panel-' + tab));
    if (tab === 'invoices') renderInvoices();
    if (tab === 'overview') renderSankey();
  }

  function renderAll(withSettings) {
    renderFilterOptions();
    renderOverview();
    renderInvoices();
    renderPayments();
    renderIssued();
    renderAlerts();
    renderSuppliers();
    if (withSettings || !$('dialog-settings').open) renderSettings();
  }

  // withSettings : après une action faite dans la fenêtre Réglages, on la redessine même ouverte.
  async function reload(withSettings) {
    const [box, issued] = await Promise.all([api('/api/app/inbox'), api('/api/app/einvoices')]);
    state.box = box;
    state.issued = issued;
    state.invoices = (box.checks || []).map((c) => adapt(c, box));
    $('load-error').classList.add('is-hidden');
    renderAll(withSettings);
    if ($('dialog-journal').open) loadJournal(true);
  }

  async function loadOrgs() {
    state.orgs = await api('/api/app/orgs');
    const active = state.orgs.find((o) => o.is_active) || state.orgs[0];
    state.role = (active && active.role) || 'viewer';
    const select = $('org-select');
    select.innerHTML = state.orgs.map((o) => `<option value="${esc(o.id)}"${o.is_active ? ' selected' : ''}>${esc(o.name)}</option>`).join('');
    select.classList.toggle('org-select-single', state.orgs.length < 2);
    select.disabled = state.orgs.length < 2;
    $('btn-open-upload').disabled = !can('approver');
    $('btn-open-upload').title = can('approver') ? '' : 'Réservé aux personnes autorisées à valider.';
  }

  function bind() {
    document.querySelectorAll('.nav-tab').forEach((btn) => btn.addEventListener('click', () => switchTab(btn.getAttribute('data-tab'))));

    $('btn-theme-toggle').addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      store('vaultguard_theme', next);
    });
    $('btn-toggle-sidebar').addEventListener('click', () => {
      const collapsed = $('app-sidebar').classList.toggle('collapsed');
      $('btn-toggle-sidebar').setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    });
    $('btn-focus-search').addEventListener('click', () => { switchTab('invoices'); $('f-search').focus(); });

    $('btn-sankey-lifecycle').addEventListener('click', () => { ui.sankeyMode = 'lifecycle'; renderSankey(); });
    $('btn-sankey-supplier').addEventListener('click', () => { ui.sankeyMode = 'supplier'; renderSankey(); });

    const openers = { 'btn-open-alerts': 'dialog-alerts', 'btn-sidebar-alerts': 'dialog-alerts', 'btn-sidebar-suppliers': 'dialog-suppliers',
                      'btn-sidebar-settings': 'dialog-settings', 'btn-open-upload': 'dialog-upload' };
    for (const [btn, dlg] of Object.entries(openers)) $(btn).addEventListener('click', () => openDialog(dlg));
    $('btn-sidebar-journal').addEventListener('click', () => { openDialog('dialog-journal'); loadJournal(); });
    document.querySelectorAll('[data-close]').forEach((btn) => btn.addEventListener('click', () => closeDialog(btn.getAttribute('data-close'))));
    document.querySelectorAll('dialog').forEach((dlg) => {
      dlg.addEventListener('click', (e) => { if (e.target === dlg && dlg.id !== 'dialog-confirm') dlg.close(); });
    });
    $('dialog-confirm').addEventListener('cancel', (e) => { e.preventDefault(); settleConfirm(false); });
    $('btn-confirm-no').addEventListener('click', () => settleConfirm(false));
    $('btn-confirm-yes').addEventListener('click', () => settleConfirm(true));

    for (const [id, key] of FILTERS) {
      $(id).addEventListener('input', () => {
        ui.query[key] = $(id).value;
        ui.viewId = '';
        ui.ids = null;
        renderInvoices();
      });
    }
    document.querySelectorAll('#invoices-table th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const col = th.getAttribute('data-sort');
        ui.query.sortDir = ui.query.sortBy === col && ui.query.sortDir === 'asc' ? 'desc' : 'asc';
        ui.query.sortBy = col;
        renderInvoices();
      });
    });
    $('btn-reset-filters').addEventListener('click', () => { resetQuery(); syncFilters(); renderInvoices(); });
    $('btn-save-view').addEventListener('click', () => {
      const custom = state.views.filter((v) => v.id.startsWith('custom_'));
      if (custom.length >= 8) { toast('8 vues enregistrées au plus : supprimez-en une', true); return; }
      const q = ui.query;
      const label = [q.status !== 'all' ? STATUS[q.status].label : '', q.supplier !== 'all' ? q.supplier : '', q.search].filter(Boolean).join(' · ');
      const view = { id: 'custom_' + Date.now(), name: (label || 'Ma vue ' + (custom.length + 1)).slice(0, 40), query: Object.assign({}, q) };
      state.views.push(view);
      ui.viewId = view.id;
      saveViews();
      renderViews();
      toast('Vue enregistrée sur cet ordinateur');
    });
    $('btn-export-csv').addEventListener('click', exportCsv);
    $('btn-export-pdf').addEventListener('click', () => window.print());

    $('btn-create-batch').addEventListener('click', () => createBatch($('btn-create-batch')));
    $('btn-audit-file').addEventListener('click', () => auditFile($('btn-audit-file')));

    $('btn-iss-add-line').addEventListener('click', addIssueLine);
    $('iss-siren').addEventListener('input', lookupBuyer);
    $('form-issue').addEventListener('submit', (e) => { e.preventDefault(); submitIssue($('btn-issue')); });
    addIssueLine();

    $('form-supplier').addEventListener('submit', (e) => {
      e.preventDefault();
      run($('btn-add-supplier'), async () => {
        await api('/api/app/payees', { name: $('sup-name').value.trim(), iban: $('sup-iban').value.trim() });
        $('form-supplier').reset();
        toast('Fournisseur ajouté. Un délai de sécurité s\'applique avant qu\'il soit « habituel ».');
        await reload();
      });
    });

    $('upload-file').addEventListener('change', () => pickUpload($('upload-file').files[0] || null));
    const drop = $('upload-drop');
    ['dragenter', 'dragover'].forEach((type) => drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add('drop-over'); }));
    ['dragleave', 'drop'].forEach((type) => drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.remove('drop-over'); }));
    drop.addEventListener('drop', (e) => pickUpload((e.dataTransfer && e.dataTransfer.files[0]) || null));
    $('btn-upload').addEventListener('click', () => upload($('btn-upload')));

    $('btn-verify-chain').addEventListener('click', () => run($('btn-verify-chain'), async () => {
      const res = await api('/api/app/audit/verify', {});
      $('verify-chain-result').textContent = res.message;
      $('verify-chain-result').classList.toggle('text-danger', !res.valid);
    }));

    $('org-select').addEventListener('change', () => run(null, async () => {
      await api('/api/app/orgs/switch', { org_id: $('org-select').value });
      window.location.reload();
    }));
    $('btn-logout').addEventListener('click', () => run($('btn-logout'), async () => {
      await api('/api/auth/logout', {});
      window.location.href = '/login';
    }));
  }

  async function init() {
    const theme = store('vaultguard_theme');
    if (theme === 'dark' || theme === 'light') document.documentElement.setAttribute('data-theme', theme);
    loadViews();
    bind();
    try {
      const me = await api('/api/auth/me');
      state.csrf = me.csrf || '';
      state.user = me.user;
      $('user-email-display').textContent = me.user.email;
      await loadOrgs();
      await reload();
    } catch (err) {
      $('load-error').textContent = 'Chargement impossible : ' + (err.message || 'erreur inconnue') + '. Rechargez la page.';
      $('load-error').classList.remove('is-hidden');
      return;
    }
    // Les factures arrivent par mail à tout moment : on rafraîchit sans déranger une saisie ou une fenêtre ouverte.
    setInterval(() => {
      if (document.hidden || anyDialogOpen()) return;
      const el = document.activeElement;
      if (el && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) return;
      reload().catch(() => {});
    }, REFRESH_MS);
  }

  init();
})();
