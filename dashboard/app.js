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

    ['add-sender-form', 'add-payee-form'].forEach(id => {
      document.getElementById(id).style.display = isAdmin ? '' : 'none';
    });
    document.getElementById('btn-save-threshold').style.display = isAdmin ? '' : 'none';
    document.getElementById('inbox-threshold').disabled = !isAdmin;

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
    const validSections = ['overview', 'inbox', 'einvoices', 'payments', 'api-keys', 'suppliers', 'policy', 'audit', 'team', 'settings'];
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
    // Les verdicts arrivent quelques secondes après l'envoi d'un mail : la page se met à jour seule.
    if (state.inboxTimer) clearInterval(state.inboxTimer);
    state.inboxTimer = sec === 'inbox' ? setInterval(loadInbox, 5000) : null;
    if (sec === 'overview') loadOverview();
    else if (sec === 'inbox') loadInbox();
    else if (sec === 'einvoices') loadEinvoices();
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
        statusEl.textContent = 'Ouvert';
        statusEl.style.color = 'var(--status-green)';
      }

      const btnUnpause = document.getElementById('btn-unpause-vault');
      if (btnUnpause) {
        btnUnpause.style.display = (isPaused && hasRole('owner')) ? 'block' : 'none';
      }

      const addrEl = document.getElementById('stat-vault-addr');
      addrEl.textContent = isPaused
        ? 'Plus aucun paiement ne part tant que vous ne le rouvrez pas'
        : (data.org.vault_address || (data.org.network === 'mock' ? 'Coffre de démonstration' : 'Non configuré'));

      api('/api/app/inbox').then(box => {
        if (box) document.getElementById('stat-inbox-review').textContent = box.checks.filter(c => c.verdict === 'review').length;
      }).catch(() => {});

      const payments = await api('/api/app/payments') || [];
      state.payments = payments;
      renderTodo(payments.filter(p => p.decision === 'pending_review'));

      // 5 dernières demandes
      const tbody = document.getElementById('overview-payments-tbody');
      tbody.textContent = '';
      if (payments.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 5;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucune demande de paiement pour le moment.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }

      payments.slice(0, 5).forEach(p => {
        const tr = document.createElement('tr');

        const tdDate = document.createElement('td');
        tdDate.textContent = formatTimestamp(p.created_at);
        tr.appendChild(tdDate);

        const tdTo = document.createElement('td');
        tdTo.className = 'break-all';
        tdTo.textContent = whoIsPaid(p);
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
      if (!status) state.payments = list || [];
      const tbody = document.getElementById('payments-tbody');
      tbody.textContent = '';

      if (!list || list.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 7;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucune demande ne correspond.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }

      list.forEach(p => {
        const tr = document.createElement('tr');

        const tdDate = document.createElement('td');
        tdDate.textContent = formatTimestamp(p.created_at);
        tr.appendChild(tdDate);

        const tdTo = document.createElement('td');
        tdTo.className = 'break-all';
        tdTo.textContent = whoIsPaid(p);
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

        const tdWhy = document.createElement('td');
        tdWhy.textContent = mainReason(p);
        tr.appendChild(tdWhy);

        const tdAction = document.createElement('td');
        const btn = document.createElement('button');
        btn.className = 'btn btn-secondary';
        btn.style.padding = '3px 8px';
        btn.textContent = p.decision === 'pending_review' ? 'Décider' : 'Détails';
        btn.onclick = () => openPaymentModal(p);
        tdAction.appendChild(btn);
        tr.appendChild(tdAction);

        tbody.appendChild(tr);
      });
    } catch (e) {
      console.error('Erreur paiements :', e);
    }
  }

  // Le fichier choisi ne quitte pas le navigateur : son empreinte est calculée ici et comparée à celles du paiement.
  async function verifyInvoiceFile(ev) {
    const out = document.getElementById('pm-verify-result');
    const file = ev.target.files && ev.target.files[0];
    const p = state.currentPayment;
    out.textContent = '';
    if (!file || !p) return;
    if (!window.crypto || !window.crypto.subtle) {
      out.textContent = 'Vérification indisponible dans ce navigateur (connexion HTTPS requise).';
      return;
    }
    const digest = await window.crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    const hex = Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
    const match = (p.documents || []).some(d => d.file_sha256 === hex || d.sha256 === hex);
    out.style.color = match ? 'var(--status-green)' : 'var(--status-red)';
    out.textContent = match
      ? 'Ce fichier est bien celui que VaultGuard a jugé pour ce paiement.'
      : 'Ce fichier ne correspond à aucun document de ce paiement (empreinte ' + hex.slice(0, 16) + '…).';
  }
  document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('pm-verify-file');
    if (input) input.addEventListener('change', verifyInvoiceFile);
  });

  function openPaymentModal(p) {
    state.currentPayment = p;
    document.getElementById('pm-id').textContent = p.id;
    document.getElementById('pm-to').textContent = whoIsPaid(p);
    document.getElementById('pm-addr').textContent = p.recipient;
    document.getElementById('pm-amount').textContent = formatWei(p.amount_gwei);
    document.getElementById('pm-memo').textContent = p.memo || '—';
    document.getElementById('pm-user-req').textContent = p.user_request || '—';

    // Documents : VaultGuard ne garde que leur empreinte SHA-256, jamais leur contenu
    const docsEl = document.getElementById('pm-docs');
    docsEl.textContent = '';
    if (p.documents && p.documents.length > 0) {
      p.documents.forEach((d, idx) => {
        const div = document.createElement('div');
        div.style.marginBottom = '4px';
        div.style.background = 'var(--bg)';
        div.style.padding = '4px 6px';
        div.style.borderRadius = '3px';
        div.className = 'break-all mono';
        div.textContent = 'Document ' + (d.n || idx + 1) + ' · ' + (d.chars || 0) + ' caractères analysés · SHA-256 '
          + (d.file_sha256 || d.sha256 || '');
        docsEl.appendChild(div);
      });
    } else {
      docsEl.textContent = 'Aucun document associé';
    }
    document.getElementById('pm-verify-file').value = '';
    document.getElementById('pm-verify-result').textContent = '';

    // Raisons pare-feu
    const reasonsEl = document.getElementById('pm-reasons');
    reasonsEl.textContent = '';
    if (p.reasons && p.reasons.length > 0) {
      p.reasons.forEach(r => {
        const div = document.createElement('div');
        div.className = 'reason-box ' + ({ BLOCK: 'reason-box-block', CONFIRM: 'reason-box-confirm', ALLOW: 'reason-box-ok' }[r.action] || '');

        const title = document.createElement('div');
        title.className = 'reason-title';
        title.textContent = r.title || r.code;
        div.appendChild(title);

        if (r.detail && r.code !== 'ok') {
          const detail = document.createElement('div');
          detail.className = 'reason-detail';
          detail.textContent = r.detail;
          div.appendChild(detail);
        }
        reasonsEl.appendChild(div);
      });
    } else {
      reasonsEl.textContent = 'Rien d\'anormal.';
    }

    // Résultat, en une phrase
    const decEl = document.getElementById('pm-decision');
    decEl.textContent = '';
    decEl.appendChild(createDecisionBadge(p.decision));
    decEl.appendChild(document.createTextNode(' ' + plainResult(p)));
    document.getElementById('pm-chain').textContent = p.chain_status || 'none';

    // Preuve de paiement : seulement pour un paiement réellement parti
    const proofRow = document.getElementById('pm-proof-row');
    document.getElementById('pm-copy-status').textContent = '';
    if (p.decision === 'allowed') {
      document.getElementById('pm-proof').textContent = proofText(p);
      proofRow.style.display = 'block';
    } else {
      proofRow.style.display = 'none';
    }

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
      loadOverview();
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
      loadOverview();
    } catch (e) {
      alert(e.message);
    }
  };

  document.getElementById('pm-btn-copy-proof').onclick = async () => {
    const status = document.getElementById('pm-copy-status');
    try {
      await navigator.clipboard.writeText(document.getElementById('pm-proof').textContent);
      status.textContent = ' Copié.';
    } catch (e) {
      status.textContent = ' Copie impossible : sélectionnez le texte à la main.';
    }
  };

  // ------------------------------------------------------------------ Langage simple : qui, pourquoi, preuve
  function whoIsPaid(p) {
    const short = p.recipient.slice(0, 8) + '…' + p.recipient.slice(-4);
    return p.supplier_name ? p.supplier_name : 'Destinataire inconnu (' + short + ')';
  }

  // La raison la plus grave en premier : c'est elle qui explique le résultat.
  function mainReason(p) {
    const rank = { BLOCK: 3, CONFIRM: 2, INFO: 1, ALLOW: 0 };
    const sorted = (p.reasons || []).slice().sort((a, b) => (rank[b.action] || 0) - (rank[a.action] || 0));
    if (p.review_action === 'approved') return 'Accepté par une personne de votre équipe.';
    if (p.review_action === 'rejected') return 'Refusé par une personne de votre équipe.';
    return sorted.length ? (sorted[0].title || sorted[0].code) : '';
  }

  function plainResult(p) {
    if (p.decision === 'allowed') {
      return p.review_action === 'approved' ? 'Payé, après accord d\'une personne de votre équipe.' : 'Payé automatiquement : tout était en règle.';
    }
    if (p.decision === 'pending_review') return 'Rien n\'est parti. Ce paiement attend votre accord.';
    return p.review_action === 'rejected' ? 'Refusé par votre équipe : rien n\'est parti.' : 'Bloqué : rien n\'est parti.';
  }

  function proofText(p) {
    const lines = [
      'PREUVE DE PAIEMENT',
      'Entreprise : ' + ((state.org && state.org.name) || ''),
      'Payé à : ' + whoIsPaid(p),
      'Adresse du destinataire : ' + p.recipient,
      'Montant : ' + formatWei(p.amount_gwei),
      'Facture : ' + (p.memo || 'non précisée'),
      'Date : ' + formatTimestamp(p.reviewed_at || p.created_at),
      'Paiement n° : ' + p.id
    ];
    (p.documents || []).slice(0, 3).forEach(d => {
      lines.push('Empreinte de la facture : ' + (d.file_sha256 || d.sha256));
    });
    if (p.tx_hash) {
      lines.push('Transaction sur Avalanche, consultable par tous : ' + p.tx_hash);
    } else {
      lines.push('Coffre de démonstration : pas de transaction publique.');
    }
    (p.proof || []).forEach(t => {
      const what = { 'payment.request': 'Demande inscrite', 'payment.approve': 'Accord inscrit', 'payment.reject': 'Refus inscrit' }[t.action] || t.action;
      lines.push(what + ' au journal infalsifiable le ' + formatTimestamp(t.created_at) + ' : ' + t.entry_hash);
    });
    return lines.join('\n');
  }

  // ------------------------------------------------------------------ Accueil : ce qui attend une décision
  async function decidePayment(id, action) {
    try {
      await api('/api/app/payments/' + action, { method: 'POST', body: JSON.stringify({ id: id }) });
    } catch (e) {
      alert(e.message);
    }
    loadOverview();
  }

  function renderTodo(pending) {
    const box = document.getElementById('todo-list');
    const title = document.getElementById('todo-title');
    box.textContent = '';
    if (pending.length === 0) {
      title.textContent = 'À faire';
      box.textContent = 'Rien à faire : aucun paiement n\'attend votre accord.';
      return;
    }
    title.textContent = 'À faire : ' + pending.length + (pending.length > 1 ? ' paiements attendent' : ' paiement attend') + ' votre accord';
    const canDecide = hasRole('approver') && !(state.org && state.org.is_suspended);
    pending.forEach(p => {
      const item = document.createElement('div');
      item.className = 'todo-item';

      const text = document.createElement('div');
      text.className = 'todo-text';
      const head = document.createElement('div');
      head.textContent = formatWei(p.amount_gwei) + ' pour ' + whoIsPaid(p) + (p.memo ? ' — ' + p.memo : '');
      const why = document.createElement('div');
      why.className = 'todo-why';
      why.textContent = 'Pourquoi on vous demande : ' + mainReason(p);
      text.appendChild(head);
      text.appendChild(why);
      item.appendChild(text);

      const actions = document.createElement('div');
      actions.className = 'todo-actions';
      const more = document.createElement('button');
      more.className = 'btn btn-secondary';
      more.textContent = 'Voir le détail';
      more.onclick = () => openPaymentModal(p);
      actions.appendChild(more);
      if (canDecide) {
        const no = document.createElement('button');
        no.className = 'btn btn-danger';
        no.textContent = 'Refuser';
        no.onclick = () => decidePayment(p.id, 'reject');
        const yes = document.createElement('button');
        yes.className = 'btn btn-success';
        yes.textContent = 'Accepter';
        yes.onclick = () => decidePayment(p.id, 'approve');
        actions.appendChild(no);
        actions.appendChild(yes);
      }
      item.appendChild(actions);
      box.appendChild(item);
    });
  }

  // ------------------------------------------------------------------ « Cette facture a-t-elle déjà été payée ? »
  function showLookup(matches, label) {
    const out = document.getElementById('lookup-result');
    out.textContent = '';
    const paid = matches.filter(p => p.decision === 'allowed');
    const head = document.createElement('div');
    head.className = 'reason-title';
    if (paid.length > 0) {
      head.style.color = 'var(--status-green)';
      head.textContent = 'Oui, ' + label + ' a déjà été payée.';
    } else if (matches.length > 0) {
      head.style.color = 'var(--status-amber)';
      head.textContent = 'Non, ' + label + ' n\'a pas été payée, mais une demande existe.';
    } else {
      head.style.color = 'var(--ink-muted)';
      head.textContent = 'Non : aucune trace de paiement pour ' + label + '.';
    }
    out.appendChild(head);
    matches.slice(0, 5).forEach(p => {
      const line = document.createElement('div');
      line.className = 'lookup-hit';
      line.appendChild(createDecisionBadge(p.decision));
      line.appendChild(document.createTextNode(' ' + formatTimestamp(p.reviewed_at || p.created_at) + ' — ' + formatWei(p.amount_gwei)
        + ' pour ' + whoIsPaid(p) + (p.memo ? ' — ' + p.memo : '') + ' '));
      const btn = document.createElement('button');
      btn.className = 'btn btn-secondary';
      btn.style.padding = '3px 8px';
      btn.textContent = p.decision === 'allowed' ? 'Voir la preuve' : 'Détails';
      btn.onclick = () => openPaymentModal(p);
      line.appendChild(btn);
      out.appendChild(line);
    });
  }

  async function allPayments() {
    state.payments = await api('/api/app/payments?limit=200') || [];
    return state.payments;
  }

  document.getElementById('btn-lookup').onclick = async () => {
    const wanted = document.getElementById('lookup-number').value.trim().toLowerCase();
    if (!wanted) return;
    const list = await allPayments();
    showLookup(list.filter(p => (p.memo || '').toLowerCase().includes(wanted)), 'la facture « ' + wanted.toUpperCase() + ' »');
  };
  document.getElementById('lookup-number').addEventListener('keydown', ev => {
    if (ev.key === 'Enter') document.getElementById('btn-lookup').click();
  });
  document.getElementById('lookup-file').addEventListener('change', async ev => {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    if (!window.crypto || !window.crypto.subtle) {
      document.getElementById('lookup-result').textContent = 'Recherche par fichier indisponible dans ce navigateur (connexion HTTPS requise).';
      return;
    }
    const digest = await window.crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    const hex = Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('');
    const list = await allPayments();
    showLookup(list.filter(p => (p.documents || []).some(d => d.file_sha256 === hex || d.sha256 === hex)), 'cette facture');
  });

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

  // ------------------------------------------------------------------ Factures reçues par mail
  const VERDICTS = {
    ok: ['badge-status-allowed', 'Bon à payer'],
    review: ['badge-status-pending', 'À vérifier'],
    refused: ['badge-status-blocked', 'Refusée']
  };

  function formatEuros(cents) {
    if (cents === null || cents === undefined) return '—';
    return (cents / 100).toLocaleString('fr-FR', { style: 'currency', currency: 'EUR' });
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function checkWho(c) {
    return c.payee_name || 'Fournisseur inconnu';
  }

  function checkWhy(c) {
    if (c.review_action === 'approved') return 'Accepté par une personne de votre équipe.';
    if (c.review_action === 'rejected') return 'Refusé par une personne de votre équipe.';
    return c.reasons.length ? c.reasons[0].title : '';
  }

  function emptyRow(tbody, cols, text) {
    const td = el('td', 'table-empty-cell', text);
    td.colSpan = cols;
    const tr = el('tr');
    tr.appendChild(td);
    tbody.appendChild(tr);
  }

  async function inboxPost(path, body) {
    try {
      await api(path, { method: 'POST', body: JSON.stringify(body) });
      return true;
    } catch (e) {
      alert(e.message);
      return false;
    } finally {
      loadInbox();
    }
  }

  async function loadInbox() {
    let box;
    try {
      box = await api('/api/app/inbox');
    } catch (e) {
      console.error('Erreur factures reçues :', e);
      return;
    }
    if (!box) return;
    state.inbox = box;
    const editable = !(state.org && state.org.is_suspended);

    document.getElementById('inbox-address').textContent = box.address;
    const ignored = Object.values(box.ignored_7d).reduce((a, b) => a + b, 0);
    document.getElementById('inbox-ignored').textContent = ignored
      ? ignored + (ignored > 1 ? ' mails écartés sans être lus' : ' mail écarté sans être lu') + ' ces 7 derniers jours (expéditeur non autorisé ou adresse imitée).'
      : '';

    // À faire
    const pending = box.checks.filter(c => c.verdict === 'review');
    const todo = document.getElementById('inbox-todo-list');
    todo.textContent = '';
    document.getElementById('inbox-todo-title').textContent = pending.length
      ? 'À faire : ' + pending.length + (pending.length > 1 ? ' factures attendent' : ' facture attend') + ' votre décision'
      : 'À faire';
    if (!pending.length) todo.textContent = 'Rien à faire : aucune facture n\'attend votre décision.';
    pending.forEach(c => {
      const item = el('div', 'todo-item');
      const text = el('div', 'todo-text');
      text.appendChild(el('div', '', formatEuros(c.amount_cents) + ' — ' + checkWho(c) + (c.invoice_number ? ' — facture ' + c.invoice_number : '')));
      c.reasons.forEach(r => {
        text.appendChild(el('div', 'todo-why', r.title + (r.detail ? ' ' + r.detail : '')));
      });
      item.appendChild(text);
      if (hasRole('approver') && editable) {
        const actions = el('div', 'todo-actions');
        const no = el('button', 'btn btn-danger', 'Refuser');
        no.onclick = () => inboxPost('/api/app/inbox/checks/reject', { id: c.id });
        const yes = el('button', 'btn btn-success', 'Bonne à payer');
        yes.onclick = () => inboxPost('/api/app/inbox/checks/approve', { id: c.id });
        actions.appendChild(no);
        actions.appendChild(yes);
        item.appendChild(actions);
      }
      todo.appendChild(item);
    });

    // Virements en euros
    const summary = document.getElementById('transfer-summary');
    const canPay = hasRole('approver') && editable;
    const btnBatch = document.getElementById('btn-create-batch');
    btnBatch.style.display = canPay && box.payable.count ? '' : 'none';
    summary.textContent = box.payable.count
      ? box.payable.count + (box.payable.count > 1 ? ' factures bonnes à payer attendent' : ' facture bonne à payer attend')
        + ' un virement : ' + formatEuros(box.payable.total_cents) + ' au total.'
      : 'Aucune facture bonne à payer n\'attend de virement.';
    if (box.payable.count && !box.bank) summary.textContent += ' Renseignez d\'abord le compte bancaire de votre entreprise, plus bas.';
    if (box.payable.skipped) {
      summary.textContent += ' ' + box.payable.skipped + (box.payable.skipped > 1 ? ' factures acceptées ne peuvent' : ' facture acceptée ne peut')
        + ' pas être payée automatiquement : son fournisseur n\'est pas dans votre liste.';
    }
    const batches = document.getElementById('transfer-batches');
    batches.textContent = '';
    box.batches.forEach(b => {
      const row = el('div', 'inbox-list-item');
      const text = el('div', 'todo-text');
      text.appendChild(el('div', '', 'Fichier du ' + formatTimestamp(b.created_at) + ' — ' + b.tx_count
        + (b.tx_count > 1 ? ' virements' : ' virement') + ', ' + formatEuros(b.total_cents)));
      const proof = el('div', 'todo-why break-all');
      if (b.seal_status === 'anchored') {
        proof.appendChild(document.createTextNode('Preuve scellée sur Avalanche : '));
        if (b.seal_url) {
          const link = el('a', '', b.seal_tx);
          link.href = b.seal_url;
          link.target = '_blank';
          link.rel = 'noopener';
          proof.appendChild(link);
        } else {
          proof.appendChild(document.createTextNode(b.seal_tx));
        }
      } else if (b.seal_status === 'simulated') {
        proof.textContent = 'Preuve inscrite sur le coffre de démonstration (hors ligne, pas de transaction publique).';
      } else {
        proof.textContent = 'Preuve pas encore scellée sur Avalanche.';
      }
      text.appendChild(proof);
      text.appendChild(el('div', 'todo-why break-all', 'Empreinte du fichier : ' + b.file_sha256));
      row.appendChild(text);
      if (canPay) {
        const actions = el('div', 'todo-actions');
        if (b.seal_status !== 'anchored' && b.seal_status !== 'simulated') {
          const sealBtn = el('button', 'btn btn-secondary', 'Sceller sur Avalanche');
          sealBtn.onclick = async () => {
            sealBtn.disabled = true;
            try {
              const res = await api('/api/app/transfers/seal', { method: 'POST', body: JSON.stringify({ id: b.id }) });
              if (res && res.seal_error) alert(res.seal_error);
            } catch (e) {
              alert(e.message);
            }
            loadInbox();
          };
          actions.appendChild(sealBtn);
        }
        const dl = el('a', 'btn btn-secondary', 'Télécharger le fichier');
        dl.href = '/api/app/transfers/' + encodeURIComponent(b.id) + '.xml';
        actions.appendChild(dl);
        row.appendChild(actions);
      }
      batches.appendChild(row);
    });

    const holder = document.getElementById('bank-holder');
    const bankIban = document.getElementById('bank-iban');
    if (document.activeElement !== holder && document.activeElement !== bankIban && !state.bankDirty) {
      holder.value = box.bank ? box.bank.holder : ((state.org && state.org.name) || '');
      bankIban.value = box.bank ? box.bank.iban.replace(/(.{4})/g, '$1 ').trim() : '';
    }
    holder.disabled = bankIban.disabled = !(hasRole('admin') && editable);
    document.getElementById('btn-save-bank').style.display = hasRole('admin') && editable ? '' : 'none';

    // Factures contrôlées
    const tbody = document.getElementById('inbox-checks-tbody');
    tbody.textContent = '';
    if (!box.checks.length) emptyRow(tbody, 7, 'Aucune facture reçue pour le moment. Transférez-en une à l\'adresse ci-dessus.');
    state.openChecks = state.openChecks || {};
    box.checks.forEach(c => {
      const tr = el('tr');
      tr.appendChild(el('td', '', formatTimestamp(c.created_at)));
      tr.appendChild(el('td', '', checkWho(c)));
      tr.appendChild(el('td', 'mono', c.currency && c.currency !== 'EUR' && c.amount_cents !== null
        ? (c.amount_cents / 100).toLocaleString('fr-FR') + ' ' + c.currency : formatEuros(c.amount_cents)));
      tr.appendChild(el('td', '', c.invoice_number || '—'));
      const tdVerdict = el('td');
      const v = VERDICTS[c.verdict] || ['badge-viewer', c.verdict];
      tdVerdict.appendChild(el('span', 'badge ' + v[0], v[1]));
      tr.appendChild(tdVerdict);
      tr.appendChild(el('td', '', checkWhy(c) + (c.batch_id ? ' Virement préparé.' : '')));

      const detail = el('tr');
      const cell = el('td', 'check-detail-cell');
      cell.colSpan = 7;
      c.reasons.forEach(r => {
        const boxEl = el('div', 'reason-box ' + ({ refused: 'reason-box-block', review: 'reason-box-confirm', ok: 'reason-box-ok' }[r.level] || ''));
        boxEl.appendChild(el('div', 'reason-title', r.title));
        if (r.detail) boxEl.appendChild(el('div', 'reason-detail', r.detail));
        cell.appendChild(boxEl);
      });
      const proof = el('div', 'check-proof');
      const lines = [];
      if (c.iban_tail) lines.push('Compte bancaire lu sur la facture : finissant par ' + c.iban_tail);
      if (c.fmt) lines.push(/ubl|cii|factur/i.test(c.fmt) ? 'Facture électronique (format structuré ' + c.fmt.replace('mail+', '').toUpperCase() + ').' : 'Facture non électronique (texte ou PDF simple) : lue, mais pas au format prévu par la réforme de la facture électronique.');
      const viaPlatform = (box.platform || {})[c.id];
      if (viaPlatform) lines.push('Reçue par la plateforme, émise par ' + viaPlatform.seller_name + ' (SIREN ' + viaPlatform.seller_siren + ').');
      if (c.batch_id) lines.push('Virement préparé dans le fichier ' + c.batch_id + '.');
      if (c.file_sha256) lines.push('Empreinte de la facture (seule trace conservée) : ' + c.file_sha256);
      (c.proof || []).forEach(t => {
        const what = { 'invoice.check': 'Contrôle inscrit', 'invoice.approve': 'Accord inscrit', 'invoice.reject': 'Refus inscrit' }[t.action] || t.action;
        lines.push(what + ' au journal infalsifiable le ' + formatTimestamp(t.created_at) + ' : ' + t.entry_hash);
      });
      lines.push('Référence : ' + c.id);
      lines.forEach(line => proof.appendChild(el('div', 'break-all', line)));
      if (viaPlatform) {
        const dl = el('a', 'btn btn-secondary', 'Télécharger la facture');
        dl.href = '/api/app/einvoices/received/' + encodeURIComponent(c.id) + '.pdf';
        proof.appendChild(dl);
      }
      cell.appendChild(proof);
      detail.appendChild(cell);
      detail.style.display = state.openChecks[c.id] ? '' : 'none';

      const tdBtn = el('td');
      const btn = el('button', 'btn btn-secondary', 'Détail');
      btn.onclick = () => {
        state.openChecks[c.id] = !state.openChecks[c.id];
        detail.style.display = state.openChecks[c.id] ? '' : 'none';
      };
      tdBtn.appendChild(btn);
      tr.appendChild(tdBtn);
      tbody.appendChild(tr);
      tbody.appendChild(detail);
    });

    // Personnes autorisées
    const senders = document.getElementById('inbox-senders');
    senders.textContent = '';
    if (!box.senders.length) {
      senders.textContent = 'Personne pour le moment : tant que cette liste est vide, aucun mail n\'est lu.';
    }
    box.senders.forEach(s => {
      const row = el('div', 'inbox-list-item');
      row.appendChild(el('span', 'mono break-all', s.email));
      if (hasRole('admin') && editable) {
        const del = el('button', 'btn btn-danger', 'Retirer');
        del.onclick = () => {
          if (confirm('Retirer ' + s.email + ' ? Ses mails ne seront plus lus.')) inboxPost('/api/app/inbox/senders/remove', { id: s.id });
        };
        row.appendChild(del);
      }
      senders.appendChild(row);
    });

    // Fournisseurs et IBAN
    const payees = document.getElementById('inbox-payees-tbody');
    payees.textContent = '';
    if (!box.payees.length) emptyRow(payees, 4, 'Aucun fournisseur enregistré : toutes les factures vous seront soumises.');
    box.payees.forEach(p => {
      const tr = el('tr');
      tr.appendChild(el('td', '', p.name));
      tr.appendChild(el('td', 'mono break-all', p.iban.replace(/(.{4})/g, '$1 ').trim()));
      const tdState = el('td');
      const hours = Math.ceil(p.remaining_seconds / 3600);
      tdState.appendChild(el('span', 'badge ' + (p.is_active ? 'badge-status-allowed' : 'badge-status-pending'),
        p.is_active ? 'Habituel' : 'Délai de sécurité : ' + hours + ' h'));
      tr.appendChild(tdState);
      const tdDel = el('td');
      if (hasRole('admin') && editable) {
        const del = el('button', 'btn btn-danger', 'Retirer');
        del.onclick = () => {
          if (confirm('Retirer le fournisseur "' + p.name + '" ?')) inboxPost('/api/app/payees/remove', { id: p.id });
        };
        tdDel.appendChild(del);
      }
      tr.appendChild(tdDel);
      payees.appendChild(tr);
    });

    const threshold = document.getElementById('inbox-threshold');
    if (document.activeElement !== threshold) {
      threshold.value = (box.review_threshold_cents / 100).toLocaleString('fr-FR', { useGrouping: false, minimumFractionDigits: box.review_threshold_cents % 100 ? 2 : 0, maximumFractionDigits: 2 });
    }
  }

  document.getElementById('btn-refresh-inbox').onclick = loadInbox;

  document.getElementById('btn-create-batch').onclick = async () => {
    const btn = document.getElementById('btn-create-batch');
    btn.disabled = true;
    try {
      const batch = await api('/api/app/transfers', { method: 'POST', body: '{}' });
      if (batch && batch.seal_error) alert('Fichier prêt. ' + batch.seal_error);
    } catch (e) {
      alert(e.message);
    }
    btn.disabled = false;
    loadInbox();
  };

  // ---- Factures émises (plateforme de facturation)

  const EINV_STATUS = {
    undelivered: ['badge-viewer', 'Non remise'],
    review: ['badge-status-pending', 'En vérification'],
    ok: ['badge-status-allowed', 'Acceptée'],
    refused: ['badge-status-blocked', 'Refusée'],
    paid: ['badge-status-allowed', 'Virement préparé']
  };

  function einvCents(text) {
    const m = /^(\d{1,7})(?:[.,](\d{1,2}))?$/.exec(String(text).trim());
    return m ? parseInt(m[1], 10) * 100 + parseInt((m[2] || '0').padEnd(2, '0'), 10) : null;
  }

  function einvUpdateTotal() {
    let ht = 0;
    let complete = true;
    document.querySelectorAll('#einv-lines .einv-line').forEach(row => {
      const qty = parseInt(row.querySelector('.einv-qty').value, 10);
      const cents = einvCents(row.querySelector('.einv-price').value);
      if (qty > 0 && cents) ht += qty * cents; else complete = false;
    });
    const rate = (state.einvoices && state.einvoices.vat_percent) || 20;
    const tax = Math.floor((ht * rate + 50) / 100);
    document.getElementById('einv-total').textContent = ht && complete
      ? 'Hors taxes ' + formatEuros(ht) + ' — TVA ' + rate + ' % ' + formatEuros(tax) + ' — à payer ' + formatEuros(ht + tax)
      : '';
  }

  function einvAddLine() {
    const holder = document.getElementById('einv-lines');
    const n = holder.children.length + 1;
    const row = el('div', 'form-row einv-line');
    const field = (cls, label, type, extra) => {
      const group = el('div', 'form-group' + (extra || ''));
      const input = el('input', 'form-input ' + cls);
      input.type = type;
      input.id = cls.split(' ')[0] + '-' + n + '-' + Date.now();
      input.required = true;
      const lab = el('label', 'form-label', label);
      lab.htmlFor = input.id;
      input.oninput = einvUpdateTotal;
      group.appendChild(lab);
      group.appendChild(input);
      row.appendChild(group);
      return input;
    };
    field('einv-label', 'Désignation', 'text', ' supplier-name-field').maxLength = 120;
    const qty = field('einv-qty', 'Quantité', 'number');
    qty.min = 1; qty.max = 9999; qty.step = 1; qty.value = 1;
    const price = field('einv-price mono', 'Prix unitaire HT (€)', 'text');
    price.maxLength = 10;
    price.inputMode = 'decimal';
    price.placeholder = '150,00';
    if (n > 1) {
      const del = el('button', 'btn btn-secondary', 'Retirer');
      del.type = 'button';
      del.onclick = () => { row.remove(); einvUpdateTotal(); };
      row.appendChild(del);
    }
    holder.appendChild(row);
  }

  async function loadEinvoices() {
    let data;
    try {
      data = await api('/api/app/einvoices');
    } catch (e) {
      console.error('Erreur factures émises :', e);
      return;
    }
    if (!data) return;
    state.einvoices = data;
    const editable = !(state.org && state.org.is_suspended);
    const siren = document.getElementById('einv-siren');
    const address = document.getElementById('einv-address');
    if (document.activeElement !== siren && document.activeElement !== address) {
      siren.value = data.profile ? data.profile.siren : '';
      address.value = data.profile ? data.profile.address : '';
    }
    siren.disabled = address.disabled = !(hasRole('admin') && editable);
    document.getElementById('btn-save-profile').style.display = hasRole('admin') && editable ? '' : 'none';
    const ready = data.profile && data.bank;
    document.getElementById('einv-bank-help').textContent = data.bank
      ? 'Vos clients vous paieront sur le compte finissant par ' + data.bank.iban.slice(-4) + ' (réglé dans « 2. Factures reçues »).'
      : 'Avant d\'émettre une facture, renseignez le compte bancaire de votre entreprise dans « 2. Factures reçues ».';
    document.getElementById('einv-create-card').style.display = ready && hasRole('approver') && editable ? '' : 'none';
    if (!document.getElementById('einv-lines').children.length) einvAddLine();

    const tbody = document.getElementById('einv-tbody');
    tbody.textContent = '';
    if (!data.issued.length) emptyRow(tbody, 6, 'Aucune facture émise pour le moment.');
    data.issued.forEach(inv => {
      const tr = el('tr');
      tr.appendChild(el('td', '', formatTimestamp(inv.created_at)));
      tr.appendChild(el('td', 'mono', inv.number));
      tr.appendChild(el('td', '', inv.buyer_name));
      tr.appendChild(el('td', 'mono', formatEuros(inv.total_cents)));
      const tdStatus = el('td');
      const s = EINV_STATUS[inv.status] || ['badge-viewer', inv.status];
      tdStatus.appendChild(el('span', 'badge ' + s[0], s[1]));
      tdStatus.appendChild(el('div', 'todo-why', inv.status_text));
      tr.appendChild(tdStatus);
      const tdDl = el('td');
      const dl = el('a', 'btn btn-secondary', 'Télécharger');
      dl.href = '/api/app/einvoices/' + encodeURIComponent(inv.id) + '.pdf';
      tdDl.appendChild(dl);
      tr.appendChild(tdDl);
      tbody.appendChild(tr);
    });
  }

  document.getElementById('btn-refresh-einv').onclick = loadEinvoices;
  document.getElementById('btn-einv-add-line').onclick = einvAddLine;

  document.getElementById('einv-profile-form').onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById('einv-profile-msg');
    msg.textContent = '';
    try {
      await api('/api/app/einvoices/profile', { method: 'POST', body: JSON.stringify({
        siren: document.getElementById('einv-siren').value.trim(),
        address: document.getElementById('einv-address').value.trim()
      }) });
      msg.textContent = 'Enregistré.';
    } catch (err) {
      msg.textContent = err.message;
    }
    loadEinvoices();
  };

  document.getElementById('einv-buyer-siren').onchange = async (e) => {
    const status = document.getElementById('einv-buyer-status');
    const name = document.getElementById('einv-buyer-name');
    const siren = e.target.value.trim();
    if (!siren) return;
    try {
      const res = await api('/api/app/einvoices/lookup', { method: 'POST', body: JSON.stringify({ siren }) });
      if (res.found) {
        name.value = res.name;
        name.disabled = true;
        status.textContent = res.name + ' est sur la plateforme : la facture lui sera remise directement.';
      } else {
        name.disabled = false;
        status.textContent = 'Ce client n\'est pas sur la plateforme : indiquez son nom. La facture sera créée, à lui transmettre vous-même.';
      }
    } catch (err) {
      name.disabled = false;
      status.textContent = err.message;
    }
  };

  document.getElementById('einv-form').onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById('einv-msg');
    const btn = document.getElementById('btn-einv-send');
    const lines = [...document.querySelectorAll('#einv-lines .einv-line')].map(row => ({
      label: row.querySelector('.einv-label').value.trim(),
      quantity: parseInt(row.querySelector('.einv-qty').value, 10),
      unit_price: row.querySelector('.einv-price').value.trim()
    }));
    msg.textContent = '';
    btn.disabled = true;
    try {
      const inv = await api('/api/app/einvoices', { method: 'POST', body: JSON.stringify({
        buyer_siren: document.getElementById('einv-buyer-siren').value.trim(),
        buyer_name: document.getElementById('einv-buyer-name').value.trim(),
        lines
      }) });
      msg.textContent = 'Facture ' + inv.number + ' créée. ' + inv.status_text;
      document.getElementById('einv-lines').textContent = '';
      einvAddLine();
      einvUpdateTotal();
    } catch (err) {
      msg.textContent = err.message;
    }
    btn.disabled = false;
    loadEinvoices();
  };

  document.getElementById('audit-file').onchange = async (e) => {
    const input = e.target;
    const msg = document.getElementById('audit-msg');
    const summary = document.getElementById('audit-summary');
    const list = document.getElementById('audit-lines');
    const file = input.files && input.files[0];
    summary.textContent = '';
    list.textContent = '';
    if (!file) return;
    if (file.size > 250000) {
      msg.textContent = 'Fichier trop volumineux (250 Ko au plus).';
      return;
    }
    msg.textContent = 'Contrôle en cours...';
    try {
      const out = await api('/api/app/transfers/audit', { method: 'POST', body: JSON.stringify({ content: await file.text() }) });
      msg.textContent = '';
      const n = out.lines.length;
      const head = el('div', 'reason-box ' + { refused: 'reason-box-block', review: 'reason-box-confirm', ok: 'reason-box-ok' }[out.verdict]);
      head.appendChild(el('div', 'reason-title', {
        refused: 'N\'envoyez pas ce fichier à votre banque.',
        review: 'À vérifier avant d\'envoyer ce fichier à votre banque.',
        ok: 'Rien d\'anormal : tous les comptes sont ceux de votre liste.'
      }[out.verdict]));
      head.appendChild(el('div', 'reason-detail', n + (n > 1 ? ' virements, ' : ' virement, ') + formatEuros(out.total_cents)
        + ' au total : ' + out.counts.ok + ' conforme' + (out.counts.ok > 1 ? 's' : '') + ', ' + out.counts.review
        + ' à vérifier, ' + out.counts.refused + ' à ne pas payer.'));
      summary.appendChild(head);
      out.lines.forEach(line => {
        const row = el('div', 'inbox-list-item');
        const text = el('div', 'todo-text');
        text.appendChild(el('div', '', line.position + '. ' + (line.name || 'Bénéficiaire sans nom') + ' — '
          + formatEuros(line.amount_cents) + (line.iban_tail ? ' — compte finissant par ' + line.iban_tail : '')));
        text.appendChild(el('div', 'todo-why', line.why + (line.level === 'ok' && !line.invoice_checked
          ? ' Aucune facture contrôlée ici ne correspond à ce montant.' : '')));
        row.appendChild(text);
        const v = VERDICTS[line.level] || ['badge-viewer', line.level];
        row.appendChild(el('span', 'badge ' + v[0], { ok: 'Conforme', review: 'À vérifier', refused: 'Ne pas payer' }[line.level]));
        list.appendChild(row);
      });
    } catch (err) {
      msg.textContent = err.message;
    }
    input.value = '';
  };

  ['bank-holder', 'bank-iban'].forEach(id => {
    document.getElementById(id).oninput = () => { state.bankDirty = true; };
  });
  document.getElementById('inbox-bank-form').onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById('inbox-bank-msg');
    msg.textContent = '';
    state.bankDirty = false;
    const ok = await inboxPost('/api/app/inbox/bank', {
      holder: document.getElementById('bank-holder').value.trim(),
      iban: document.getElementById('bank-iban').value.trim()
    });
    msg.textContent = ok ? 'Enregistré.' : '';
  };

  document.getElementById('btn-copy-inbox').onclick = async () => {
    const status = document.getElementById('inbox-copy-status');
    try {
      await navigator.clipboard.writeText(document.getElementById('inbox-address').textContent);
      status.textContent = 'Adresse copiée.';
    } catch (e) {
      status.textContent = 'Copie impossible : sélectionnez l\'adresse à la main.';
    }
  };

  document.getElementById('add-sender-form').onsubmit = async (e) => {
    e.preventDefault();
    const input = document.getElementById('sender-email');
    if (await inboxPost('/api/app/inbox/senders', { email: input.value.trim() })) input.value = '';
  };

  document.getElementById('add-payee-form').onsubmit = async (e) => {
    e.preventDefault();
    const name = document.getElementById('payee-name');
    const iban = document.getElementById('payee-iban');
    if (await inboxPost('/api/app/payees', { name: name.value.trim(), iban: iban.value.trim() })) {
      name.value = '';
      iban.value = '';
    }
  };

  document.getElementById('inbox-threshold-form').onsubmit = async (e) => {
    e.preventDefault();
    const msg = document.getElementById('inbox-threshold-msg');
    const m = document.getElementById('inbox-threshold').value.trim().replace(/\s/g, '').replace(',', '.').match(/^(\d{1,9})(?:\.(\d{1,2}))?$/);
    if (!m) {
      msg.textContent = 'Montant invalide : un nombre d\'euros, ex. 1000 ou 1000,50.';
      return;
    }
    document.getElementById('inbox-threshold').blur();
    const ok = await inboxPost('/api/app/inbox/threshold', { cents: Number(m[1]) * 100 + Number((m[2] || '').padEnd(2, '0')) });
    msg.textContent = ok ? 'Enregistré.' : '';
  };

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
    return new Date(ts * 1000).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
  }

  function createDecisionBadge(dec) {
    const span = document.createElement('span');
    if (dec === 'allowed') {
      span.className = 'badge badge-status-allowed';
      span.textContent = 'Payé';
    } else if (dec === 'blocked') {
      span.className = 'badge badge-status-blocked';
      span.textContent = 'Bloqué';
    } else if (dec === 'pending_review') {
      span.className = 'badge badge-status-pending';
      span.textContent = 'À valider';
    } else {
      span.className = 'badge badge-viewer';
      span.textContent = dec || 'Inconnu';
    }
    return span;
  }

  // Lancement
  window.addEventListener('DOMContentLoaded', init);
})();
