/* app.js — Client frontend VaultGuard v3
   Règles strictes de sécurité :
     - Pas de CDN, code vanille
     - Aucune injection innerHTML avec des données dynamiques (textContent uniquement)
     - Adresses et hash protégés contre les débordements
     - Jeton CSRF systématiquement envoyé sur chaque requête POST
*/
(function () {
  'use strict';

  // État local de la session
  let state = {
    csrf: '',
    user: null,
    org: null,
    role: 'viewer',
    allOrgs: [],
    currentSection: 'overview',
    currentPayment: null
  };

  // Niveaux de rôles numériques
  const ROLE_LEVELS = {
    viewer: 1,
    approver: 2,
    admin: 3,
    owner: 4
  };

  function hasRole(minRole) {
    return (ROLE_LEVELS[state.role] || 0) >= (ROLE_LEVELS[minRole] || 0);
  }

  // ------------------------------------------------------------------ Requêtes API sécurisées
  async function api(path, opts = {}) {
    opts.headers = opts.headers || {};
    if (opts.method && opts.method.toUpperCase() === 'POST') {
      opts.headers['Content-Type'] = 'application/json';
      if (state.csrf) {
        opts.headers['X-CSRF-Token'] = state.csrf;
      }
    }

    const res = await fetch(path, opts);
    if (res.status === 401) {
      window.location.href = '/login';
      return null;
    }

    const ctype = res.headers.get('content-type') || '';
    if (ctype.includes('application/json')) {
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || 'Erreur requête (' + res.status + ')');
      }
      return data;
    }
    return res;
  }

  // ------------------------------------------------------------------ Initialisation
  async function init() {
    try {
      // 1. Récupération des informations de compte
      const me = await api('/api/auth/me');
      if (!me || !me.authenticated) {
        window.location.href = '/login';
        return;
      }
      state.user = me.user;
      state.org = me.org;
      state.csrf = me.csrf || '';

      // 2. Affichage des informations utilisateur
      const emailEl = document.getElementById('user-email-display');
      if (emailEl) emailEl.textContent = state.user.email;

      // 3. Récupération des organisations de l'utilisateur
      await loadOrgs();

      // 4. Navigation
      setupNavigation();

      // 5. Chargement de la section courante
      handleRoute();
    } catch (err) {
      console.error('Erreur initialisation :', err);
      window.location.href = '/login';
    }
  }

  // ------------------------------------------------------------------ Gestion des Organisations
  async function loadOrgs() {
    try {
      const orgs = await api('/api/app/orgs');
      if (!orgs) return;
      state.allOrgs = orgs;

      const select = document.getElementById('org-select');
      select.textContent = ''; // Vider

      orgs.forEach(o => {
        const opt = document.createElement('option');
        opt.value = o.id;
        opt.textContent = o.name + (o.is_suspended ? ' (Suspendue)' : '');
        if (o.is_active) {
          opt.selected = true;
          state.role = o.role || 'viewer';
          state.org = o;
        }
        select.appendChild(opt);
      });

      updateRoleUI();

      select.onchange = async () => {
        const newOrgId = select.value;
        if (newOrgId && (!state.org || newOrgId !== state.org.id)) {
          try {
            await api('/api/app/orgs/switch', {
              method: 'POST',
              body: JSON.stringify({ org_id: newOrgId })
            });
            window.location.reload();
          } catch (e) {
            alert(e.message);
            select.value = state.org ? state.org.id : '';
          }
        }
      };
    } catch (e) {
      console.error('Erreur chargement organisations :', e);
    }
  }

  function updateRoleUI() {
    // Badge de rôle
    const badge = document.getElementById('user-role-badge');
    badge.className = 'badge badge-' + state.role;
    badge.textContent = state.role.toUpperCase();

    // Alerte suspension
    const alertBox = document.getElementById('global-alert-container');
    if (state.org && state.org.is_suspended) {
      alertBox.textContent = '';
      const div = document.createElement('div');
      div.className = 'alert-box alert-warning';
      div.textContent = 'Organisation suspendue : consultation en lecture seule active. Toute modification est bloquée.';
      alertBox.appendChild(div);
      alertBox.style.display = 'block';
    } else {
      alertBox.style.display = 'none';
    }

    // Affichage conditionnel selon les rôles
    const isAdmin = hasRole('admin');
    const isApprover = hasRole('approver');
    const isOwner = hasRole('owner');

    const newKeyBox = document.getElementById('new-key-box');
    if (newKeyBox) newKeyBox.style.display = isAdmin ? 'block' : 'none';

    const newSupBox = document.getElementById('new-supplier-box');
    if (newSupBox) newSupBox.style.display = isAdmin ? 'block' : 'none';

    const btnSavePolicy = document.getElementById('btn-save-policy');
    if (btnSavePolicy) btnSavePolicy.style.display = isAdmin ? 'inline-block' : 'none';

    const btnAnchor = document.getElementById('btn-anchor-audit');
    if (btnAnchor) btnAnchor.style.display = isAdmin ? 'inline-block' : 'none';

    const inviteBox = document.getElementById('invite-box');
    if (inviteBox) inviteBox.style.display = isAdmin ? 'block' : 'none';

    const optInvOwner = document.getElementById('opt-inv-owner');
    if (optInvOwner) optInvOwner.style.display = isOwner ? 'block' : 'none';

    const btnSaveOrg = document.getElementById('btn-save-org-settings');
    if (btnSaveOrg) btnSaveOrg.style.display = isAdmin ? 'inline-block' : 'none';

    const pendingInvites = document.getElementById('pending-invites-container');
    if (pendingInvites) pendingInvites.style.display = isAdmin ? 'block' : 'none';
  }

  // ------------------------------------------------------------------ Navigation par onglets
  function setupNavigation() {
    window.addEventListener('hashchange', handleRoute);
  }

  function handleRoute() {
    const hash = (window.location.hash || '#overview').replace('#', '');
    const validSections = ['overview', 'payments', 'api-keys', 'suppliers', 'policy', 'audit', 'team', 'settings'];
    const target = validSections.includes(hash) ? hash : 'overview';

    // Mise à jour de la barre latérale
    document.querySelectorAll('#main-nav .nav-link').forEach(link => {
      if (link.getAttribute('data-section') === target) {
        link.classList.add('active');
      } else {
        link.classList.remove('active');
      }
    });

    // Affichage de la section
    document.querySelectorAll('.app-section').forEach(sec => {
      sec.classList.remove('active');
    });
    const targetSec = document.getElementById('sec-' + target);
    if (targetSec) targetSec.classList.add('active');

    state.currentSection = target;
    loadSectionData(target);
  }

  function loadSectionData(sec) {
    if (sec === 'overview') loadOverview();
    else if (sec === 'payments') loadPayments();
    else if (sec === 'api-keys') loadApiKeys();
    else if (sec === 'suppliers') loadSuppliers();
    else if (sec === 'policy') loadPolicy();
    else if (sec === 'audit') loadAudit();
    else if (sec === 'team') loadTeam();
    else if (sec === 'settings') loadSettings();
  }

  // ------------------------------------------------------------------ 1. Vue d'ensemble
  async function loadOverview() {
    try {
      const data = await api('/api/app/overview');
      if (!data) return;

      document.getElementById('stat-today-count').textContent = data.stats.today_count;
      document.getElementById('stat-today-wei').textContent = formatWei(data.stats.today_gwei);
      document.getElementById('stat-blocked-count').textContent = data.stats.blocked_count;
      document.getElementById('stat-pending-count').textContent = data.stats.pending_count;
      document.getElementById('stat-protected-wei').textContent = formatWei(data.stats.protected_gwei);

      const statusEl = document.getElementById('stat-vault-status');
      const isPaused = Boolean((data.vault && data.vault.is_paused) || (data.org && data.org.vault_paused));
      const isSuspended = Boolean(data.org && data.org.is_suspended);
      if (isPaused) {
        statusEl.textContent = 'Gelé';
        statusEl.style.color = 'var(--status-red)';
      } else if (isSuspended) {
        statusEl.textContent = 'Suspendu';
        statusEl.style.color = 'var(--status-amber)';
      } else {
        statusEl.textContent = 'Actif';
        statusEl.style.color = 'var(--status-green)';
      }

      const btnUnpause = document.getElementById('btn-unpause-vault');
      if (btnUnpause) {
        btnUnpause.style.display = (isPaused && hasRole('owner')) ? 'block' : 'none';
      }

      const addrEl = document.getElementById('stat-vault-addr');
      addrEl.textContent = data.org.vault_address || (data.org.network === 'mock' ? 'Simulation active' : 'Non configuré');

      // 5 derniers paiements
      const payments = await api('/api/app/payments');
      const tbody = document.getElementById('overview-payments-tbody');
      tbody.textContent = '';
      if (!payments || payments.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 5;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucun paiement enregistré pour le moment.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }

      payments.slice(0, 5).forEach(p => {
        const tr = document.createElement('tr');

        const tdDate = document.createElement('td');
        tdDate.className = 'mono';
        tdDate.textContent = formatTimestamp(p.created_at);
        tr.appendChild(tdDate);

        const tdTo = document.createElement('td');
        tdTo.className = 'mono break-all';
        tdTo.textContent = p.recipient;
        tr.appendChild(tdTo);

        const tdAmount = document.createElement('td');
        tdAmount.className = 'mono';
        tdAmount.textContent = formatWei(p.amount_gwei);
        tr.appendChild(tdAmount);

        const tdMemo = document.createElement('td');
        tdMemo.textContent = p.memo || '—';
        tr.appendChild(tdMemo);

        const tdDec = document.createElement('td');
        tdDec.appendChild(createDecisionBadge(p.decision));
        tr.appendChild(tdDec);

        tbody.appendChild(tr);
      });
    } catch (e) {
      console.error('Erreur overview :', e);
    }
  }

  // ------------------------------------------------------------------ 2. Paiements
  async function loadPayments() {
    const status = document.getElementById('filter-payment-status').value;
    const url = '/api/app/payments' + (status ? '?status=' + encodeURIComponent(status) : '');
    try {
      const list = await api(url);
      const tbody = document.getElementById('payments-tbody');
      tbody.textContent = '';

      if (!list || list.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 7;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucune transaction ne correspond à ce filtre.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }

      list.forEach(p => {
        const tr = document.createElement('tr');

        const tdId = document.createElement('td');
        tdId.className = 'mono';
        tdId.textContent = p.id.slice(0, 10) + '...';
        tr.appendChild(tdId);

        const tdDate = document.createElement('td');
        tdDate.className = 'mono';
        tdDate.textContent = formatTimestamp(p.created_at);
        tr.appendChild(tdDate);

        const tdTo = document.createElement('td');
        tdTo.className = 'mono break-all';
        tdTo.textContent = p.recipient;
        tr.appendChild(tdTo);

        const tdAmount = document.createElement('td');
        tdAmount.className = 'mono';
        tdAmount.textContent = formatWei(p.amount_gwei);
        tr.appendChild(tdAmount);

        const tdMemo = document.createElement('td');
        tdMemo.textContent = p.memo || '—';
        tr.appendChild(tdMemo);

        const tdDec = document.createElement('td');
        tdDec.appendChild(createDecisionBadge(p.decision));
        tr.appendChild(tdDec);

        const tdAction = document.createElement('td');
        const btn = document.createElement('button');
        btn.className = 'btn btn-secondary';
        btn.style.padding = '3px 8px';
        btn.textContent = 'Détails';
        btn.onclick = () => openPaymentModal(p);
        tdAction.appendChild(btn);
        tr.appendChild(tdAction);

        tbody.appendChild(tr);
      });
    } catch (e) {
      console.error('Erreur paiements :', e);
    }
  }

  function openPaymentModal(p) {
    state.currentPayment = p;
    document.getElementById('pm-id').textContent = p.id;
    document.getElementById('pm-to').textContent = p.recipient;
    document.getElementById('pm-amount').textContent = formatWei(p.amount_gwei) + ' (' + p.amount_gwei + ' gwei)';
    document.getElementById('pm-memo').textContent = p.memo || '—';
    document.getElementById('pm-user-req').textContent = p.user_request || '—';

    // Documents
    const docsEl = document.getElementById('pm-docs');
    docsEl.textContent = '';
    if (p.documents && p.documents.length > 0) {
      p.documents.forEach((d, idx) => {
        const div = document.createElement('div');
        div.style.marginBottom = '4px';
        div.style.background = 'var(--bg)';
        div.style.padding = '4px 6px';
        div.style.borderRadius = '3px';
        div.className = 'break-all';
        div.textContent = (d.source ? '[' + d.source + '] ' : '') + (d.content || '');
        docsEl.appendChild(div);
      });
    } else {
      docsEl.textContent = 'Aucun document associé';
    }

    // Raisons pare-feu
    const reasonsEl = document.getElementById('pm-reasons');
    reasonsEl.textContent = '';
    if (p.reasons && p.reasons.length > 0) {
      p.reasons.forEach(r => {
        const div = document.createElement('div');
        div.style.marginBottom = '6px';
        div.style.padding = '6px 8px';
        div.style.borderRadius = '4px';
        div.style.background = 'var(--status-red-bg)';
        div.style.border = '1px solid var(--status-red-border)';

        const title = document.createElement('div');
        title.style.fontWeight = '600';
        title.style.color = 'var(--status-red)';
        title.textContent = r.title || r.code;
        div.appendChild(title);

        if (r.detail) {
          const detail = document.createElement('div');
          detail.style.fontSize = '12px';
          detail.textContent = r.detail;
          div.appendChild(detail);
        }
        reasonsEl.appendChild(div);
      });
    } else {
      reasonsEl.textContent = 'Aucun blocage signalé (verdict favorable)';
    }

    // Décision
    const decEl = document.getElementById('pm-decision');
    decEl.textContent = p.decision.toUpperCase() + ' (état on-chain : ' + (p.chain_status || 'none') + ')';

    // Tx Hash
    const txRow = document.getElementById('pm-tx-row');
    if (p.tx_hash) {
      document.getElementById('pm-tx').textContent = p.tx_hash;
      txRow.style.display = 'block';
    } else {
      txRow.style.display = 'none';
    }

    // Boutons arbitrage
    const footer = document.getElementById('pm-actions-footer');
    const isPending = p.decision === 'pending_review';
    const canArbitrate = hasRole('approver') && !state.org.is_suspended;
    footer.style.display = isPending && canArbitrate ? 'flex' : 'none';

    document.getElementById('payment-modal').classList.add('active');
  }

  // Actions valider / rejeter
  document.getElementById('pm-close').onclick = () => {
    document.getElementById('payment-modal').classList.remove('active');
  };

  document.getElementById('pm-btn-approve').onclick = async () => {
    if (!state.currentPayment) return;
    try {
      await api('/api/app/payments/approve', {
        method: 'POST',
        body: JSON.stringify({ id: state.currentPayment.id })
      });
      document.getElementById('payment-modal').classList.remove('active');
      loadPayments();
    } catch (e) {
      alert(e.message);
    }
  };

  document.getElementById('pm-btn-reject').onclick = async () => {
    if (!state.currentPayment) return;
    try {
      await api('/api/app/payments/reject', {
        method: 'POST',
        body: JSON.stringify({ id: state.currentPayment.id })
      });
      document.getElementById('payment-modal').classList.remove('active');
      loadPayments();
    } catch (e) {
      alert(e.message);
    }
  };

  document.getElementById('filter-payment-status').onchange = loadPayments;
  document.getElementById('btn-refresh-payments').onclick = loadPayments;

  // ------------------------------------------------------------------ 3. Agents & Clés API
  async function loadApiKeys() {
    try {
      const keys = await api('/api/app/api-keys');
      const tbody = document.getElementById('api-keys-tbody');
      tbody.textContent = '';

      if (!keys || keys.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 6;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucune clé API configurée pour cette organisation.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }

      keys.forEach(k => {
        const tr = document.createElement('tr');

        const tdName = document.createElement('td');
        tdName.style.fontWeight = '600';
        tdName.textContent = k.name;
        tr.appendChild(tdName);

        const tdPrefix = document.createElement('td');
        tdPrefix.className = 'mono';
        tdPrefix.textContent = k.key_prefix + '...';
        tr.appendChild(tdPrefix);

        const tdStatus = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = 'badge ' + (k.is_active ? 'badge-status-allowed' : 'badge-status-blocked');
        badge.textContent = k.is_active ? 'Active' : 'Révoquée';
        tdStatus.appendChild(badge);
        tr.appendChild(tdStatus);

        const tdQuar = document.createElement('td');
        if (k.quarantined_until && k.quarantined_until > Date.now() / 1000) {
          tdQuar.style.color = 'var(--status-red)';
          tdQuar.textContent = 'Oui (' + (k.quarantine_reason || 'suspecte') + ')';
        } else {
          tdQuar.textContent = 'Non';
        }
        tr.appendChild(tdQuar);

        const tdDate = document.createElement('td');
        tdDate.className = 'mono';
        tdDate.textContent = formatTimestamp(k.created_at);
        tr.appendChild(tdDate);

        const tdAction = document.createElement('td');
        if (k.is_active && hasRole('admin') && !state.org.is_suspended) {
          const btnRevoke = document.createElement('button');
          btnRevoke.className = 'btn btn-danger';
          btnRevoke.style.padding = '2px 8px';
          btnRevoke.textContent = 'Révoquer';
          btnRevoke.onclick = async () => {
            if (confirm('Révoquer la clé pour "' + k.name + '" ? Cette action est irréversible.')) {
              try {
                await api('/api/app/api-keys/revoke', {
                  method: 'POST',
                  body: JSON.stringify({ id: k.id })
                });
                loadApiKeys();
              } catch (e) {
                alert(e.message);
              }
            }
          };
          tdAction.appendChild(btnRevoke);
        } else {
          tdAction.textContent = '—';
        }
        tr.appendChild(tdAction);

        tbody.appendChild(tr);
      });
    } catch (e) {
      console.error('Erreur clés API :', e);
    }
  }

  document.getElementById('create-key-form').onsubmit = async (e) => {
    e.preventDefault();
    const nameInput = document.getElementById('key-name');
    const name = nameInput.value.trim();
    if (!name) return;

    try {
      const res = await api('/api/app/api-keys', {
        method: 'POST',
        body: JSON.stringify({ name })
      });
      nameInput.value = '';
      const resBox = document.getElementById('new-key-result');
      document.getElementById('new-key-value').textContent = res.raw_key;
      resBox.style.display = 'block';
      loadApiKeys();
    } catch (err) {
      alert(err.message);
    }
  };

  // ------------------------------------------------------------------ 4. Fournisseurs
  async function loadSuppliers() {
    try {
      const sups = await api('/api/app/suppliers');
      const tbody = document.getElementById('suppliers-tbody');
      tbody.textContent = '';

      if (!sups || sups.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 5;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucun fournisseur approuvé dans le carnet d\'adresses.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }

      sups.forEach(s => {
        const tr = document.createElement('tr');

        const tdName = document.createElement('td');
        tdName.style.fontWeight = '600';
        tdName.textContent = s.name;
        tr.appendChild(tdName);

        const tdAddr = document.createElement('td');
        tdAddr.className = 'mono break-all';
        tdAddr.textContent = s.address;
        tr.appendChild(tdAddr);

        const tdState = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = 'badge ' + (s.is_payable ? 'badge-status-allowed' : 'badge-status-pending');
        badge.textContent = s.is_payable ? 'Payable' : 'En attente d\'activation';
        tdState.appendChild(badge);
        tr.appendChild(tdState);

        const tdDelay = document.createElement('td');
        tdDelay.className = 'mono';
        if (s.is_payable) {
          tdDelay.textContent = 'Actif';
        } else {
          const h = Math.ceil(s.remaining_seconds / 3600);
          tdDelay.textContent = h + ' h restante' + (h > 1 ? 's' : '');
        }
        tr.appendChild(tdDelay);

        const tdAction = document.createElement('td');
        if (hasRole('admin') && !state.org.is_suspended) {
          const btnDel = document.createElement('button');
          btnDel.className = 'btn btn-danger';
          btnDel.style.padding = '2px 8px';
          btnDel.textContent = 'Retirer';
          btnDel.onclick = async () => {
            if (confirm('Retirer le fournisseur "' + s.name + '" ?')) {
              try {
                await api('/api/app/suppliers/remove', {
                  method: 'POST',
                  body: JSON.stringify({ id: s.id })
                });
                loadSuppliers();
              } catch (e) {
                alert(e.message);
              }
            }
          };
          tdAction.appendChild(btnDel);
        } else {
          tdAction.textContent = '—';
        }
        tr.appendChild(tdAction);

        tbody.appendChild(tr);
      });
    } catch (e) {
      console.error('Erreur fournisseurs :', e);
    }
  }

  document.getElementById('add-supplier-form').onsubmit = async (e) => {
    e.preventDefault();
    const name = document.getElementById('sup-name').value.trim();
    const address = document.getElementById('sup-addr').value.trim();
    if (!name || !address) return;

    try {
      await api('/api/app/suppliers', {
        method: 'POST',
        body: JSON.stringify({ name, address })
      });
      document.getElementById('sup-name').value = '';
      document.getElementById('sup-addr').value = '';
      loadSuppliers();
    } catch (err) {
      alert(err.message);
    }
  };

  // ------------------------------------------------------------------ 5. Politique
  async function loadPolicy() {
    try {
      const pol = await api('/api/app/policy');
      if (!pol) return;

      document.getElementById('pol-max-tx').value = gweiToAvaxInput(pol.max_tx_gwei);
      document.getElementById('pol-max-daily').value = gweiToAvaxInput(pol.max_daily_gwei);
      document.getElementById('pol-human-threshold').value = gweiToAvaxInput(pol.human_threshold_gwei);
      document.getElementById('pol-activation-delay').value = pol.activation_delay;
      document.getElementById('pol-circuit-breaker').value = pol.circuit_breaker_limit;

      document.getElementById('help-max-tx').textContent = 'Actuel : ' + formatWei(pol.max_tx_gwei);
      document.getElementById('help-max-daily').textContent = 'Actuel : ' + formatWei(pol.max_daily_gwei);
      document.getElementById('help-human-threshold').textContent = 'Actuel : ' + formatWei(pol.human_threshold_gwei);

      // Mise à jour lecture seule si pas admin
      const isEditable = hasRole('admin') && !state.org.is_suspended;
      ['pol-max-tx', 'pol-max-daily', 'pol-human-threshold', 'pol-activation-delay', 'pol-circuit-breaker'].forEach(id => {
        document.getElementById(id).disabled = !isEditable;
      });
    } catch (e) {
      console.error('Erreur politique :', e);
    }
  }

  document.getElementById('policy-form').onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById('policy-msg');
    msg.style.display = 'none';

    try {
      const payload = {
        max_tx_gwei: avaxInputToGwei(document.getElementById('pol-max-tx').value),
        max_daily_gwei: avaxInputToGwei(document.getElementById('pol-max-daily').value),
        human_threshold_gwei: avaxInputToGwei(document.getElementById('pol-human-threshold').value),
        activation_delay: parseInt(document.getElementById('pol-activation-delay').value, 10),
        circuit_breaker_limit: parseInt(document.getElementById('pol-circuit-breaker').value, 10)
      };

      await api('/api/app/policy', {
        method: 'POST',
        body: JSON.stringify(payload)
      });

      msg.className = 'alert-box alert-success';
      msg.textContent = 'Politique financière enregistrée avec succès.';
      msg.style.display = 'block';
      loadPolicy();
    } catch (err) {
      msg.className = 'alert-box alert-danger';
      msg.textContent = err.message;
      msg.style.display = 'block';
    }
  };

  // ------------------------------------------------------------------ 6. Journal d'audit
  async function loadAudit() {
    try {
      const logs = await api('/api/app/audit');
      const tbody = document.getElementById('audit-tbody');
      tbody.textContent = '';

      if (!logs || logs.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 6;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucune entrée d\'audit pour cette organisation.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }

      logs.forEach(l => {
        const tr = document.createElement('tr');

        const tdId = document.createElement('td');
        tdId.className = 'mono';
        tdId.textContent = '#' + l.id;
        tr.appendChild(tdId);

        const tdDate = document.createElement('td');
        tdDate.className = 'mono';
        tdDate.textContent = formatTimestamp(l.created_at);
        tr.appendChild(tdDate);

        const tdAction = document.createElement('td');
        tdAction.style.fontWeight = '600';
        tdAction.textContent = l.action;
        tr.appendChild(tdAction);

        const tdUser = document.createElement('td');
        tdUser.textContent = l.user_email || l.ip || 'Système';
        tr.appendChild(tdUser);

        const tdDetails = document.createElement('td');
        tdDetails.className = 'mono break-all';
        tdDetails.style.fontSize = '11px';
        tdDetails.textContent = JSON.stringify(l.details || {});
        tr.appendChild(tdDetails);

        const tdHash = document.createElement('td');
        tdHash.className = 'mono break-all';
        tdHash.style.fontSize = '11px';
        tdHash.textContent = (l.entry_hash || '').slice(0, 16) + '...';
        tr.appendChild(tdHash);

        tbody.appendChild(tr);
      });
    } catch (e) {
      console.error('Erreur audit :', e);
    }
  }

  document.getElementById('btn-verify-audit').onclick = async () => {
    const resBox = document.getElementById('audit-verify-result');
    resBox.style.display = 'none';

    try {
      const res = await api('/api/app/audit/verify', { method: 'POST', body: '{}' });
      resBox.className = 'alert-box ' + (res.valid ? 'alert-success' : 'alert-danger');
      resBox.textContent = res.message;
      resBox.style.display = 'block';
    } catch (e) {
      resBox.className = 'alert-box alert-danger';
      resBox.textContent = e.message;
      resBox.style.display = 'block';
    }
  };

  document.getElementById('btn-anchor-audit').onclick = async () => {
    try {
      const res = await api('/api/app/audit/anchor', { method: 'POST', body: '{}' });
      alert('Rapport scellé on-chain avec succès ! Hash: ' + res.sha256);
      loadAudit();
    } catch (e) {
      alert(e.message);
    }
  };

  // ------------------------------------------------------------------ 7. Équipe
  async function loadTeam() {
    try {
      const members = await api('/api/app/team/members');
      const tbody = document.getElementById('team-members-tbody');
      tbody.textContent = '';

      if (!members || members.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 4;
        td.style.textAlign = 'center';
        td.textContent = 'Aucun membre.';
        tr.appendChild(td);
        tbody.appendChild(tr);
      } else {
        members.forEach(m => {
          const tr = document.createElement('tr');

          const tdEmail = document.createElement('td');
          tdEmail.style.fontWeight = '600';
          tdEmail.textContent = m.email;
          tr.appendChild(tdEmail);

          const tdRole = document.createElement('td');
          const badge = document.createElement('span');
          badge.className = 'badge badge-' + m.role;
          badge.textContent = m.role.toUpperCase();
          tdRole.appendChild(badge);
          tr.appendChild(tdRole);

          const tdDate = document.createElement('td');
          tdDate.className = 'mono';
          tdDate.textContent = formatTimestamp(m.created_at);
          tr.appendChild(tdDate);

          const tdAction = document.createElement('td');
          const canManage = hasRole('admin') && !state.org.is_suspended;
          if (canManage) {
            // Sélecteur de rôle
            const sel = document.createElement('select');
            sel.className = 'select-input';
            sel.style.padding = '2px 6px';
            sel.style.marginRight = '6px';
            ['viewer', 'approver', 'admin', 'owner'].forEach(r => {
              if (r === 'owner' && !hasRole('owner')) return;
              const opt = document.createElement('option');
              opt.value = r;
              opt.textContent = r;
              if (r === m.role) opt.selected = true;
              sel.appendChild(opt);
            });

            sel.onchange = async () => {
              try {
                await api('/api/app/team/members/role', {
                  method: 'POST',
                  body: JSON.stringify({ member_id: m.id, role: sel.value })
                });
                loadTeam();
              } catch (e) {
                alert(e.message);
                sel.value = m.role;
              }
            };
            tdAction.appendChild(sel);

            // Bouton Retirer
            const btnDel = document.createElement('button');
            btnDel.className = 'btn btn-danger';
            btnDel.style.padding = '2px 6px';
            btnDel.textContent = 'Retirer';
            btnDel.onclick = async () => {
              if (confirm('Retirer ' + m.email + ' de l\'organisation ?')) {
                try {
                  await api('/api/app/team/members/remove', {
                    method: 'POST',
                    body: JSON.stringify({ member_id: m.id })
                  });
                  loadTeam();
                } catch (e) {
                  alert(e.message);
                }
              }
            };
            tdAction.appendChild(btnDel);
          } else {
            tdAction.textContent = '—';
          }
          tr.appendChild(tdAction);

          tbody.appendChild(tr);
        });
      }

      // Invitations en attente (admin+)
      if (hasRole('admin')) {
        const invites = await api('/api/app/team/invites');
        const invTbody = document.getElementById('team-invites-tbody');
        invTbody.textContent = '';

        if (!invites || invites.length === 0) {
          const tr = document.createElement('tr');
          const td = document.createElement('td');
          td.colSpan = 4;
          td.style.textAlign = 'center';
          td.style.color = 'var(--ink-muted)';
          td.textContent = 'Aucune invitation en attente.';
          tr.appendChild(td);
          invTbody.appendChild(tr);
        } else {
          invites.forEach(inv => {
            const tr = document.createElement('tr');

            const tdEmail = document.createElement('td');
            tdEmail.textContent = inv.email;
            tr.appendChild(tdEmail);

            const tdRole = document.createElement('td');
            tdRole.textContent = inv.role;
            tr.appendChild(tdRole);

            const tdExp = document.createElement('td');
            tdExp.className = 'mono';
            tdExp.textContent = formatTimestamp(inv.expires_at);
            tr.appendChild(tdExp);

            const tdAction = document.createElement('td');
            const btnRev = document.createElement('button');
            btnRev.className = 'btn btn-danger';
            btnRev.style.padding = '2px 6px';
            btnRev.textContent = 'Annuler';
            btnRev.onclick = async () => {
              try {
                await api('/api/app/team/invites/revoke', {
                  method: 'POST',
                  body: JSON.stringify({ invite_id: inv.id })
                });
                loadTeam();
              } catch (e) {
                alert(e.message);
              }
            };
            tdAction.appendChild(btnRev);
            tr.appendChild(tdAction);

            invTbody.appendChild(tr);
          });
        }
      }
    } catch (e) {
      console.error('Erreur équipe :', e);
    }
  }

  document.getElementById('invite-form').onsubmit = async (e) => {
    e.preventDefault();
    const email = document.getElementById('inv-email').value.trim();
    const role = document.getElementById('inv-role').value;
    if (!email) return;

    try {
      const res = await api('/api/app/team/invites', {
        method: 'POST',
        body: JSON.stringify({ email, role })
      });
      document.getElementById('inv-email').value = '';

      const linkVal = window.location.origin + '/signup?invite=' + encodeURIComponent(res.token);
      document.getElementById('invite-link-val').textContent = linkVal;
      document.getElementById('invite-result-box').style.display = 'block';
      loadTeam();
    } catch (err) {
      alert(err.message);
    }
  };

  // ------------------------------------------------------------------ 9. Paramètres
  async function loadSettings() {
    try {
      const s = await api('/api/app/settings');
      if (s) {
        document.getElementById('set-org-name').value = s.name || '';
        document.getElementById('set-network').value = s.network || 'mock';
        document.getElementById('set-vault-addr').value = s.vault_address || '';
        document.getElementById('set-canary-addr').value = s.canary_address || '';

        const isEditable = hasRole('admin') && !state.org.is_suspended;
        ['set-org-name', 'set-network', 'set-vault-addr', 'set-canary-addr'].forEach(id => {
          document.getElementById(id).disabled = !isEditable;
        });
      }

      // État 2FA
      const status2fa = document.getElementById('2fa-status-text');
      const btnSetup2fa = document.getElementById('btn-setup-2fa');
      if (state.user && state.user.totp_enabled) {
        status2fa.textContent = 'Activée (votre compte est sécurisé par un code TOTP à 6 chiffres).';
        status2fa.style.color = 'var(--status-green)';
        btnSetup2fa.style.display = 'none';
      } else {
        status2fa.textContent = 'Désactivée (recommandé d\'activer pour sécuriser les opérations sensibles).';
        status2fa.style.color = 'var(--status-amber)';
        btnSetup2fa.style.display = 'inline-block';
      }
    } catch (e) {
      console.error('Erreur paramètres :', e);
    }
  }

  document.getElementById('org-settings-form').onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById('org-settings-msg');
    msg.style.display = 'none';

    try {
      await api('/api/app/settings', {
        method: 'POST',
        body: JSON.stringify({
          name: document.getElementById('set-org-name').value.trim(),
          network: document.getElementById('set-network').value,
          vault_address: document.getElementById('set-vault-addr').value.trim(),
          canary_address: document.getElementById('set-canary-addr').value.trim()
        })
      });
      msg.className = 'alert-box alert-success';
      msg.textContent = 'Paramètres de l\'organisation mis à jour avec succès.';
      msg.style.display = 'block';
      loadOrgs();
    } catch (err) {
      msg.className = 'alert-box alert-danger';
      msg.textContent = err.message;
      msg.style.display = 'block';
    }
  };

  // 2FA Setup
  document.getElementById('btn-setup-2fa').onclick = async () => {
    try {
      const res = await api('/api/auth/2fa/setup', { method: 'POST', body: '{}' });
      document.getElementById('2fa-secret-val').textContent = res.secret;
      document.getElementById('2fa-setup-box').style.display = 'block';
      document.getElementById('btn-setup-2fa').style.display = 'none';
    } catch (e) {
      alert(e.message);
    }
  };

  document.getElementById('btn-enable-2fa').onclick = async () => {
    const code = document.getElementById('2fa-confirm-code').value.trim();
    if (!code) return;

    try {
      await api('/api/auth/2fa/enable', {
        method: 'POST',
        body: JSON.stringify({ code })
      });
      alert('Double authentification activée avec succès !');
      window.location.reload();
    } catch (e) {
      alert(e.message);
    }
  };

  // Mot de passe
  document.getElementById('change-pwd-form').onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById('pwd-msg');
    msg.style.display = 'none';

    const old_password = document.getElementById('pwd-old').value;
    const new_password = document.getElementById('pwd-new').value;

    try {
      await api('/api/auth/password', {
        method: 'POST',
        body: JSON.stringify({ old_password, new_password })
      });
      document.getElementById('pwd-old').value = '';
      document.getElementById('pwd-new').value = '';
      msg.className = 'alert-box alert-success';
      msg.textContent = 'Mot de passe modifié. Toutes les autres sessions ont été fermées.';
      msg.style.display = 'block';
    } catch (err) {
      msg.className = 'alert-box alert-danger';
      msg.textContent = err.message;
      msg.style.display = 'block';
    }
  };

  // Sessions
  document.getElementById('btn-logout-all').onclick = async () => {
    if (confirm('Voulez-vous déconnecter toutes vos sessions sur tous vos appareils ?')) {
      try {
        await api('/api/auth/logout-all', { method: 'POST', body: '{}' });
        window.location.href = '/login';
      } catch (e) {
        alert(e.message);
      }
    }
  };

  document.getElementById('btn-logout').onclick = async () => {
    try {
      await api('/api/auth/logout', { method: 'POST', body: '{}' });
    } catch (e) {
      // Ignorer
    }
    window.location.href = '/login';
  };

  // Dégel du coffre (owner + 2FA)
  const modalUnpause = document.getElementById('modal-unpause-vault');
  const btnUnpause = document.getElementById('btn-unpause-vault');
  const btnUnpauseClose = document.getElementById('modal-unpause-close');
  const btnUnpauseCancel = document.getElementById('modal-unpause-cancel');
  const btnUnpauseConfirm = document.getElementById('modal-unpause-confirm');
  const unpauseTotpInput = document.getElementById('unpause-totp-input');
  const unpauseErrorMsg = document.getElementById('unpause-error-msg');

  if (btnUnpause) {
    btnUnpause.onclick = () => {
      if (unpauseTotpInput) unpauseTotpInput.value = '';
      if (unpauseErrorMsg) {
        unpauseErrorMsg.style.display = 'none';
        unpauseErrorMsg.textContent = '';
      }
      if (modalUnpause) modalUnpause.style.display = 'flex';
      if (unpauseTotpInput) unpauseTotpInput.focus();
    };
  }

  const closeUnpauseModal = () => {
    if (modalUnpause) modalUnpause.style.display = 'none';
    if (unpauseTotpInput) unpauseTotpInput.value = '';
    if (unpauseErrorMsg) unpauseErrorMsg.style.display = 'none';
  };

  if (btnUnpauseClose) btnUnpauseClose.onclick = closeUnpauseModal;
  if (btnUnpauseCancel) btnUnpauseCancel.onclick = closeUnpauseModal;

  if (btnUnpauseConfirm) {
    btnUnpauseConfirm.onclick = async () => {
      const code = (unpauseTotpInput ? unpauseTotpInput.value : '').trim();
      if (!code || code.length !== 6) {
        if (unpauseErrorMsg) {
          unpauseErrorMsg.textContent = 'Veuillez saisir un code 2FA valide à 6 chiffres.';
          unpauseErrorMsg.style.display = 'block';
        }
        return;
      }
      try {
        await api('/api/app/vault/unpause', {
          method: 'POST',
          body: JSON.stringify({ code: code })
        });
        closeUnpauseModal();
        alert('Coffre dégelé avec succès. Les opérations sont réactivées.');
        loadOverview();
      } catch (err) {
        if (unpauseErrorMsg) {
          unpauseErrorMsg.textContent = err.message;
          unpauseErrorMsg.style.display = 'block';
        }
      }
    };
  }

  // ------------------------------------------------------------------ Utilitaires
  // Montants stockés en gwei entiers (1 AVAX = 10^9 gwei) : exacts en JavaScript jusqu'à ~9 millions d'AVAX.
  function formatWei(gwei) {
    if (gwei === undefined || gwei === null) return '0 AVAX';
    const avax = Number(gwei) / 1e9;
    return avax.toLocaleString('fr-FR', { maximumFractionDigits: 9 }) + ' AVAX';
  }

  function gweiToAvaxInput(gwei) {
    const g = BigInt(gwei || 0);
    const frac = (g % 1000000000n).toString().padStart(9, '0').replace(/0+$/, '');
    return (g / 1000000000n).toString() + (frac ? '.' + frac : '');
  }

  // « 0,1 » ou « 0.1 » AVAX -> 100000000 gwei, sans passer par un flottant.
  function avaxInputToGwei(text) {
    const m = String(text).trim().replace(',', '.').match(/^(\d{1,7})(?:\.(\d{1,9}))?$/);
    if (!m) throw new Error('Montant invalide : un nombre d’AVAX, 9 décimales au plus (ex. 0,1)');
    return Number(BigInt(m[1]) * 1000000000n + BigInt((m[2] || '').padEnd(9, '0')));
  }

  function formatTimestamp(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toISOString().replace('T', ' ').slice(0, 19);
  }

  function createDecisionBadge(dec) {
    const span = document.createElement('span');
    if (dec === 'allowed') {
      span.className = 'badge badge-status-allowed';
      span.textContent = 'Autorisé';
    } else if (dec === 'blocked') {
      span.className = 'badge badge-status-blocked';
      span.textContent = 'Bloqué';
    } else if (dec === 'pending_review') {
      span.className = 'badge badge-status-pending';
      span.textContent = 'En revue';
    } else {
      span.className = 'badge badge-viewer';
      span.textContent = dec || 'Inconnu';
    }
    return span;
  }

  // Lancement
  window.addEventListener('DOMContentLoaded', init);
})();
