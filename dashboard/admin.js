/* admin.js — Logique de l'espace d'administration VaultGuard v3 (Étape 5)
 * Strictement conforme aux règles AGENTS.md :
 * - Aucun innerHTML pour l'affichage de données (textContent uniquement)
 * - Aucune dépendance externe ni CDN
 * - Jeton CSRF systématique sur tous les POST
 */
(function() {
  'use strict';

  const state = {
    csrf: '',
    user: null,
    currentSection: 'stats'
  };

  async function api(path, options = {}) {
    const opts = { ...options };
    opts.headers = {
      'Content-Type': 'application/json',
      ...(opts.headers || {})
    };
    if (state.csrf) {
      opts.headers['X-CSRF-Token'] = state.csrf;
    }
    const resp = await fetch(path, opts);
    if (!resp.ok) {
      let errText = 'Erreur serveur (' + resp.status + ')';
      try {
        const errJson = await resp.json();
        if (errJson && errJson.error) errText = errJson.error;
      } catch (e) {
        // Ignorer
      }
      throw new Error(errText);
    }
    return resp.json();
  }

  function formatTimestamp(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return d.toISOString().replace('T', ' ').slice(0, 19);
  }

  // ------------------------------------------------------------------ Initialisation
  async function init() {
    try {
      // 1. Session et CSRF
      const me = await api('/api/auth/me');
      if (!me || !me.authenticated || !me.user || !me.user.is_superadmin) {
        window.location.href = '/login';
        return;
      }
      state.user = me.user;
      state.csrf = me.csrf;

      const emailEl = document.getElementById('user-email-display');
      if (emailEl) emailEl.textContent = me.user.email;

      // 2. Gestion de la navigation
      setupNavigation();

      // 3. Bouton déconnexion
      const btnLogout = document.getElementById('btn-logout');
      if (btnLogout) {
        btnLogout.onclick = async () => {
          try {
            await api('/api/auth/logout', { method: 'POST', body: '{}' });
          } catch (e) {
            // Ignorer
          }
          window.location.href = '/login';
        };
      }

      // 4. Chargement initial
      loadSection('stats');
    } catch (e) {
      console.error('Erreur init admin :', e);
      window.location.href = '/login';
    }
  }

  function setupNavigation() {
    const links = document.querySelectorAll('.nav-link[data-section]');
    links.forEach(link => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const sec = link.getAttribute('data-section');
        if (sec) {
          links.forEach(l => l.classList.remove('active'));
          link.classList.add('active');
          loadSection(sec);
        }
      });
    });
  }

  function loadSection(sec) {
    state.currentSection = sec;
    const sections = ['stats', 'orgs', 'users', 'security', 'audit', 'health'];
    sections.forEach(s => {
      const el = document.getElementById('sec-' + s);
      if (el) el.style.display = (s === sec) ? 'block' : 'none';
    });

    if (sec === 'stats') loadStats();
    else if (sec === 'orgs') loadOrgs();
    else if (sec === 'users') loadUsers();
    else if (sec === 'security') loadSecurity();
    else if (sec === 'audit') loadAudit();
    else if (sec === 'health') loadHealth();
  }

  // ------------------------------------------------------------------ 1. Statistiques
  async function loadStats() {
    try {
      const data = await api('/api/admin/stats');
      if (!data) return;

      document.getElementById('stat-users-total').textContent = data.users.total;
      document.getElementById('stat-users-sub').textContent =
        data.users.active + ' actifs · ' + data.users.totp_enabled + ' avec 2FA · ' + data.users.superadmins + ' admin';

      document.getElementById('stat-orgs-total').textContent = data.orgs.total;
      document.getElementById('stat-orgs-sub').textContent =
        data.orgs.active + ' actives · ' + data.orgs.suspended + ' suspendues';

      document.getElementById('stat-keys-total').textContent = data.api_keys.total;
      document.getElementById('stat-keys-sub').textContent =
        data.api_keys.active + ' actives · ' + data.api_keys.quarantined + ' en quarantaine';

      document.getElementById('stat-payments-total').textContent = data.payments.total;
      document.getElementById('stat-payments-sub').textContent =
        data.payments.allowed + ' autorisés · ' + data.payments.blocked + ' bloqués · ' + data.payments.pending_review + ' en revue';

      document.getElementById('stat-audit-total').textContent = data.audit_entries_count;
    } catch (e) {
      console.error('Erreur chargement stats admin :', e);
    }
  }

  // ------------------------------------------------------------------ 2. Organisations
  async function loadOrgs() {
    const tbody = document.getElementById('orgs-tbody');
    try {
      const list = await api('/api/admin/orgs');
      tbody.textContent = '';
      if (!list || list.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 8;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucune organisation enregistrée.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }

      list.forEach(org => {
        const tr = document.createElement('tr');

        // Nom
        const tdName = document.createElement('td');
        tdName.style.fontWeight = '600';
        tdName.textContent = org.name;
        tr.appendChild(tdName);

        // ID / Slug
        const tdSlug = document.createElement('td');
        tdSlug.className = 'mono break-all';
        tdSlug.textContent = org.slug || org.id;
        tr.appendChild(tdSlug);

        // Réseau
        const tdNet = document.createElement('td');
        tdNet.textContent = org.network === 'mock' ? 'Simulation' : 'Avalanche';
        tr.appendChild(tdNet);

        // Adresse coffre
        const tdVault = document.createElement('td');
        tdVault.className = 'mono break-all';
        tdVault.textContent = org.vault_address || '—';
        tr.appendChild(tdVault);

        // Membres
        const tdMemb = document.createElement('td');
        tdMemb.textContent = org.members_count || 0;
        tr.appendChild(tdMemb);

        // Clés API
        const tdKeys = document.createElement('td');
        tdKeys.textContent = org.api_keys_count || 0;
        tr.appendChild(tdKeys);

        // Statut
        const tdStatus = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = org.is_suspended ? 'badge badge-danger' : 'badge badge-success';
        badge.textContent = org.is_suspended ? 'Suspendue' : 'Active';
        tdStatus.appendChild(badge);
        tr.appendChild(tdStatus);

        // Action
        const tdAction = document.createElement('td');
        const btn = document.createElement('button');
        btn.className = org.is_suspended ? 'btn btn-secondary' : 'btn btn-danger';
        btn.style.fontSize = '12px';
        btn.textContent = org.is_suspended ? 'Réactiver' : 'Suspendre';
        btn.onclick = async () => {
          const actionText = org.is_suspended ? 'réactiver' : 'suspendre';
          if (confirm('Voulez-vous vraiment ' + actionText + ' l’organisation ' + org.name + ' ?')) {
            try {
              const url = org.is_suspended ? '/api/admin/orgs/reactivate' : '/api/admin/orgs/suspend';
              await api(url, {
                method: 'POST',
                body: JSON.stringify({ org_id: org.id })
              });
              loadOrgs();
            } catch (err) {
              alert(err.message);
            }
          }
        };
        tdAction.appendChild(btn);
        tr.appendChild(tdAction);

        tbody.appendChild(tr);
      });
    } catch (e) {
      tbody.textContent = '';
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 8;
      td.className = 'alert-danger';
      td.textContent = 'Erreur lors du chargement des organisations : ' + e.message;
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
  }

  // ------------------------------------------------------------------ 3. Utilisateurs
  async function loadUsers() {
    const tbody = document.getElementById('users-tbody');
    try {
      const list = await api('/api/admin/users');
      tbody.textContent = '';
      if (!list || list.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 7;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucun utilisateur trouvé.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }

      list.forEach(u => {
        const tr = document.createElement('tr');

        // Email
        const tdEmail = document.createElement('td');
        tdEmail.className = 'mono break-all';
        tdEmail.textContent = u.email;
        if (u.is_superadmin) {
          const sBadge = document.createElement('span');
          sBadge.className = 'badge badge-admin';
          sBadge.style.marginLeft = '6px';
          sBadge.textContent = 'SUPER-ADMIN';
          tdEmail.appendChild(sBadge);
        }
        tr.appendChild(tdEmail);

        // Organisations
        const tdOrgs = document.createElement('td');
        if (u.orgs && u.orgs.length > 0) {
          tdOrgs.textContent = u.orgs.map(o => o.name + ' (' + o.role + ')').join(', ');
        } else {
          tdOrgs.textContent = '—';
        }
        tr.appendChild(tdOrgs);

        // 2FA
        const td2fa = document.createElement('td');
        const b2fa = document.createElement('span');
        b2fa.className = u.totp_enabled ? 'badge badge-success' : 'badge badge-viewer';
        b2fa.textContent = u.totp_enabled ? 'Activée' : 'Désactivée';
        td2fa.appendChild(b2fa);
        tr.appendChild(td2fa);

        // Sessions
        const tdSess = document.createElement('td');
        tdSess.textContent = u.sessions_count || 0;
        tr.appendChild(tdSess);

        // Statut
        const tdStatus = document.createElement('td');
        const bStatus = document.createElement('span');
        bStatus.className = u.is_active ? 'badge badge-success' : 'badge badge-danger';
        bStatus.textContent = u.is_active ? 'Actif' : 'Inactif';
        tdStatus.appendChild(bStatus);
        tr.appendChild(tdStatus);

        // Date
        const tdDate = document.createElement('td');
        tdDate.className = 'mono';
        tdDate.textContent = formatTimestamp(u.created_at);
        tr.appendChild(tdDate);

        // Actions
        const tdActions = document.createElement('td');
        const btnGroup = document.createElement('div');
        btnGroup.style.display = 'flex';
        btnGroup.style.gap = '6px';

        // Bouton Activer / Désactiver
        const btnToggle = document.createElement('button');
        btnToggle.className = u.is_active ? 'btn btn-danger' : 'btn btn-secondary';
        btnToggle.style.fontSize = '11px';
        btnToggle.textContent = u.is_active ? 'Désactiver' : 'Activer';
        btnToggle.onclick = async () => {
          const act = u.is_active ? 'désactiver' : 'activer';
          if (confirm('Voulez-vous vraiment ' + act + ' le compte ' + u.email + ' ?')) {
            try {
              const url = u.is_active ? '/api/admin/users/deactivate' : '/api/admin/users/activate';
              await api(url, {
                method: 'POST',
                body: JSON.stringify({ user_id: u.id })
              });
              loadUsers();
            } catch (err) {
              alert(err.message);
            }
          }
        };
        btnGroup.appendChild(btnToggle);

        // Bouton Déconnecter partout
        const btnDisc = document.createElement('button');
        btnDisc.className = 'btn btn-secondary';
        btnDisc.style.fontSize = '11px';
        btnDisc.textContent = 'Déconnecter';
        btnDisc.onclick = async () => {
          if (confirm('Révoquer toutes les sessions de ' + u.email + ' ?')) {
            try {
              await api('/api/admin/users/disconnect-all', {
                method: 'POST',
                body: JSON.stringify({ user_id: u.id })
              });
              alert('Toutes les sessions de l’utilisateur ont été supprimées.');
              loadUsers();
            } catch (err) {
              alert(err.message);
            }
          }
        };
        btnGroup.appendChild(btnDisc);

        tdActions.appendChild(btnGroup);
        tr.appendChild(tdActions);

        tbody.appendChild(tr);
      });
    } catch (e) {
      tbody.textContent = '';
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 7;
      td.className = 'alert-danger';
      td.textContent = 'Erreur lors du chargement des utilisateurs : ' + e.message;
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
  }

  // ------------------------------------------------------------------ 4. Événements de sécurité
  async function loadSecurity() {
    try {
      const data = await api('/api/admin/security-events');
      if (!data) return;

      document.getElementById('sec-failed-count').textContent = data.summary.failed_logins_count;
      document.getElementById('sec-quarantine-count').textContent = data.summary.quarantined_keys_count;
      document.getElementById('sec-canary-count').textContent = data.summary.canary_events_count;

      // 1. Échecs de connexion
      const tbFailed = document.getElementById('sec-failed-tbody');
      tbFailed.textContent = '';
      if (!data.failed_logins || data.failed_logins.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 4;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucun échec d’authentification enregistré.';
        tr.appendChild(td);
        tbFailed.appendChild(tr);
      } else {
        data.failed_logins.forEach(f => {
          const tr = document.createElement('tr');

          const tdDate = document.createElement('td');
          tdDate.className = 'mono';
          tdDate.textContent = formatTimestamp(f.created_at);
          tr.appendChild(tdDate);

          const tdEmail = document.createElement('td');
          tdEmail.className = 'mono break-all';
          tdEmail.textContent = f.email;
          tr.appendChild(tdEmail);

          const tdIp = document.createElement('td');
          tdIp.className = 'mono';
          tdIp.textContent = f.ip || '—';
          tr.appendChild(tdIp);

          const tdReason = document.createElement('td');
          tdReason.textContent = f.reason || 'Identifiants invalides';
          tr.appendChild(tdReason);

          tbFailed.appendChild(tr);
        });
      }

      // 2. Quarantaines
      const tbQuar = document.getElementById('sec-quarantine-tbody');
      tbQuar.textContent = '';
      if (!data.quarantined_keys || data.quarantined_keys.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 5;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucune clé agent en quarantaine active.';
        tr.appendChild(td);
        tbQuar.appendChild(tr);
      } else {
        data.quarantined_keys.forEach(k => {
          const tr = document.createElement('tr');

          const tdOrg = document.createElement('td');
          tdOrg.textContent = k.org_name;
          tr.appendChild(tdOrg);

          const tdName = document.createElement('td');
          tdName.textContent = k.name;
          tr.appendChild(tdName);

          const tdPref = document.createElement('td');
          tdPref.className = 'mono';
          tdPref.textContent = k.key_prefix + '...';
          tr.appendChild(tdPref);

          const tdReason = document.createElement('td');
          tdReason.textContent = k.quarantine_reason || 'Activité anormale détectée';
          tr.appendChild(tdReason);

          const tdUntil = document.createElement('td');
          tdUntil.className = 'mono';
          tdUntil.textContent = formatTimestamp(k.quarantined_until);
          tr.appendChild(tdUntil);

          tbQuar.appendChild(tr);
        });
      }

      // 3. Appâts touchés
      const tbCanary = document.getElementById('sec-canary-tbody');
      tbCanary.textContent = '';
      if (!data.canary_events || data.canary_events.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 4;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Aucun piège appât déclenché à ce jour.';
        tr.appendChild(td);
        tbCanary.appendChild(tr);
      } else {
        data.canary_events.forEach(c => {
          const tr = document.createElement('tr');

          const tdDate = document.createElement('td');
          tdDate.className = 'mono';
          tdDate.textContent = formatTimestamp(c.created_at);
          tr.appendChild(tdDate);

          const tdOrg = document.createElement('td');
          tdOrg.textContent = c.org_name || c.org_id || 'Plateforme';
          tr.appendChild(tdOrg);

          const tdType = document.createElement('td');
          const badge = document.createElement('span');
          badge.className = 'badge badge-danger';
          badge.textContent = 'APPÂT DÉCLENCHÉ';
          tdType.appendChild(badge);
          tr.appendChild(tdType);

          const tdDet = document.createElement('td');
          tdDet.className = 'mono break-all';
          tdDet.textContent = c.recipient ? 'Paiement vers destination appât ' + c.recipient : JSON.stringify(c.details || {});
          tr.appendChild(tdDet);

          tbCanary.appendChild(tr);
        });
      }

    } catch (e) {
      console.error('Erreur sécurité admin :', e);
    }
  }

  // ------------------------------------------------------------------ 5. Journal d'audit
  async function loadAudit() {
    const tbody = document.getElementById('audit-tbody');
    try {
      const list = await api('/api/admin/audit');
      tbody.textContent = '';
      if (!list || list.length === 0) {
        const tr = document.createElement('tr');
        const td = document.createElement('td');
        td.colSpan = 6;
        td.style.textAlign = 'center';
        td.style.color = 'var(--ink-muted)';
        td.textContent = 'Journal d’audit vide.';
        tr.appendChild(td);
        tbody.appendChild(tr);
        return;
      }

      list.forEach(a => {
        const tr = document.createElement('tr');

        const tdDate = document.createElement('td');
        tdDate.className = 'mono';
        tdDate.textContent = formatTimestamp(a.created_at);
        tr.appendChild(tdDate);

        const tdOrg = document.createElement('td');
        tdOrg.textContent = a.org_name || a.org_id || 'Système';
        tr.appendChild(tdOrg);

        const tdUser = document.createElement('td');
        tdUser.className = 'mono break-all';
        tdUser.textContent = a.user_email || a.user_id || (a.api_key_id ? 'Clé ' + a.api_key_id.slice(0, 8) : 'Système');
        tr.appendChild(tdUser);

        const tdAction = document.createElement('td');
        const actBadge = document.createElement('span');
        actBadge.className = 'badge badge-viewer';
        actBadge.textContent = a.action;
        tdAction.appendChild(actBadge);
        tr.appendChild(tdAction);

        const tdIp = document.createElement('td');
        tdIp.className = 'mono';
        tdIp.textContent = a.ip || '—';
        tr.appendChild(tdIp);

        const tdHash = document.createElement('td');
        tdHash.className = 'mono break-all';
        tdHash.textContent = (a.entry_hash || '').slice(0, 16) + '...';
        tdHash.title = a.entry_hash;
        tr.appendChild(tdHash);

        tbody.appendChild(tr);
      });

      // Bouton vérifier
      const btnVerify = document.getElementById('btn-verify-audit');
      const statusEl = document.getElementById('audit-verify-status');
      if (btnVerify) {
        btnVerify.onclick = async () => {
          statusEl.textContent = 'Vérification en cours...';
          statusEl.style.color = 'var(--ink-muted)';
          try {
            const res = await api('/api/admin/audit/verify', { method: 'POST', body: '{}' });
            if (res.valid) {
              statusEl.textContent = 'Intégrité confirmée : ' + (res.count || list.length) + ' maillons vérifiés sans anomalie.';
              statusEl.style.color = 'var(--status-green)';
            } else {
              statusEl.textContent = 'ALERTE : altération de la chaîne détectée au maillon #' + (res.tampered_id || 'inconnu');
              statusEl.style.color = 'var(--status-red)';
            }
          } catch (err) {
            statusEl.textContent = 'Erreur : ' + err.message;
            statusEl.style.color = 'var(--status-red)';
          }
        };
      }
    } catch (e) {
      tbody.textContent = '';
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 6;
      td.className = 'alert-danger';
      td.textContent = 'Erreur lors du chargement du journal d’audit : ' + e.message;
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
  }

  // ------------------------------------------------------------------ 6. Santé de la plateforme
  async function loadHealth() {
    try {
      const data = await api('/api/admin/health');
      if (!data) return;

      // Base SQLite
      const dbStatusEl = document.getElementById('health-db-status');
      const dbSubEl = document.getElementById('health-db-sub');
      const dbOk = data.database && data.database.status === 'ok';
      dbStatusEl.textContent = dbOk ? 'OK' : 'Erreur';
      dbStatusEl.style.color = dbOk ? 'var(--status-green)' : 'var(--status-red)';
      dbSubEl.textContent = 'Mode WAL · Latence : ' + (data.database ? data.database.latency_ms : '—') + ' ms';

      // RPC Avalanche
      const rpcStatusEl = document.getElementById('health-rpc-status');
      const rpcSubEl = document.getElementById('health-rpc-sub');
      const rpcOk = data.avalanche_rpc && data.avalanche_rpc.status === 'ok';
      rpcStatusEl.textContent = rpcOk ? 'Connecté' : (data.avalanche_rpc ? data.avalanche_rpc.status : 'Non disponible');
      rpcStatusEl.style.color = rpcOk ? 'var(--status-green)' : 'var(--status-amber)';
      if (rpcOk) {
        rpcSubEl.textContent = 'Bloc #' + data.avalanche_rpc.block_number + ' · Latence : ' + data.avalanche_rpc.latency_ms + ' ms';
      } else {
        rpcSubEl.textContent = 'URL : ' + (data.avalanche_rpc ? data.avalanche_rpc.url : '—');
      }

      // Version
      document.getElementById('health-version').textContent = data.version || '3.0.0';
    } catch (e) {
      console.error('Erreur santé admin :', e);
    }
  }

  window.addEventListener('DOMContentLoaded', init);
})();
