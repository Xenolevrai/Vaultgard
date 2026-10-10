// Vaultgard — Invoice Audit & Payment Dashboard Core Engine
// Zero-dependency universal module (Browser + Node.js)

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.Vaultgard = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  // ===========================================================================
  // 1. INVOICE STATUS MODEL
  // ===========================================================================
  const STATUSES = Object.freeze({
    RECEIVED: 'received',
    PENDING_VERIFICATION: 'pending_verification',
    UNDER_REVIEW: 'under_review',
    FLAGGED: 'flagged',
    REJECTED: 'rejected',
    VERIFIED_APPROVED: 'verified_approved',
    READY_TO_PAY: 'ready_to_pay',
    SCHEDULED: 'scheduled',
    PAID: 'paid',
    ON_HOLD: 'on_hold'
  });

  const STATUS_META = Object.freeze({
    received: {
      id: 'received',
      label: 'Received / New',
      labelFr: 'Reçue / Nouvelle',
      description: 'Just ingested, no checks run yet',
      color: 'slate',
      payable: false
    },
    pending_verification: {
      id: 'pending_verification',
      label: 'Pending verification',
      labelFr: 'En attente de vérification',
      description: 'In the audit queue',
      color: 'amber',
      payable: false
    },
    under_review: {
      id: 'under_review',
      label: 'Under review',
      labelFr: 'En cours d’audit',
      description: 'Assigned to an auditor',
      color: 'blue',
      payable: false
    },
    flagged: {
      id: 'flagged',
      label: 'Flagged / Suspicious',
      labelFr: 'Signalée / Suspecte',
      description: 'Fraud indicators detected',
      color: 'orange',
      payable: false
    },
    rejected: {
      id: 'rejected',
      label: 'Rejected / Confirmed scam',
      labelFr: 'Rejetée / Fraude confirmée',
      description: 'Blocked, cannot be paid',
      color: 'red',
      payable: false
    },
    verified_approved: {
      id: 'verified_approved',
      label: 'Verified & approved',
      labelFr: 'Vérifiée & approuvée',
      description: 'Audited and clean',
      color: 'emerald',
      payable: true
    },
    ready_to_pay: {
      id: 'ready_to_pay',
      label: 'Ready to pay',
      labelFr: 'Prête à payer',
      description: 'Approved, due date reached or approaching',
      color: 'teal',
      payable: true
    },
    scheduled: {
      id: 'scheduled',
      label: 'Scheduled',
      labelFr: 'Paiement planifié',
      description: 'Payment date set',
      color: 'indigo',
      payable: true
    },
    paid: {
      id: 'paid',
      label: 'Paid',
      labelFr: 'Payée',
      description: 'With payment reference',
      color: 'green',
      payable: false
    },
    on_hold: {
      id: 'on_hold',
      label: 'On hold / Disputed',
      labelFr: 'En suspens / Litige',
      description: 'Waiting on supplier or internal clarification',
      color: 'purple',
      payable: false
    }
  });

  const ALL_STATUS_KEYS = Object.freeze(Object.keys(STATUS_META));

  // Exchange rates relative to EUR (base)
  const FX_RATES = Object.freeze({
    EUR: 1.0,
    USD: 0.92, // 1 USD = 0.92 EUR
    GBP: 1.17, // 1 GBP = 1.17 EUR
    CHF: 1.04  // 1 CHF = 1.04 EUR
  });

  function convertCurrency(amount, fromCurrency = 'EUR', toCurrency = 'EUR') {
    const num = Number(amount) || 0;
    if (fromCurrency === toCurrency) return num;
    const fromRate = FX_RATES[fromCurrency] || 1.0;
    const toRate = FX_RATES[toCurrency] || 1.0;
    const inEur = num * fromRate;
    return Number((inEur / toRate).toFixed(2));
  }

  function formatMoney(amount, currency = 'EUR', locale = 'en-US') {
    const num = Number(amount) || 0;
    try {
      return new Intl.NumberFormat(locale, {
        style: 'currency',
        currency: FX_RATES[currency] ? currency : 'EUR',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }).format(num);
    } catch (_) {
      return `${currency} ${num.toFixed(2)}`;
    }
  }

  // ===========================================================================
  // 10. ROLES, PERMISSIONS & SEGREGATION OF DUTIES
  // ===========================================================================
  const ROLES = Object.freeze({
    VIEWER: 'viewer',
    AUDITOR: 'auditor',
    APPROVER: 'approver',
    PAYER: 'payer',
    ADMIN: 'admin'
  });

  const ROLE_PERMISSIONS = Object.freeze({
    viewer: new Set(['view']),
    auditor: new Set([
      'view',
      'run_checks',
      'assign',
      'flag',
      'request_info',
      'escalate',
      'hold',
      'release',
      'verify_callback',
      'comment',
      'attach',
      'ingest'
    ]),
    approver: new Set([
      'view',
      'run_checks',
      'assign',
      'approve',
      'reject',
      'flag',
      'request_info',
      'escalate',
      'hold',
      'release',
      'verify_callback',
      'approve_and_schedule',
      'comment',
      'attach'
    ]),
    payer: new Set([
      'view',
      'schedule_payment',
      'create_batch',
      'mark_paid',
      'partial_payment',
      'apply_credit_note',
      'reconcile_bank',
      'comment',
      'attach'
    ]),
    admin: new Set([
      'view',
      'run_checks',
      'assign',
      'approve',
      'reject',
      'flag',
      'request_info',
      'escalate',
      'hold',
      'release',
      'verify_callback',
      'approve_and_schedule',
      'schedule_payment',
      'create_batch',
      'mark_paid',
      'partial_payment',
      'apply_credit_note',
      'reconcile_bank',
      'comment',
      'attach',
      'ingest',
      'manage_suppliers',
      'manage_settings'
    ])
  });

  function hasPermission(actor, permission) {
    if (!actor || !actor.role) return false;
    const perms = ROLE_PERMISSIONS[actor.role];
    return Boolean(perms && perms.has(permission));
  }

  function checkDepartmentAndAmountAccess(actor, invoice, settings) {
    if (!actor) return { allowed: false, reason: 'Missing actor context' };
    if (actor.role === ROLES.ADMIN) return { allowed: true };
    if (actor.departments && actor.departments.length > 0 && !actor.departments.includes('ALL')) {
      if (invoice.department && !actor.departments.includes(invoice.department)) {
        return {
          allowed: false,
          reason: `Access restricted: Actor department scope (${actor.departments.join(', ')}) does not cover ${invoice.department}`
        };
      }
    }
    if (actor.entities && actor.entities.length > 0 && !actor.entities.includes('ALL')) {
      if (invoice.entity && !actor.entities.includes(invoice.entity)) {
        return {
          allowed: false,
          reason: `Access restricted: Actor entity scope (${actor.entities.join(', ')}) does not cover ${invoice.entity}`
        };
      }
    }
    if (typeof actor.maxApprovalAmount === 'number') {
      const amountEur = convertCurrency(invoice.amount, invoice.currency, 'EUR');
      if (amountEur > actor.maxApprovalAmount) {
        return {
          allowed: false,
          reason: `Amount (${formatMoney(amountEur, 'EUR')}) exceeds actor approval limit (${formatMoney(actor.maxApprovalAmount, 'EUR')})`
        };
      }
    }
    return { allowed: true };
  }

  function hasActorApprovedInvoice(invoice, actor) {
    if (!invoice || !actor) return false;
    if (invoice.approvedBy && (invoice.approvedBy === actor.id || invoice.approvedBy === actor.name)) {
      return true;
    }
    if (Array.isArray(invoice.approvals)) {
      return invoice.approvals.some(
        (a) => a.userId === actor.id || a.userName === actor.name
      );
    }
    return false;
  }

  // ===========================================================================
  // 11. AUDIT TRAIL & HASH CHAIN
  // ===========================================================================
  function simpleHash(str) {
    let h = 2166136261 >>> 0;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h.toString(16).padStart(8, '0');
  }

  function appendAuditLog(state, entry) {
    const prev = state.auditLog.length > 0 ? state.auditLog[state.auditLog.length - 1] : null;
    const prevHash = prev ? prev.hash : '00000000';
    const timestamp = entry.timestamp || new Date().toISOString();
    const id = `AUD-${String(state.auditLog.length + 1).padStart(4, '0')}`;
    const payloadStr = `${id}|${timestamp}|${entry.actorId || 'system'}|${entry.action}|${entry.entityId || ''}|${prevHash}`;
    const record = Object.freeze({
      id,
      timestamp,
      actorId: entry.actorId || 'system',
      actorName: entry.actorName || 'System',
      actorRole: entry.actorRole || 'system',
      action: entry.action,
      entityType: entry.entityType || 'invoice',
      entityId: entry.entityId || '',
      summary: entry.summary || '',
      details: Object.freeze({ ...(entry.details || {}) }),
      prevHash,
      hash: simpleHash(payloadStr)
    });
    state.auditLog.push(record);
    return record;
  }

  function verifyAuditLogIntegrity(auditLog) {
    for (let i = 0; i < auditLog.length; i++) {
      const entry = auditLog[i];
      const expectedPrev = i === 0 ? '00000000' : auditLog[i - 1].hash;
      if (entry.prevHash !== expectedPrev) {
        return { valid: false, brokenAtIndex: i, id: entry.id };
      }
      const payloadStr = `${entry.id}|${entry.timestamp}|${entry.actorId}|${entry.action}|${entry.entityId}|${entry.prevHash}`;
      if (entry.hash !== simpleHash(payloadStr)) {
        return { valid: false, brokenAtIndex: i, id: entry.id };
      }
    }
    return { valid: true, count: auditLog.length };
  }

  function recordInvoiceVersion(invoice, actor, reason) {
    if (!Array.isArray(invoice.versionHistory)) {
      invoice.versionHistory = [];
    }
    const versionNum = invoice.versionHistory.length + 1;
    const snapshot = Object.freeze({
      version: versionNum,
      timestamp: new Date().toISOString(),
      actorId: actor ? actor.id : 'system',
      actorName: actor ? actor.name : 'System',
      reason: reason || 'Update',
      status: invoice.status,
      amount: invoice.amount,
      currency: invoice.currency,
      iban: invoice.iban,
      dueDate: invoice.dueDate,
      assignee: invoice.assignee,
      riskScore: invoice.riskScore,
      riskLevel: invoice.riskLevel
    });
    invoice.versionHistory.push(snapshot);
    return snapshot;
  }

  // ===========================================================================
  // 4. AUDIT AND FRAUD CHECKS ENGINE (9 CHECKS)
  // ===========================================================================
  function levenshtein(a, b) {
    const s = String(a || '').toLowerCase();
    const t = String(b || '').toLowerCase();
    const m = s.length;
    const n = t.length;
    const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
    for (let i = 0; i <= m; i++) dp[i][0] = i;
    for (let j = 0; j <= n; j++) dp[0][j] = j;
    for (let i = 1; i <= m; i++) {
      for (let j = 1; j <= n; j++) {
        const cost = s[i - 1] === t[j - 1] ? 0 : 1;
        dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost);
      }
    }
    return dp[m][n];
  }

  function normalizeLookalike(domain) {
    return String(domain || '')
      .toLowerCase()
      .replace(/rn/g, 'm')
      .replace(/vv/g, 'w')
      .replace(/0/g, 'o')
      .replace(/1/g, 'l');
  }

  function getRequiredApprovalLevels(amountEur, settings) {
    const t1 = (settings && settings.approvalThresholds && settings.approvalThresholds.level1) || 10000;
    const t2 = (settings && settings.approvalThresholds && settings.approvalThresholds.level2) || 50000;
    if (amountEur > t2) return 3;
    if (amountEur > t1) return 2;
    return 1;
  }

  function runAuditChecks(invoice, state) {
    const suppliers = (state && state.suppliers) || [];
    const invoices = (state && state.invoices) || [];
    const settings = (state && state.settings) || {};
    const supplier = suppliers.find((s) => s.id === invoice.supplierId || s.name === invoice.supplierName);

    const checks = [];
    const reasons = [];
    let score = 0;

    // 1. Supplier validation
    const vatRegex = /^[A-Z]{2}[A-Z0-9]{8,12}$/i;
    const vatValid = Boolean(invoice.vatNumber && vatRegex.test(invoice.vatNumber.trim()));
    if (!supplier) {
      checks.push({
        id: 'supplier_validation',
        label: 'Supplier validation',
        status: 'failed',
        reason: 'Supplier is not in the approved vendor master list'
      });
      reasons.push('Unregistered / unknown supplier');
      score += 30;
    } else if (supplier.status === 'blacklisted') {
      checks.push({
        id: 'supplier_validation',
        label: 'Supplier validation',
        status: 'failed',
        reason: `Supplier ${supplier.name} is blacklisted`
      });
      reasons.push('Supplier is on blacklist');
      score += 50;
    } else if (!vatValid || (supplier.vatNumber && supplier.vatNumber !== invoice.vatNumber)) {
      checks.push({
        id: 'supplier_validation',
        label: 'Supplier validation',
        status: 'failed',
        reason: !vatValid
          ? 'Missing or invalid VAT / tax ID format'
          : `VAT mismatch (expected ${supplier.vatNumber}, got ${invoice.vatNumber})`
      });
      reasons.push('Invalid or mismatched supplier VAT / tax ID');
      score += 20;
    } else if (supplier.status === 'pending' || supplier.status === 'watchlist') {
      checks.push({
        id: 'supplier_validation',
        label: 'Supplier validation',
        status: 'pending',
        reason: `Supplier verification status is "${supplier.status}"`
      });
      reasons.push(`Supplier is currently on ${supplier.status}`);
      score += 12;
    } else {
      checks.push({
        id: 'supplier_validation',
        label: 'Supplier validation',
        status: 'passed',
        reason: `Approved vendor (${supplier.regNumber || 'REG-OK'}), VAT ${invoice.vatNumber} verified`
      });
    }

    // 2. Bank details check
    if (!invoice.iban || invoice.iban.trim().length < 14) {
      checks.push({
        id: 'bank_details',
        label: 'Bank details check',
        status: 'failed',
        reason: 'Missing or malformed IBAN on invoice'
      });
      reasons.push('Missing or malformed IBAN');
      score += 25;
    } else if (supplier && supplier.iban && invoice.iban !== supplier.iban) {
      if (invoice.callbackVerified) {
        checks.push({
          id: 'bank_details',
          label: 'Bank details check',
          status: 'passed',
          reason: `IBAN change (${invoice.iban}) verified via phone callback: ${invoice.callbackNotes || 'Confirmed'}`
        });
      } else {
        checks.push({
          id: 'bank_details',
          label: 'Bank details check',
          status: 'failed',
          reason: `IBAN (${invoice.iban}) does not match IBAN on file (${supplier.iban})`
        });
        reasons.push('Bank account (IBAN) mismatch with vendor master file');
        score += 35;
      }
    } else if (supplier && supplier.bankChangedRecently && !invoice.callbackVerified) {
      checks.push({
        id: 'bank_details',
        label: 'Bank details check',
        status: 'failed',
        reason: 'Supplier bank account changed recently; callback verification required'
      });
      reasons.push('Recent bank account change not yet callback-verified');
      score += 25;
    } else {
      checks.push({
        id: 'bank_details',
        label: 'Bank details check',
        status: 'passed',
        reason: `IBAN ${invoice.iban} matches verified bank account on file`
      });
    }

    // 3. Duplicate detection
    const duplicates = invoices.filter((other) => {
      if (other.id === invoice.id) return false;
      const sameNumAndSup =
        other.invoiceNumber.toLowerCase() === invoice.invoiceNumber.toLowerCase() &&
        other.supplierId === invoice.supplierId;
      const sameSupAmtDate =
        other.supplierId === invoice.supplierId &&
        Number(other.amount) === Number(invoice.amount) &&
        other.issueDate === invoice.issueDate;
      return sameNumAndSup || sameSupAmtDate;
    });
    if (duplicates.length > 0) {
      const dupIds = duplicates.map((d) => `${d.id} (${d.invoiceNumber})`).join(', ');
      checks.push({
        id: 'duplicate_detection',
        label: 'Duplicate detection',
        status: 'failed',
        reason: `Potential duplicate of ${dupIds}`
      });
      reasons.push(`Duplicate invoice detected (${dupIds})`);
      score += 40;
    } else {
      checks.push({
        id: 'duplicate_detection',
        label: 'Duplicate detection',
        status: 'passed',
        reason: 'No duplicate invoice number, amount, or date found'
      });
    }

    // 4. Three-way match (Invoice vs PO vs Goods Received Note)
    if (!invoice.poNumber) {
      checks.push({
        id: 'three_way_match',
        label: 'Three-way match (PO / GRN)',
        status: 'failed',
        reason: 'Missing Purchase Order (PO) reference'
      });
      reasons.push('No Purchase Order (PO) linked');
      score += 18;
    } else if (invoice.grnStatus === 'pending') {
      checks.push({
        id: 'three_way_match',
        label: 'Three-way match (PO / GRN)',
        status: 'pending',
        reason: `PO ${invoice.poNumber} matched; awaiting Goods Received Note (GRN)`
      });
      score += 8;
    } else if (
      (typeof invoice.poAmount === 'number' && Math.abs(invoice.poAmount - invoice.amount) > 0.01) ||
      invoice.grnStatus === 'mismatch' ||
      invoice.grnStatus === 'missing'
    ) {
      checks.push({
        id: 'three_way_match',
        label: 'Three-way match (PO / GRN)',
        status: 'failed',
        reason:
          typeof invoice.poAmount === 'number' && Math.abs(invoice.poAmount - invoice.amount) > 0.01
            ? `Invoice amount (${invoice.amount}) differs from PO ${invoice.poNumber} (${invoice.poAmount})`
            : `Delivery receipt (GRN) ${invoice.grnStatus || 'missing'} for PO ${invoice.poNumber}`
      });
      reasons.push(`Three-way match discrepancy on PO ${invoice.poNumber}`);
      score += 22;
    } else {
      checks.push({
        id: 'three_way_match',
        label: 'Three-way match (PO / GRN)',
        status: 'passed',
        reason: `Matched PO ${invoice.poNumber} and delivery receipt ${invoice.grnNumber || 'GRN-OK'}`
      });
    }

    // 5. Amount checks (unusual amount, round numbers, just under approval thresholds)
    const amountEur = convertCurrency(invoice.amount, invoice.currency, 'EUR');
    const t1 = (settings.approvalThresholds && settings.approvalThresholds.level1) || 10000;
    const t2 = (settings.approvalThresholds && settings.approvalThresholds.level2) || 50000;
    const justUnderT1 = amountEur >= t1 * 0.95 && amountEur < t1;
    const justUnderT2 = amountEur >= t2 * 0.95 && amountEur < t2;
    const isSuspiciousRound =
      settings.flagRoundNumbers !== false && amountEur >= 5000 && Number(invoice.amount) % 1000 === 0;
    const isInvalidAmount = !(Number(invoice.amount) > 0);

    if (isInvalidAmount) {
      checks.push({
        id: 'amount_checks',
        label: 'Amount checks',
        status: 'failed',
        reason: `Invalid non-positive invoice amount (${invoice.amount})`
      });
      reasons.push('Invalid (zero or negative) invoice amount');
      score += 40;
    } else if (justUnderT1 || justUnderT2) {
      const thresh = justUnderT2 ? t2 : t1;
      checks.push({
        id: 'amount_checks',
        label: 'Amount checks',
        status: 'failed',
        reason: `Amount (${formatMoney(amountEur, 'EUR')}) is structured just below ${formatMoney(thresh, 'EUR')} approval threshold`
      });
      reasons.push(`Split/structured amount just under ${formatMoney(thresh, 'EUR')} approval threshold`);
      score += 18;
    } else if (isSuspiciousRound) {
      checks.push({
        id: 'amount_checks',
        label: 'Amount checks',
        status: 'failed',
        reason: `Exact round-number billing (${formatMoney(invoice.amount, invoice.currency)}) requires itemization check`
      });
      reasons.push('Unusual exact round-number invoice amount');
      score += 12;
    } else {
      checks.push({
        id: 'amount_checks',
        label: 'Amount checks',
        status: 'passed',
        reason: 'Amount within normal parameters and threshold rules'
      });
    }

    // 6. Document checks (tampering, metadata anomalies, missing mandatory fields)
    const docMeta = invoice.documentMeta || {};
    if (docMeta.tampered || docMeta.fontMismatch || docMeta.modifiedAfterIssue) {
      const issues = [
        docMeta.tampered && 'PDF layer tampering detected',
        docMeta.fontMismatch && 'Inconsistent font glyphs on bank/amount block',
        docMeta.modifiedAfterIssue && 'PDF metadata modified after issue date'
      ].filter(Boolean);
      checks.push({
        id: 'document_checks',
        label: 'Document & metadata checks',
        status: 'failed',
        reason: issues.join('; ')
      });
      reasons.push(`Document integrity failure: ${issues.join(', ')}`);
      score += 40;
    } else if (docMeta.missingLegalMentions || !invoice.vatNumber) {
      checks.push({
        id: 'document_checks',
        label: 'Document & metadata checks',
        status: 'failed',
        reason: 'Missing mandatory legal mentions or VAT registration on PDF'
      });
      reasons.push('Missing mandatory legal mentions or VAT field');
      score += 15;
    } else {
      checks.push({
        id: 'document_checks',
        label: 'Document & metadata checks',
        status: 'passed',
        reason: 'PDF signature, metadata timestamps, and legal mentions valid'
      });
    }

    // 7. Email / sender check (spoofed domain, lookalike addresses)
    const senderEmail = String(invoice.senderEmail || '');
    const senderDomain = senderEmail.includes('@') ? senderEmail.split('@')[1].toLowerCase() : '';
    const officialDomain = supplier && supplier.officialDomain ? supplier.officialDomain.toLowerCase() : '';
    if (!senderDomain) {
      checks.push({
        id: 'email_sender',
        label: 'Email / sender check',
        status: 'pending',
        reason: 'No sender email metadata (manual upload)'
      });
    } else if (officialDomain && senderDomain !== officialDomain) {
      const dist = levenshtein(senderDomain, officialDomain);
      const isHomoglyph =
        normalizeLookalike(senderDomain) === normalizeLookalike(officialDomain) || dist <= 2;
      checks.push({
        id: 'email_sender',
        label: 'Email / sender check',
        status: 'failed',
        reason: isHomoglyph
          ? `Spoofed lookalike domain detected: "${senderDomain}" impersonating "${officialDomain}"`
          : `Sender domain "${senderDomain}" does not match supplier official domain "${officialDomain}"`
      });
      reasons.push(
        isHomoglyph
          ? `Spoofed lookalike sender domain (${senderDomain} vs ${officialDomain})`
          : `Unrecognized sender email domain (${senderDomain})`
      );
      score += isHomoglyph ? 40 : 22;
    } else {
      checks.push({
        id: 'email_sender',
        label: 'Email / sender check',
        status: 'passed',
        reason: `SPF/DKIM aligned with official domain (${senderDomain})`
      });
    }

    // 8. Anomaly detection (deviation from supplier history)
    const multiplier = Number(settings.anomalyMultiplier) || 2.5;
    const avgAmt = supplier && Number(supplier.avgInvoiceAmount) > 0 ? Number(supplier.avgInvoiceAmount) : 0;
    if (avgAmt > 0 && amountEur > avgAmt * multiplier) {
      const ratio = (amountEur / avgAmt).toFixed(1);
      checks.push({
        id: 'anomaly_detection',
        label: 'Historical anomaly detection',
        status: 'failed',
        reason: `Invoice amount is ${ratio}x supplier historical average (${formatMoney(avgAmt, 'EUR')})`
      });
      reasons.push(`Amount is ${ratio}x supplier historical average`);
      score += 20;
    } else {
      checks.push({
        id: 'anomaly_detection',
        label: 'Historical anomaly detection',
        status: 'passed',
        reason: avgAmt
          ? `Consistent with supplier historical average (${formatMoney(avgAmt, 'EUR')})`
          : 'No historical anomaly detected'
      });
    }

    // 9. Sanctions / blacklist screening
    if ((supplier && (supplier.sanctionsHit || supplier.status === 'blacklisted')) || invoice.sanctionsHit) {
      checks.push({
        id: 'sanctions_screening',
        label: 'Sanctions & blacklist screening',
        status: 'failed',
        reason: 'Match found on OFAC / EU Sanctions or internal Fraud Blacklist'
      });
      reasons.push('Sanctions / Fraud Blacklist hit');
      score += 60;
    } else {
      checks.push({
        id: 'sanctions_screening',
        label: 'Sanctions & blacklist screening',
        status: 'passed',
        reason: 'Cleared OFAC, EU, UN sanctions and internal watchlist'
      });
    }

    const finalScore = Math.min(100, score);
    const highThreshold = Number(settings.highRiskThreshold) || 65;
    const medThreshold = Number(settings.mediumRiskThreshold) || 30;
    let riskLevel = 'low';
    if (
      finalScore >= highThreshold ||
      checks.some((c) => c.id === 'sanctions_screening' && c.status === 'failed') ||
      checks.some((c) => c.id === 'document_checks' && c.status === 'failed' && docMeta.tampered)
    ) {
      riskLevel = 'high';
    } else if (finalScore >= medThreshold) {
      riskLevel = 'medium';
    }

    return {
      checklist: checks,
      riskScore: finalScore,
      riskLevel,
      riskReasons: reasons,
      requiredApprovalLevels: getRequiredApprovalLevels(amountEur, settings),
      passedCount: checks.filter((c) => c.status === 'passed').length,
      failedCount: checks.filter((c) => c.status === 'failed').length,
      pendingCount: checks.filter((c) => c.status === 'pending').length
    };
  }

  // ===========================================================================
  // 2. MAIN OVERVIEW KPI ENGINE
  // ===========================================================================
  function computeKPIs(state, nowInput) {
    const now = nowInput ? new Date(nowInput) : new Date(state.referenceDate || '2026-10-10T12:00:00Z');
    const baseCurrency = (state.settings && state.settings.baseCurrency) || 'EUR';
    const invoices = state.invoices || [];

    const byStatus = {};
    for (const key of ALL_STATUS_KEYS) {
      byStatus[key] = { count: 0, totalAmount: 0 };
    }

    let readyToday = 0;
    let readyThisWeek = 0;
    let readyThisMonth = 0;
    let readyCount = 0;

    let pendingCount = 0;
    let pendingAmount = 0;
    let oldestPending = null;

    let flaggedCount = 0;
    let flaggedAmountAtRisk = 0;
    let rejectedCount = 0;
    let rejectedAmountSaved = 0;

    let verificationTimeTotalHours = 0;
    let verifiedMeasuredCount = 0;

    let overdueCount = 0;
    let overdueAmount = 0;
    const overdueInvoices = [];

    const todayStr = now.toISOString().slice(0, 10);
    const weekEnd = new Date(now.getTime() + 7 * 86400000).toISOString().slice(0, 10);
    const monthEnd = new Date(now.getTime() + 30 * 86400000).toISOString().slice(0, 10);

    const monthlyMap = new Map();
    const supplierMap = new Map();

    for (const inv of invoices) {
      const remaining = getRemainingAmount(inv);
      const amtBase = convertCurrency(inv.amount, inv.currency, baseCurrency);
      const remBase = convertCurrency(remaining, inv.currency, baseCurrency);

      if (byStatus[inv.status]) {
        byStatus[inv.status].count += 1;
        byStatus[inv.status].totalAmount = Number((byStatus[inv.status].totalAmount + amtBase).toFixed(2));
      }

      // Ready to pay buckets (approved, ready_to_pay, scheduled)
      if (
        inv.status === STATUSES.READY_TO_PAY ||
        inv.status === STATUSES.VERIFIED_APPROVED ||
        inv.status === STATUSES.SCHEDULED
      ) {
        readyCount += 1;
        if (inv.dueDate <= todayStr) {
          readyToday = Number((readyToday + remBase).toFixed(2));
        }
        if (inv.dueDate <= weekEnd) {
          readyThisWeek = Number((readyThisWeek + remBase).toFixed(2));
        }
        if (inv.dueDate <= monthEnd) {
          readyThisMonth = Number((readyThisMonth + remBase).toFixed(2));
        }
      }

      // Pending verification queue
      if (
        inv.status === STATUSES.RECEIVED ||
        inv.status === STATUSES.PENDING_VERIFICATION ||
        inv.status === STATUSES.UNDER_REVIEW
      ) {
        pendingCount += 1;
        pendingAmount = Number((pendingAmount + amtBase).toFixed(2));
        const recTime = new Date(inv.receivedAt || inv.issueDate).getTime();
        const ageHours = Math.max(0, Math.round((now.getTime() - recTime) / 3600000));
        if (!oldestPending || recTime < oldestPending._recTime) {
          oldestPending = {
            id: inv.id,
            invoiceNumber: inv.invoiceNumber,
            supplierName: inv.supplierName,
            receivedAt: inv.receivedAt || inv.issueDate,
            ageHours,
            _recTime: recTime
          };
        }
      }

      // Flagged & Rejected (at risk / fraud caught)
      if (inv.status === STATUSES.FLAGGED) {
        flaggedCount += 1;
        flaggedAmountAtRisk = Number((flaggedAmountAtRisk + amtBase).toFixed(2));
      }
      if (inv.status === STATUSES.REJECTED) {
        rejectedCount += 1;
        rejectedAmountSaved = Number((rejectedAmountSaved + amtBase).toFixed(2));
      }

      // Verification turnaround time
      if (inv.receivedAt && inv.verifiedAt) {
        const diffH = (new Date(inv.verifiedAt).getTime() - new Date(inv.receivedAt).getTime()) / 3600000;
        if (diffH >= 0) {
          verificationTimeTotalHours += diffH;
          verifiedMeasuredCount += 1;
        }
      }

      // Overdue (past dueDate, not paid, not rejected)
      if (
        inv.dueDate &&
        inv.dueDate < todayStr &&
        inv.status !== STATUSES.PAID &&
        inv.status !== STATUSES.REJECTED
      ) {
        overdueCount += 1;
        overdueAmount = Number((overdueAmount + remBase).toFixed(2));
        overdueInvoices.push(inv);
      }

      // Monthly trend aggregation
      const monthKey = (inv.issueDate || todayStr).slice(0, 7);
      if (!monthlyMap.has(monthKey)) {
        monthlyMap.set(monthKey, {
          month: monthKey,
          totalAmount: 0,
          verifiedAmount: 0,
          paidAmount: 0,
          flaggedAmount: 0,
          count: 0
        });
      }
      const mRow = monthlyMap.get(monthKey);
      mRow.count += 1;
      mRow.totalAmount = Number((mRow.totalAmount + amtBase).toFixed(2));
      if (
        inv.status === STATUSES.VERIFIED_APPROVED ||
        inv.status === STATUSES.READY_TO_PAY ||
        inv.status === STATUSES.SCHEDULED
      ) {
        mRow.verifiedAmount = Number((mRow.verifiedAmount + amtBase).toFixed(2));
      } else if (inv.status === STATUSES.PAID) {
        mRow.paidAmount = Number((mRow.paidAmount + amtBase).toFixed(2));
      } else if (inv.status === STATUSES.FLAGGED || inv.status === STATUSES.REJECTED) {
        mRow.flaggedAmount = Number((mRow.flaggedAmount + amtBase).toFixed(2));
      }

      // Supplier trend aggregation
      const supKey = inv.supplierId || inv.supplierName;
      if (!supplierMap.has(supKey)) {
        supplierMap.set(supKey, {
          supplierId: inv.supplierId,
          supplierName: inv.supplierName,
          count: 0,
          totalAmount: 0,
          flaggedCount: 0,
          maxRiskScore: 0
        });
      }
      const sRow = supplierMap.get(supKey);
      sRow.count += 1;
      sRow.totalAmount = Number((sRow.totalAmount + amtBase).toFixed(2));
      if (inv.status === STATUSES.FLAGGED || inv.status === STATUSES.REJECTED) {
        sRow.flaggedCount += 1;
      }
      if ((inv.riskScore || 0) > sRow.maxRiskScore) {
        sRow.maxRiskScore = inv.riskScore || 0;
      }
    }

    if (oldestPending) {
      delete oldestPending._recTime;
    }

    const avgVerificationTimeHours =
      verifiedMeasuredCount > 0
        ? Number((verificationTimeTotalHours / verifiedMeasuredCount).toFixed(1))
        : 0;

    return {
      baseCurrency,
      totalInvoices: invoices.length,
      byStatus,
      readyToPay: {
        today: readyToday,
        thisWeek: readyThisWeek,
        thisMonth: readyThisMonth,
        count: readyCount
      },
      pendingVerification: {
        count: pendingCount,
        totalAmount: pendingAmount,
        oldestInvoice: oldestPending
      },
      flagged: {
        count: flaggedCount,
        amountAtRisk: flaggedAmountAtRisk,
        rejectedCount,
        moneySaved: Number((flaggedAmountAtRisk + rejectedAmountSaved).toFixed(2)),
        confirmedScamAmount: rejectedAmountSaved
      },
      avgVerificationTimeHours,
      overdue: {
        count: overdueCount,
        totalAmount: overdueAmount,
        invoices: overdueInvoices
      },
      trends: {
        byMonth: Array.from(monthlyMap.values()).sort((a, b) => a.month.localeCompare(b.month)),
        bySupplier: Array.from(supplierMap.values()).sort((a, b) => b.totalAmount - a.totalAmount)
      }
    };
  }

  // ===========================================================================
  // 3. INVOICE LIST, SEARCH, FILTER, SORT & EXPORT
  // ===========================================================================
  function queryInvoices(state, query = {}) {
    const invoices = state.invoices || [];
    const nowStr = new Date(state.referenceDate || '2026-10-10T12:00:00Z').toISOString().slice(0, 10);
    const weekEndStr = new Date(
      new Date(state.referenceDate || '2026-10-10T12:00:00Z').getTime() + 7 * 86400000
    )
      .toISOString()
      .slice(0, 10);

    let result = invoices.filter((inv) => {
      // Search by invoice number, supplier, amount, or PO number
      if (query.search && String(query.search).trim() !== '') {
        const q = String(query.search).trim().toLowerCase();
        const matchNum = String(inv.invoiceNumber || '').toLowerCase().includes(q);
        const matchSup = String(inv.supplierName || '').toLowerCase().includes(q);
        const matchAmt = String(inv.amount || '').toLowerCase().includes(q);
        const matchPo = String(inv.poNumber || '').toLowerCase().includes(q);
        const matchId = String(inv.id || '').toLowerCase().includes(q);
        if (!matchNum && !matchSup && !matchAmt && !matchPo && !matchId) {
          return false;
        }
      }

      // Filter by status (string or array)
      if (query.status && query.status !== 'all') {
        if (Array.isArray(query.status)) {
          if (query.status.length > 0 && !query.status.includes(inv.status)) return false;
        } else if (inv.status !== query.status) {
          return false;
        }
      }

      // Filter by supplier
      if (query.supplierId && query.supplierId !== 'all') {
        if (inv.supplierId !== query.supplierId && inv.supplierName !== query.supplierId) return false;
      }

      // Filter by date range (issueDate or dueDate)
      const dateField = query.dateField === 'issueDate' ? inv.issueDate : inv.dueDate;
      if (query.dateFrom && dateField < query.dateFrom) return false;
      if (query.dateTo && dateField > query.dateTo) return false;

      // Filter by amount range (in EUR or invoice currency)
      if (query.amountMin !== undefined && query.amountMin !== '' && query.amountMin !== null) {
        if (Number(inv.amount) < Number(query.amountMin)) return false;
      }
      if (query.amountMax !== undefined && query.amountMax !== '' && query.amountMax !== null) {
        if (Number(inv.amount) > Number(query.amountMax)) return false;
      }

      // Filter by risk level
      if (query.riskLevel && query.riskLevel !== 'all') {
        if (inv.riskLevel !== query.riskLevel) return false;
      }

      // Filter by department
      if (query.department && query.department !== 'all') {
        if (inv.department !== query.department) return false;
      }

      // Filter by assignee
      if (query.assignee && query.assignee !== 'all') {
        if (inv.assignee !== query.assignee) return false;
      }

      // Filter by payment method
      if (query.paymentMethod && query.paymentMethod !== 'all') {
        if (inv.paymentMethod !== query.paymentMethod) return false;
      }

      // Preset view filters
      if (query.preset === 'ready_this_week') {
        const isPayable =
          inv.status === STATUSES.READY_TO_PAY ||
          inv.status === STATUSES.VERIFIED_APPROVED ||
          inv.status === STATUSES.SCHEDULED;
        if (!isPayable || inv.dueDate > weekEndStr) return false;
      } else if (query.preset === 'overdue') {
        if (
          !inv.dueDate ||
          inv.dueDate >= nowStr ||
          inv.status === STATUSES.PAID ||
          inv.status === STATUSES.REJECTED
        ) {
          return false;
        }
      } else if (query.preset === 'high_risk') {
        if (
          inv.riskLevel !== 'high' &&
          inv.status !== STATUSES.FLAGGED &&
          inv.status !== STATUSES.REJECTED
        ) {
          return false;
        }
      } else if (query.preset === 'pending_audit') {
        if (
          inv.status !== STATUSES.RECEIVED &&
          inv.status !== STATUSES.PENDING_VERIFICATION &&
          inv.status !== STATUSES.UNDER_REVIEW
        ) {
          return false;
        }
      }

      return true;
    });

    // Sorting
    const sortBy = query.sortBy || 'dueDate';
    const sortDir = query.sortDir === 'desc' ? -1 : 1;
    result = result.slice().sort((a, b) => {
      let va = a[sortBy];
      let vb = b[sortBy];
      if (sortBy === 'amount' || sortBy === 'riskScore') {
        va = Number(va) || 0;
        vb = Number(vb) || 0;
        return (va - vb) * sortDir;
      }
      va = String(va ?? '').toLowerCase();
      vb = String(vb ?? '').toLowerCase();
      if (va < vb) return -1 * sortDir;
      if (va > vb) return 1 * sortDir;
      return 0;
    });

    return result;
  }

  function escapeCsvCell(val) {
    const s = String(val ?? '');
    if (s.includes(',') || s.includes('"') || s.includes('\n')) {
      return `"${s.replace(/"/g, '""')}"`;
    }
    return s;
  }

  function exportInvoicesCSV(invoices) {
    const headers = [
      'ID',
      'Invoice Number',
      'Supplier',
      'Amount',
      'Currency',
      'Issue Date',
      'Due Date',
      'Status',
      'Risk Level',
      'Risk Score',
      'PO Number',
      'Department',
      'Assignee',
      'Payment Method',
      'IBAN'
    ];
    const rows = invoices.map((inv) =>
      [
        inv.id,
        inv.invoiceNumber,
        inv.supplierName,
        inv.amount,
        inv.currency,
        inv.issueDate,
        inv.dueDate,
        inv.status,
        inv.riskLevel,
        inv.riskScore,
        inv.poNumber || '',
        inv.department || '',
        inv.assignee || 'Unassigned',
        inv.paymentMethod || 'SEPA',
        inv.iban || ''
      ]
        .map(escapeCsvCell)
        .join(',')
    );
    return [headers.join(','), ...rows].join('\n');
  }

  // ===========================================================================
  // 6. WORKFLOW AND ACTIONS
  // ===========================================================================
  function addTimelineEvent(invoice, event, actor, note) {
    if (!Array.isArray(invoice.timeline)) invoice.timeline = [];
    invoice.timeline.push({
      id: `TL-${invoice.timeline.length + 1}`,
      timestamp: new Date().toISOString(),
      event,
      actorName: actor ? actor.name : 'System',
      actorRole: actor ? actor.role : 'system',
      note: note || ''
    });
  }

  function performWorkflowAction(state, invoiceId, action, payload = {}, actor = null) {
    const user = actor || state.currentUser;
    const inv = (state.invoices || []).find((i) => i.id === invoiceId);
    if (!inv) {
      throw new Error(`Invoice ${invoiceId} not found`);
    }

    // Check role permissions
    const actionPermissionMap = {
      run_checks: 'run_checks',
      assign: 'assign',
      approve: 'approve',
      reject: 'reject',
      flag: 'flag',
      request_info: 'request_info',
      escalate: 'escalate',
      hold: 'hold',
      release: 'release',
      verify_callback: 'verify_callback',
      approve_and_schedule: 'approve_and_schedule',
      comment: 'comment',
      attach: 'attach'
    };

    const reqPerm = actionPermissionMap[action];
    if (!reqPerm || !hasPermission(user, reqPerm)) {
      throw new Error(`Permission denied: Role "${user ? user.role : 'none'}" cannot perform "${action}"`);
    }

    // Check department/entity/amount scope for approval actions
    if (action === 'approve' || action === 'approve_and_schedule' || action === 'reject') {
      const scopeCheck = checkDepartmentAndAmountAccess(user, inv, state.settings);
      if (!scopeCheck.allowed) {
        throw new Error(scopeCheck.reason);
      }
    }

    if (action === 'run_checks') {
      const auditResult = runAuditChecks(inv, state);
      inv.checklist = auditResult.checklist;
      inv.riskScore = auditResult.riskScore;
      inv.riskLevel = auditResult.riskLevel;
      inv.riskReasons = auditResult.riskReasons;
      inv.requiredApprovalLevels = auditResult.requiredApprovalLevels;
      if (inv.status === STATUSES.RECEIVED) {
        inv.status =
          auditResult.riskLevel === 'high' ? STATUSES.FLAGGED : STATUSES.PENDING_VERIFICATION;
      }
      addTimelineEvent(
        inv,
        `Automated audit checks executed (Risk: ${inv.riskLevel.toUpperCase()} / ${inv.riskScore})`,
        user,
        inv.riskReasons.join('; ') || 'All checks clean'
      );
      recordInvoiceVersion(inv, user, 'Audit checks executed');
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: 'RUN_AUDIT_CHECKS',
        entityId: inv.id,
        summary: `Ran fraud & audit checks on ${inv.invoiceNumber}: ${inv.riskLevel} (${inv.riskScore})`
      });
      return inv;
    }

    if (action === 'assign') {
      const assignee = payload.assignee || user.name;
      inv.assignee = assignee;
      if (inv.status === STATUSES.RECEIVED || inv.status === STATUSES.PENDING_VERIFICATION) {
        inv.status = STATUSES.UNDER_REVIEW;
      }
      addTimelineEvent(inv, `Assigned to auditor ${assignee}`, user, payload.note || '');
      recordInvoiceVersion(inv, user, `Assigned to ${assignee}`);
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: 'ASSIGN_INVOICE',
        entityId: inv.id,
        summary: `Assigned ${inv.invoiceNumber} to ${assignee}`
      });
      return inv;
    }

    if (action === 'verify_callback') {
      inv.callbackVerified = true;
      inv.callbackNotes = payload.note || `Verified by phone callback by ${user.name}`;
      inv.callbackVerifiedBy = user.id;
      const auditResult = runAuditChecks(inv, state);
      inv.checklist = auditResult.checklist;
      inv.riskScore = auditResult.riskScore;
      inv.riskLevel = auditResult.riskLevel;
      inv.riskReasons = auditResult.riskReasons;
      addTimelineEvent(inv, 'Verified by phone / callback', user, inv.callbackNotes);
      recordInvoiceVersion(inv, user, 'Phone callback verification');
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: 'VERIFY_CALLBACK',
        entityId: inv.id,
        summary: `Phone callback verified for ${inv.invoiceNumber}: ${inv.callbackNotes}`
      });
      return inv;
    }

    if (action === 'flag') {
      inv.status = STATUSES.FLAGGED;
      if (payload.reason && !inv.riskReasons.includes(payload.reason)) {
        inv.riskReasons.push(payload.reason);
      }
      inv.riskLevel = 'high';
      inv.riskScore = Math.max(inv.riskScore || 0, 75);
      addTimelineEvent(inv, 'Flagged as suspicious', user, payload.reason || '');
      recordInvoiceVersion(inv, user, 'Flagged as suspicious');
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: 'FLAG_INVOICE',
        entityId: inv.id,
        summary: `Flagged ${inv.invoiceNumber} as suspicious: ${payload.reason || 'Fraud suspicion'}`
      });
      return inv;
    }

    if (action === 'reject') {
      inv.status = STATUSES.REJECTED;
      inv.rejectedBy = user.id;
      inv.rejectionReason = payload.reason || 'Confirmed fraud / rejected';
      addTimelineEvent(inv, 'Rejected / Confirmed scam (blocked)', user, inv.rejectionReason);
      recordInvoiceVersion(inv, user, 'Rejected');
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: 'REJECT_INVOICE',
        entityId: inv.id,
        summary: `Rejected ${inv.invoiceNumber}: ${inv.rejectionReason}`
      });
      return inv;
    }

    if (action === 'hold' || action === 'request_info') {
      inv.status = STATUSES.ON_HOLD;
      inv.holdReason =
        payload.reason ||
        (action === 'request_info' ? 'Requested clarification from supplier' : 'Placed on hold');
      addTimelineEvent(
        inv,
        action === 'request_info' ? 'Requested information from supplier' : 'Placed on hold / disputed',
        user,
        inv.holdReason
      );
      recordInvoiceVersion(inv, user, inv.holdReason);
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: action === 'request_info' ? 'REQUEST_SUPPLIER_INFO' : 'HOLD_INVOICE',
        entityId: inv.id,
        summary: `${inv.invoiceNumber}: ${inv.holdReason}`
      });
      return inv;
    }

    if (action === 'release') {
      inv.status = STATUSES.UNDER_REVIEW;
      addTimelineEvent(inv, 'Released from hold back to review', user, payload.note || '');
      recordInvoiceVersion(inv, user, 'Released from hold');
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: 'RELEASE_INVOICE',
        entityId: inv.id,
        summary: `Released ${inv.invoiceNumber} from hold`
      });
      return inv;
    }

    if (action === 'escalate') {
      const target = payload.target || 'Fraud & Risk Committee';
      inv.escalatedTo = target;
      inv.assignee = target;
      if (inv.status === STATUSES.RECEIVED || inv.status === STATUSES.PENDING_VERIFICATION) {
        inv.status = STATUSES.UNDER_REVIEW;
      }
      addTimelineEvent(inv, `Escalated to ${target}`, user, payload.note || '');
      recordInvoiceVersion(inv, user, `Escalated to ${target}`);
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: 'ESCALATE_INVOICE',
        entityId: inv.id,
        summary: `Escalated ${inv.invoiceNumber} to ${target}`
      });
      return inv;
    }

    if (action === 'approve' || action === 'approve_and_schedule') {
      if (inv.status === STATUSES.REJECTED || inv.status === STATUSES.PAID) {
        throw new Error(`Cannot approve invoice in "${inv.status}" status`);
      }
      // Block approving blacklisted/sanctioned invoices
      const supplier = (state.suppliers || []).find((s) => s.id === inv.supplierId);
      if (supplier && (supplier.status === 'blacklisted' || supplier.sanctionsHit)) {
        throw new Error(`Cannot approve invoice from blacklisted/sanctioned supplier "${supplier.name}"`);
      }
      // Ensure audit checks have run at least once
      if (!inv.checklist || inv.checklist.length === 0) {
        const res = runAuditChecks(inv, state);
        inv.checklist = res.checklist;
        inv.riskScore = res.riskScore;
        inv.riskLevel = res.riskLevel;
        inv.riskReasons = res.riskReasons;
        inv.requiredApprovalLevels = res.requiredApprovalLevels;
      }
      // Block approving duplicate invoices unless explicitly cleared
      const dupCheck = inv.checklist.find((c) => c.id === 'duplicate_detection');
      if (dupCheck && dupCheck.status === 'failed' && !payload.overrideDuplicate) {
        throw new Error(`Cannot approve duplicate invoice (${dupCheck.reason})`);
      }

      if (!Array.isArray(inv.approvals)) inv.approvals = [];
      if (inv.approvals.some((a) => a.userId === user.id)) {
        throw new Error(`User ${user.name} has already recorded an approval on this invoice`);
      }

      const amountEur = convertCurrency(inv.amount, inv.currency, 'EUR');
      const requiredLevels = inv.requiredApprovalLevels || getRequiredApprovalLevels(amountEur, state.settings);
      inv.requiredApprovalLevels = requiredLevels;

      const nextLevel = inv.approvals.length + 1;
      inv.approvals.push({
        level: nextLevel,
        userId: user.id,
        userName: user.name,
        role: user.role,
        timestamp: new Date().toISOString(),
        note: payload.note || ''
      });

      if (inv.approvals.length < requiredLevels && !payload.forceSingleStep) {
        inv.status = STATUSES.UNDER_REVIEW;
        addTimelineEvent(
          inv,
          `Level ${nextLevel}/${requiredLevels} approval granted by ${user.name}`,
          user,
          payload.note || 'Awaiting next approval level'
        );
      } else {
        inv.approvedBy = user.id;
        inv.approvedByName = user.name;
        inv.verifiedAt = inv.verifiedAt || new Date().toISOString();
        const nowStr = new Date(state.referenceDate || '2026-10-10T12:00:00Z').toISOString().slice(0, 10);
        const weekEnd = new Date(
          new Date(state.referenceDate || '2026-10-10T12:00:00Z').getTime() + 7 * 86400000
        )
          .toISOString()
          .slice(0, 10);

        if (action === 'approve_and_schedule') {
          inv.status = STATUSES.SCHEDULED;
          inv.scheduledPaymentDate = payload.scheduledDate || inv.dueDate || nowStr;
          addTimelineEvent(
            inv,
            `Verified, approved & scheduled for ${inv.scheduledPaymentDate}`,
            user,
            payload.note || ''
          );
        } else {
          inv.status =
            inv.dueDate && inv.dueDate <= weekEnd
              ? STATUSES.READY_TO_PAY
              : STATUSES.VERIFIED_APPROVED;
          addTimelineEvent(
            inv,
            `Final approval (${inv.approvals.length}/${requiredLevels}) — Status: ${STATUS_META[inv.status].label}`,
            user,
            payload.note || ''
          );
        }
      }

      recordInvoiceVersion(inv, user, `Approved (L${nextLevel}/${requiredLevels})`);
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: action === 'approve_and_schedule' ? 'APPROVE_AND_SCHEDULE' : 'APPROVE_INVOICE',
        entityId: inv.id,
        summary: `Approved ${inv.invoiceNumber} (Level ${nextLevel}/${requiredLevels}) -> ${inv.status}`
      });
      return inv;
    }

    if (action === 'comment') {
      if (!Array.isArray(inv.comments)) inv.comments = [];
      const text = String(payload.text || '').trim();
      if (!text) throw new Error('Comment text cannot be empty');
      const mentions = (text.match(/@[a-zA-Z0-9_.-]+/g) || []).map((m) => m.slice(1));
      const commentObj = {
        id: `CMT-${inv.comments.length + 1}`,
        timestamp: new Date().toISOString(),
        authorId: user.id,
        authorName: user.name,
        authorRole: user.role,
        text,
        mentions
      };
      inv.comments.push(commentObj);
      addTimelineEvent(inv, `Comment added by ${user.name}`, user, text);
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: 'ADD_COMMENT',
        entityId: inv.id,
        summary: `Comment on ${inv.invoiceNumber}: "${text.slice(0, 60)}"`
      });
      return inv;
    }

    if (action === 'attach') {
      if (!Array.isArray(inv.attachments)) inv.attachments = [];
      const attachment = {
        id: `ATT-${inv.attachments.length + 1}`,
        name: payload.name || 'verification-evidence.pdf',
        type: payload.type || 'proof_of_verification',
        uploadedBy: user.name,
        uploadedAt: new Date().toISOString(),
        sizeKb: payload.sizeKb || 142
      };
      inv.attachments.push(attachment);
      addTimelineEvent(inv, `Attached file "${attachment.name}"`, user, attachment.type);
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: 'ADD_ATTACHMENT',
        entityId: inv.id,
        summary: `Attached ${attachment.name} to ${inv.invoiceNumber}`
      });
      return inv;
    }

    throw new Error(`Unknown workflow action "${action}"`);
  }

  // ===========================================================================
  // 7. PAYMENT MANAGEMENT, BLOCKING RULES, SEPA EXPORT & FORECAST
  // ===========================================================================
  function getRemainingAmount(invoice) {
    const total = Number(invoice.amount) || 0;
    const paid = Number(invoice.paidAmount) || 0;
    const credit = Number(invoice.creditNoteAmount) || 0;
    const discount = Number(invoice.appliedDiscountAmount) || 0;
    return Math.max(0, Number((total - paid - credit - discount).toFixed(2)));
  }

  function computeEarlyDiscount(invoice, scheduledDateStr) {
    const pct = Number(invoice.earlyDiscountPercent) || 0;
    const deadline = invoice.earlyDiscountDeadline || '';
    if (pct <= 0 || !deadline || !scheduledDateStr) {
      return { eligible: false, discountAmount: 0, netAmount: getRemainingAmount(invoice) };
    }
    const remaining = getRemainingAmount(invoice);
    if (scheduledDateStr <= deadline) {
      const discountAmount = Number(((remaining * pct) / 100).toFixed(2));
      return {
        eligible: true,
        discountPercent: pct,
        discountDeadline: deadline,
        discountAmount,
        netAmount: Number((remaining - discountAmount).toFixed(2))
      };
    }
    return { eligible: false, discountAmount: 0, netAmount: remaining };
  }

  function canPayInvoice(state, invoice, actor = null) {
    const user = actor || state.currentUser;
    if (!invoice) return { allowed: false, reason: 'Invoice not found' };

    // 1. Status must be approved / ready_to_pay / scheduled
    const payableStatuses = new Set([
      STATUSES.VERIFIED_APPROVED,
      STATUSES.READY_TO_PAY,
      STATUSES.SCHEDULED
    ]);
    if (!payableStatuses.has(invoice.status)) {
      return {
        allowed: false,
        reason: `Payment blocked: Invoice status is "${STATUS_META[invoice.status]?.label || invoice.status}" (only audited & approved invoices can be paid)`
      };
    }

    // 2. Remaining balance check
    const remaining = getRemainingAmount(invoice);
    if (remaining <= 0) {
      return { allowed: false, reason: 'Payment blocked: Invoice remaining balance is 0.00' };
    }

    // 3. Supplier blacklist / sanctions check
    const supplier = (state.suppliers || []).find((s) => s.id === invoice.supplierId);
    if (supplier && (supplier.status === 'blacklisted' || supplier.sanctionsHit)) {
      return {
        allowed: false,
        reason: `Payment blocked: Supplier "${supplier.name}" is blacklisted or sanctioned`
      };
    }

    // 4. Duplicate check block
    if (Array.isArray(invoice.checklist)) {
      const dup = invoice.checklist.find((c) => c.id === 'duplicate_detection');
      if (dup && dup.status === 'failed') {
        return {
          allowed: false,
          reason: `Payment blocked: Duplicate invoice flag (${dup.reason})`
        };
      }
      const sanct = invoice.checklist.find((c) => c.id === 'sanctions_screening');
      if (sanct && sanct.status === 'failed') {
        return {
          allowed: false,
          reason: `Payment blocked: Failed sanctions screening`
        };
      }
    }

    // 5. Segregation of Duties (SoD): approver cannot pay
    const enforceSoD = state.settings ? state.settings.enforceSegregationOfDuties !== false : true;
    if (enforceSoD && user && hasActorApprovedInvoice(invoice, user)) {
      return {
        allowed: false,
        reason: `Segregation of Duties violation: ${user.name} approved this invoice and cannot also execute payment`
      };
    }

    // 6. Role permission check
    if (
      user &&
      !hasPermission(user, 'mark_paid') &&
      !hasPermission(user, 'schedule_payment') &&
      !hasPermission(user, 'create_batch')
    ) {
      return {
        allowed: false,
        reason: `Permission denied: Role "${user.role}" is not authorized to execute payments`
      };
    }

    return { allowed: true, payableAmount: remaining };
  }

  function scheduleInvoicePayment(state, invoiceId, options = {}, actor = null) {
    const user = actor || state.currentUser;
    if (!hasPermission(user, 'schedule_payment')) {
      throw new Error(`Permission denied: Role "${user ? user.role : 'none'}" cannot schedule payments`);
    }
    const inv = (state.invoices || []).find((i) => i.id === invoiceId);
    const check = canPayInvoice(state, inv, user);
    if (!check.allowed) {
      throw new Error(check.reason);
    }

    const scheduledDate =
      options.useEarlyDiscount && inv.earlyDiscountDeadline
        ? inv.earlyDiscountDeadline
        : options.scheduledDate || inv.dueDate;

    const discountInfo = computeEarlyDiscount(inv, scheduledDate);
    if (options.useEarlyDiscount && discountInfo.eligible) {
      inv.appliedDiscountAmount = discountInfo.discountAmount;
    }

    inv.status = STATUSES.SCHEDULED;
    inv.scheduledPaymentDate = scheduledDate;
    inv.scheduledBy = user.id;

    addTimelineEvent(
      inv,
      `Payment scheduled for ${scheduledDate}${discountInfo.eligible ? ` (Early discount saved ${formatMoney(discountInfo.discountAmount, inv.currency)})` : ''}`,
      user
    );
    recordInvoiceVersion(inv, user, `Scheduled payment for ${scheduledDate}`);
    appendAuditLog(state, {
      actorId: user.id,
      actorName: user.name,
      actorRole: user.role,
      action: 'SCHEDULE_PAYMENT',
      entityId: inv.id,
      summary: `Scheduled payment of ${inv.invoiceNumber} for ${scheduledDate}`
    });
    return { invoice: inv, discountInfo };
  }

  function generateSepaXml(batch, invoices) {
    const createdIso = batch.createdAt || new Date().toISOString();
    const txs = invoices
      .map(
        (inv) => `      <CdtTrfTxInf>
        <PmtId><EndToEndId>${inv.id}-${inv.invoiceNumber}</EndToEndId></PmtId>
        <Amt><InstdAmt Ccy="${inv.currency}">${getRemainingAmount(inv).toFixed(2)}</InstdAmt></Amt>
        <Cdtr><Nm>${inv.supplierName.replace(/[<>&]/g, '')}</Nm></Cdtr>
        <CdtrAcct><Id><IBAN>${inv.iban}</IBAN></Id></CdtrAcct>
        <RmtInf><Ustrd>Invoice ${inv.invoiceNumber}</Ustrd></RmtInf>
      </CdtTrfTxInf>`
      )
      .join('\n');

    return `<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">
  <CstmrCdtTrfInitn>
    <GrpHdr>
      <MsgId>${batch.id}</MsgId>
      <CreDtTm>${createdIso}</CreDtTm>
      <NbOfTxs>${invoices.length}</NbOfTxs>
      <CtrlSum>${batch.totalAmountEur.toFixed(2)}</CtrlSum>
    </GrpHdr>
    <PmtInf>
      <PmtInfId>${batch.id}-PMT</PmtInfId>
      <PmtMtd>TRF</PmtMtd>
      <ReqdExctnDt>${batch.executionDate}</ReqdExctnDt>
${txs}
    </PmtInf>
  </CstmrCdtTrfInitn>
</Document>`;
  }

  function createPaymentBatch(state, invoiceIds, options = {}, actor = null) {
    const user = actor || state.currentUser;
    if (!hasPermission(user, 'create_batch')) {
      throw new Error(`Permission denied: Role "${user ? user.role : 'none'}" cannot create payment batches`);
    }
    if (!Array.isArray(invoiceIds) || invoiceIds.length === 0) {
      throw new Error('Select at least one invoice to create a payment batch');
    }

    const selected = [];
    for (const id of invoiceIds) {
      const inv = (state.invoices || []).find((i) => i.id === id);
      const check = canPayInvoice(state, inv, user);
      if (!check.allowed) {
        throw new Error(`Cannot include ${inv ? inv.invoiceNumber : id} in batch: ${check.reason}`);
      }
      selected.push(inv);
    }

    const executionDate =
      options.executionDate ||
      new Date(state.referenceDate || '2026-10-10T12:00:00Z').toISOString().slice(0, 10);
    const totalAmountEur = selected.reduce(
      (sum, inv) => sum + convertCurrency(getRemainingAmount(inv), inv.currency, 'EUR'),
      0
    );

    if (!Array.isArray(state.paymentBatches)) state.paymentBatches = [];
    const batchId = `BATCH-SEPA-${String(state.paymentBatches.length + 1).padStart(3, '0')}`;
    const batch = {
      id: batchId,
      createdAt: new Date().toISOString(),
      createdBy: user.name,
      executionDate,
      invoiceIds: selected.map((i) => i.id),
      invoiceCount: selected.length,
      totalAmountEur: Number(totalAmountEur.toFixed(2)),
      status: options.markPaidImmediately ? 'executed' : 'scheduled',
      paymentReference: `SEPA-${batchId}`
    };
    batch.sepaXml = generateSepaXml(batch, selected);

    for (const inv of selected) {
      inv.batchId = batchId;
      inv.scheduledPaymentDate = executionDate;
      if (options.markPaidImmediately) {
        const rem = getRemainingAmount(inv);
        inv.paidAmount = Number(((inv.paidAmount || 0) + rem).toFixed(2));
        inv.status = STATUSES.PAID;
        inv.paymentReference = `${batch.paymentReference}-${inv.invoiceNumber}`;
        inv.paidAt = new Date().toISOString();
        inv.paidBy = user.id;
        addTimelineEvent(inv, `Paid in batch ${batchId} (Ref: ${inv.paymentReference})`, user);
      } else {
        inv.status = STATUSES.SCHEDULED;
        addTimelineEvent(inv, `Added to SEPA payment batch ${batchId} for ${executionDate}`, user);
      }
      recordInvoiceVersion(inv, user, `Batch ${batchId}`);
    }

    state.paymentBatches.push(batch);
    appendAuditLog(state, {
      actorId: user.id,
      actorName: user.name,
      actorRole: user.role,
      action: 'CREATE_PAYMENT_BATCH',
      entityType: 'batch',
      entityId: batchId,
      summary: `Created SEPA payment batch ${batchId} (${selected.length} invoices, ${formatMoney(batch.totalAmountEur, 'EUR')})`
    });

    return batch;
  }

  function recordPaymentOrCredit(state, invoiceId, options = {}, actor = null) {
    const user = actor || state.currentUser;
    const inv = (state.invoices || []).find((i) => i.id === invoiceId);
    if (!inv) throw new Error(`Invoice ${invoiceId} not found`);

    if (options.type === 'credit_note') {
      if (!hasPermission(user, 'apply_credit_note')) {
        throw new Error('Permission denied: Cannot apply credit notes');
      }
      const creditAmt = Number(options.amount) || 0;
      const rem = getRemainingAmount(inv);
      if (creditAmt <= 0 || creditAmt > rem) {
        throw new Error(`Invalid credit note amount (${creditAmt}); remaining balance is ${rem}`);
      }
      inv.creditNoteAmount = Number(((inv.creditNoteAmount || 0) + creditAmt).toFixed(2));
      inv.creditNoteRef = options.reference || `CN-${inv.invoiceNumber}`;
      if (getRemainingAmount(inv) === 0) {
        inv.status = STATUSES.PAID;
        inv.paymentReference = inv.creditNoteRef;
      }
      addTimelineEvent(
        inv,
        `Applied credit note ${inv.creditNoteRef} (${formatMoney(creditAmt, inv.currency)})`,
        user
      );
      recordInvoiceVersion(inv, user, `Credit note ${inv.creditNoteRef}`);
      appendAuditLog(state, {
        actorId: user.id,
        actorName: user.name,
        actorRole: user.role,
        action: 'APPLY_CREDIT_NOTE',
        entityId: inv.id,
        summary: `Applied credit note ${inv.creditNoteRef} of ${formatMoney(creditAmt, inv.currency)} to ${inv.invoiceNumber}`
      });
      return inv;
    }

    // Partial or full payment execution
    const check = canPayInvoice(state, inv, user);
    if (!check.allowed) {
      throw new Error(check.reason);
    }

    const rem = getRemainingAmount(inv);
    const payAmt = options.amount !== undefined ? Number(options.amount) : rem;
    if (payAmt <= 0 || payAmt > rem) {
      throw new Error(`Payment amount (${payAmt}) must be between 0.01 and remaining balance (${rem})`);
    }

    inv.paidAmount = Number(((inv.paidAmount || 0) + payAmt).toFixed(2));
    inv.paymentReference = options.reference || `PAY-${Date.now().toString().slice(-6)}`;
    inv.reconciled = Boolean(options.reconciled);

    if (getRemainingAmount(inv) === 0) {
      inv.status = STATUSES.PAID;
      inv.paidAt = new Date().toISOString();
      inv.paidBy = user.id;
      addTimelineEvent(
        inv,
        `Paid in full (${formatMoney(payAmt, inv.currency)}) — Ref: ${inv.paymentReference}${inv.reconciled ? ' [Bank Reconciled]' : ''}`,
        user
      );
    } else {
      addTimelineEvent(
        inv,
        `Partial payment recorded (${formatMoney(payAmt, inv.currency)}); remaining: ${formatMoney(getRemainingAmount(inv), inv.currency)}`,
        user
      );
    }

    recordInvoiceVersion(inv, user, `Payment ${inv.paymentReference}`);
    appendAuditLog(state, {
      actorId: user.id,
      actorName: user.name,
      actorRole: user.role,
      action: getRemainingAmount(inv) === 0 ? 'MARK_PAID' : 'PARTIAL_PAYMENT',
      entityId: inv.id,
      summary: `Paid ${formatMoney(payAmt, inv.currency)} on ${inv.invoiceNumber} (Ref: ${inv.paymentReference})`
    });
    return inv;
  }

  function computeCashFlowForecast(state, nowInput) {
    const now = nowInput ? new Date(nowInput) : new Date(state.referenceDate || '2026-10-10T12:00:00Z');
    const baseCurrency = (state.settings && state.settings.baseCurrency) || 'EUR';
    const todayStr = now.toISOString().slice(0, 10);
    const day7Str = new Date(now.getTime() + 7 * 86400000).toISOString().slice(0, 10);
    const day30Str = new Date(now.getTime() + 30 * 86400000).toISOString().slice(0, 10);

    const forecast = {
      baseCurrency,
      overdue: 0,
      dueToday: 0,
      next7Days: 0,
      next30Days: 0,
      beyond30Days: 0,
      potentialEarlyDiscountSavings: 0
    };

    for (const inv of state.invoices || []) {
      if (inv.status === STATUSES.PAID || inv.status === STATUSES.REJECTED || inv.status === STATUSES.FLAGGED) {
        continue;
      }
      const remEur = convertCurrency(getRemainingAmount(inv), inv.currency, baseCurrency);
      const targetDate = inv.scheduledPaymentDate || inv.dueDate || todayStr;
      if (targetDate < todayStr) {
        forecast.overdue = Number((forecast.overdue + remEur).toFixed(2));
      } else if (targetDate === todayStr) {
        forecast.dueToday = Number((forecast.dueToday + remEur).toFixed(2));
      } else if (targetDate <= day7Str) {
        forecast.next7Days = Number((forecast.next7Days + remEur).toFixed(2));
      } else if (targetDate <= day30Str) {
        forecast.next30Days = Number((forecast.next30Days + remEur).toFixed(2));
      } else {
        forecast.beyond30Days = Number((forecast.beyond30Days + remEur).toFixed(2));
      }

      const disc = computeEarlyDiscount(inv, todayStr);
      if (disc.eligible) {
        const discBase = convertCurrency(disc.discountAmount, inv.currency, baseCurrency);
        forecast.potentialEarlyDiscountSavings = Number(
          (forecast.potentialEarlyDiscountSavings + discBase).toFixed(2)
        );
      }
    }
    return forecast;
  }

  // ===========================================================================
  // 8. SUPPLIER VIEW & WHITELIST / BLACKLIST MANAGEMENT
  // ===========================================================================
  function setSupplierStatus(state, supplierId, newStatus, actor = null, reason = '') {
    const user = actor || state.currentUser;
    if (!hasPermission(user, 'manage_suppliers') && user.role !== ROLES.AUDITOR && user.role !== ROLES.APPROVER) {
      throw new Error('Permission denied: Cannot modify supplier verification status');
    }
    const sup = (state.suppliers || []).find((s) => s.id === supplierId);
    if (!sup) throw new Error(`Supplier ${supplierId} not found`);

    const prevStatus = sup.status;
    sup.status = newStatus;
    if (newStatus === 'blacklisted') {
      sup.riskRating = 'high';
    } else if (newStatus === 'verified') {
      sup.riskRating = 'low';
    }

    appendAuditLog(state, {
      actorId: user.id,
      actorName: user.name,
      actorRole: user.role,
      action: 'UPDATE_SUPPLIER_STATUS',
      entityType: 'supplier',
      entityId: sup.id,
      summary: `Changed supplier ${sup.name} status from "${prevStatus}" to "${newStatus}" ${reason ? `(${reason})` : ''}`
    });
    return sup;
  }

  function updateSupplierBankDetails(state, supplierId, newIban, actor = null, verified = false) {
    const user = actor || state.currentUser;
    const sup = (state.suppliers || []).find((s) => s.id === supplierId);
    if (!sup) throw new Error(`Supplier ${supplierId} not found`);
    if (!Array.isArray(sup.bankChangeLog)) sup.bankChangeLog = [];

    const oldIban = sup.iban;
    sup.bankChangeLog.unshift({
      changedAt: new Date().toISOString().slice(0, 10),
      previousIban: oldIban,
      newIban,
      changedBy: user ? user.name : 'Supplier Portal',
      verified
    });
    sup.iban = newIban;
    sup.bankChangedRecently = !verified;

    appendAuditLog(state, {
      actorId: user ? user.id : 'system',
      actorName: user ? user.name : 'System',
      actorRole: user ? user.role : 'system',
      action: 'SUPPLIER_BANK_CHANGE',
      entityType: 'supplier',
      entityId: sup.id,
      summary: `Bank IBAN changed for ${sup.name}: ${oldIban} -> ${newIban}`
    });
    return sup;
  }

  // ===========================================================================
  // 9. ALERTS, SLA BREACHES & NOTIFICATIONS
  // ===========================================================================
  function computeAlerts(state, nowInput) {
    const now = nowInput ? new Date(nowInput) : new Date(state.referenceDate || '2026-10-10T12:00:00Z');
    const todayStr = now.toISOString().slice(0, 10);
    const soonStr = new Date(now.getTime() + 3 * 86400000).toISOString().slice(0, 10);
    const slaHours = (state.settings && Number(state.settings.slaHours)) || 48;

    const alerts = [];

    for (const inv of state.invoices || []) {
      // 1. High-risk / flagged invoice
      if (inv.riskLevel === 'high' || inv.status === STATUSES.FLAGGED) {
        alerts.push({
          id: `ALT-RISK-${inv.id}`,
          type: 'high_risk',
          severity: 'critical',
          invoiceId: inv.id,
          title: `High-risk invoice ${inv.invoiceNumber} (${inv.supplierName})`,
          message: (inv.riskReasons && inv.riskReasons.join('; ')) || `Risk score ${inv.riskScore}/100`
        });
      }

      // 2. SLA breach (stuck in verification beyond slaHours)
      if (
        inv.status === STATUSES.RECEIVED ||
        inv.status === STATUSES.PENDING_VERIFICATION ||
        inv.status === STATUSES.UNDER_REVIEW
      ) {
        const recTime = new Date(inv.receivedAt || inv.issueDate).getTime();
        const hoursInQueue = Math.round((now.getTime() - recTime) / 3600000);
        if (hoursInQueue > slaHours) {
          alerts.push({
            id: `ALT-SLA-${inv.id}`,
            type: 'sla_breach',
            severity: 'warning',
            invoiceId: inv.id,
            title: `SLA Breach: ${inv.invoiceNumber} in verification for ${hoursInQueue}h (SLA: ${slaHours}h)`,
            message: `Assigned to: ${inv.assignee || 'Unassigned'}`
          });
        }
      }

      // 3. Overdue or upcoming due date
      if (inv.status !== STATUSES.PAID && inv.status !== STATUSES.REJECTED && inv.dueDate) {
        if (inv.dueDate < todayStr) {
          alerts.push({
            id: `ALT-LATE-${inv.id}`,
            type: 'overdue',
            severity: 'high',
            invoiceId: inv.id,
            title: `Overdue payment: ${inv.invoiceNumber} was due on ${inv.dueDate}`,
            message: `${inv.supplierName} — ${formatMoney(inv.amount, inv.currency)}`
          });
        } else if (inv.dueDate <= soonStr) {
          alerts.push({
            id: `ALT-DUE-${inv.id}`,
            type: 'upcoming_due',
            severity: 'info',
            invoiceId: inv.id,
            title: `Upcoming due date: ${inv.invoiceNumber} due ${inv.dueDate}`,
            message: `${inv.supplierName} — ${formatMoney(inv.amount, inv.currency)}`
          });
        }
      }

      // 4. Duplicate invoice detected
      if (
        Array.isArray(inv.checklist) &&
        inv.checklist.some((c) => c.id === 'duplicate_detection' && c.status === 'failed')
      ) {
        alerts.push({
          id: `ALT-DUP-${inv.id}`,
          type: 'duplicate',
          severity: 'critical',
          invoiceId: inv.id,
          title: `Duplicate invoice detected: ${inv.invoiceNumber}`,
          message: inv.checklist.find((c) => c.id === 'duplicate_detection').reason
        });
      }
    }

    // 5. Supplier bank detail change alerts
    for (const sup of state.suppliers || []) {
      if (sup.bankChangedRecently) {
        alerts.push({
          id: `ALT-BANK-${sup.id}`,
          type: 'bank_change',
          severity: 'high',
          supplierId: sup.id,
          title: `Bank detail change detected for ${sup.name}`,
          message: `New IBAN ${sup.iban} requires out-of-band phone callback verification`
        });
      }
    }

    return alerts;
  }

  // ===========================================================================
  // 12. REPORTING & ANALYTICS
  // ===========================================================================
  function computeAnalytics(state, nowInput) {
    const kpis = computeKPIs(state, nowInput);
    const invoices = state.invoices || [];

    // Turnaround time by auditor
    const auditorMap = new Map();
    let paidOnTime = 0;
    let paidLate = 0;

    for (const inv of invoices) {
      const auditor = inv.assignee || 'Unassigned';
      if (!auditorMap.has(auditor)) {
        auditorMap.set(auditor, { auditor, count: 0, verifiedCount: 0, totalHours: 0, avgHours: 0 });
      }
      const aStat = auditorMap.get(auditor);
      aStat.count += 1;
      if (inv.receivedAt && inv.verifiedAt) {
        const h = Math.max(0, (new Date(inv.verifiedAt).getTime() - new Date(inv.receivedAt).getTime()) / 3600000);
        aStat.verifiedCount += 1;
        aStat.totalHours += h;
        aStat.avgHours = Number((aStat.totalHours / aStat.verifiedCount).toFixed(1));
      }

      if (inv.status === STATUSES.PAID) {
        const paidDate = (inv.paidAt || inv.scheduledPaymentDate || inv.dueDate).slice(0, 10);
        if (paidDate <= inv.dueDate) {
          paidOnTime += 1;
        } else {
          paidLate += 1;
        }
      }
    }

    const totalPaid = paidOnTime + paidLate;
    return {
      fraudCaughtCount: kpis.flagged.count + kpis.flagged.rejectedCount,
      moneySavedEur: kpis.flagged.moneySaved,
      turnaroundByAuditor: Array.from(auditorMap.values()),
      paymentPerformance: {
        paidOnTime,
        paidLate,
        onTimeRatePercent: totalPaid > 0 ? Math.round((paidOnTime / totalPaid) * 100) : 100
      },
      topSuppliersByVolume: kpis.trends.bySupplier.slice(0, 5),
      topSuppliersByRisk: kpis.trends.bySupplier
        .slice()
        .sort((a, b) => b.maxRiskScore - a.maxRiskScore)
        .slice(0, 5)
    };
  }

  // ===========================================================================
  // 13. INTEGRATIONS, OCR EXTRACTION & INGESTION
  // ===========================================================================
  function parseOcrText(rawText) {
    const text = String(rawText || '');
    const pick = (regex, fallback = '') => {
      const m = text.match(regex);
      return m ? m[1].trim() : fallback;
    };

    const invoiceNumber = pick(/(?:Invoice\s*(?:No|Number|#)?\s*[:=-]?\s*)([A-Z0-9-]{3,30})/i, `INV-${Date.now().toString().slice(-4)}`);
    const supplierName = pick(/(?:Supplier|Vendor|From)\s*[:=-]?\s*([^\n\r]+)/i, 'Unknown Vendor Ltd');
    const vatNumber = pick(/(?:VAT|Tax\s*ID)\s*[:=-]?\s*([A-Z]{2}[A-Z0-9]{6,14})/i, 'FR12345678901');
    const iban = pick(/(?:IBAN)\s*[:=-]?\s*([A-Z]{2}[0-9A-Z\s]{12,32})/i, 'FR7630006000011234567890189').replace(/\s+/g, '');
    const amountRaw = pick(/(?:Total|Amount\s*Due|Amount)\s*[:=-]?\s*[$€£]?\s*([0-9]+(?:[.,][0-9]{1,2})?)/i, '1250.00');
    const amount = Number(amountRaw.replace(',', '.')) || 1250;
    const currency = pick(/(?:Currency)\s*[:=-]?\s*(EUR|USD|GBP|CHF)/i, text.includes('$') ? 'USD' : text.includes('£') ? 'GBP' : 'EUR');
    const poNumber = pick(/(?:PO|Purchase\s*Order)\s*[:=-]?\s*([A-Z0-9-]{3,25})/i, '');
    const issueDate = pick(/(?:Issue\s*Date|Date)\s*[:=-]?\s*(\d{4}-\d{2}-\d{2})/i, '2026-10-10');
    const dueDate = pick(/(?:Due\s*Date|Due)\s*[:=-]?\s*(\d{4}-\d{2}-\d{2})/i, '2026-10-25');
    const senderEmail = pick(/(?:Email|From\s*Email)\s*[:=-]?\s*([^\s@\n]+@[^\s@\n]+)/i, '');

    return {
      invoiceNumber,
      supplierName,
      vatNumber,
      iban,
      amount,
      currency,
      poNumber,
      issueDate,
      dueDate,
      senderEmail
    };
  }

  function ingestInvoice(state, input = {}, source = 'upload', actor = null) {
    const user = actor || state.currentUser || { id: 'system', name: 'Ingestion Pipeline', role: 'admin' };
    const parsed = input.rawOcrText ? { ...parseOcrText(input.rawOcrText), ...input } : input;

    const existingSupplier = (state.suppliers || []).find(
      (s) =>
        s.id === parsed.supplierId ||
        s.name.toLowerCase() === String(parsed.supplierName || '').toLowerCase()
    );

    const newId = `INV-${String((state.invoices || []).length + 1001)}`;
    const nowIso = new Date(state.referenceDate || new Date().toISOString()).toISOString();

    const invoice = {
      id: newId,
      invoiceNumber: parsed.invoiceNumber || newId,
      supplierId: existingSupplier ? existingSupplier.id : parsed.supplierId || 'SUP-UNKNOWN',
      supplierName: existingSupplier ? existingSupplier.name : parsed.supplierName || 'Unknown Vendor',
      vatNumber: parsed.vatNumber || (existingSupplier ? existingSupplier.vatNumber : ''),
      iban: parsed.iban || (existingSupplier ? existingSupplier.iban : ''),
      amount: Number(parsed.amount) || 0,
      currency: parsed.currency || 'EUR',
      issueDate: parsed.issueDate || nowIso.slice(0, 10),
      dueDate: parsed.dueDate || nowIso.slice(0, 10),
      receivedAt: parsed.receivedAt || nowIso,
      status: STATUSES.RECEIVED,
      department: parsed.department || 'Operations',
      entity: parsed.entity || 'Vaultgard EU',
      assignee: parsed.assignee || 'Unassigned',
      paymentMethod: parsed.paymentMethod || 'SEPA',
      poNumber: parsed.poNumber || '',
      poAmount: parsed.poAmount !== undefined ? Number(parsed.poAmount) : Number(parsed.amount) || 0,
      grnNumber: parsed.grnNumber || (parsed.poNumber ? `GRN-${parsed.poNumber}` : ''),
      grnStatus: parsed.grnStatus || (parsed.poNumber ? 'matched' : 'missing'),
      senderEmail: parsed.senderEmail || '',
      ingestionSource: source,
      documentMeta: parsed.documentMeta || { tampered: false, fontMismatch: false, modifiedAfterIssue: false },
      checklist: [],
      riskScore: 0,
      riskLevel: 'low',
      riskReasons: [],
      approvals: [],
      comments: [],
      attachments: [],
      timeline: [],
      versionHistory: []
    };

    addTimelineEvent(invoice, `Invoice ingested via ${source}`, user, `Source: ${source}`);

    if (parsed.autoRunChecks !== false) {
      const checkRes = runAuditChecks(invoice, state);
      invoice.checklist = checkRes.checklist;
      invoice.riskScore = checkRes.riskScore;
      invoice.riskLevel = checkRes.riskLevel;
      invoice.riskReasons = checkRes.riskReasons;
      invoice.requiredApprovalLevels = checkRes.requiredApprovalLevels;
      invoice.status =
        checkRes.riskLevel === 'high' ? STATUSES.FLAGGED : STATUSES.PENDING_VERIFICATION;
      addTimelineEvent(
        invoice,
        `Initial audit checks completed (Risk: ${invoice.riskLevel.toUpperCase()} / ${invoice.riskScore})`,
        user,
        invoice.riskReasons.join('; ') || 'All checks passed'
      );
    }

    recordInvoiceVersion(invoice, user, `Ingested via ${source}`);
    state.invoices.unshift(invoice);

    appendAuditLog(state, {
      actorId: user.id,
      actorName: user.name,
      actorRole: user.role,
      action: 'INGEST_INVOICE',
      entityId: invoice.id,
      summary: `Ingested invoice ${invoice.invoiceNumber} from ${invoice.supplierName} (${formatMoney(invoice.amount, invoice.currency)}) via ${source}`
    });

    return invoice;
  }

  function maskPII(value, enabled = false) {
    const s = String(value || '');
    if (!enabled || !s) return s;
    if (s.includes('@')) {
      const [u, d] = s.split('@');
      return `${u.slice(0, 2)}***@${d}`;
    }
    if (s.length > 8) {
      return `${s.slice(0, 4)}••••••••${s.slice(-4)}`;
    }
    return '••••';
  }

  // ===========================================================================
  // INITIAL SEED STATE (Covers all 10 statuses & fraud scenarios)
  // ===========================================================================
  function createInitialState() {
    const state = {
      referenceDate: '2026-10-10T12:00:00Z',
      currentUser: {
        id: 'USR-APPROVER-1',
        name: 'Claire Dubois',
        role: ROLES.APPROVER,
        departments: ['ALL'],
        entities: ['ALL'],
        maxApprovalAmount: 250000
      },
      users: [
        { id: 'USR-VIEWER-1', name: 'Marc Laurent', role: ROLES.VIEWER, departments: ['ALL'], entities: ['ALL'], maxApprovalAmount: 0 },
        { id: 'USR-AUDITOR-1', name: 'Sophie Mercier', role: ROLES.AUDITOR, departments: ['ALL'], entities: ['ALL'], maxApprovalAmount: 0 },
        { id: 'USR-APPROVER-1', name: 'Claire Dubois', role: ROLES.APPROVER, departments: ['ALL'], entities: ['ALL'], maxApprovalAmount: 250000 },
        { id: 'USR-APPROVER-2', name: 'Henri Vance (CFO)', role: ROLES.APPROVER, departments: ['ALL'], entities: ['ALL'], maxApprovalAmount: 1000000 },
        { id: 'USR-PAYER-1', name: 'Thomas Bernard', role: ROLES.PAYER, departments: ['ALL'], entities: ['ALL'], maxApprovalAmount: 0 },
        { id: 'USR-ADMIN-1', name: 'Elena Rostova', role: ROLES.ADMIN, departments: ['ALL'], entities: ['ALL'], maxApprovalAmount: 1000000 }
      ],
      settings: {
        baseCurrency: 'EUR',
        language: 'en',
        darkMode: true,
        enforceSegregationOfDuties: true,
        flagRoundNumbers: true,
        slaHours: 48,
        anomalyMultiplier: 2.5,
        highRiskThreshold: 65,
        mediumRiskThreshold: 30,
        approvalThresholds: {
          level1: 10000,
          level2: 50000
        },
        gdprRetentionDays: 365 * 7,
        gdprMaskPii: false,
        notifications: {
          email: true,
          inApp: true,
          slack: true,
          teams: false,
          digestFrequency: 'daily'
        }
      },
      savedViews: [
        { id: 'all', name: 'All Invoices', query: {} },
        { id: 'ready_this_week', name: 'Ready to pay this week', query: { preset: 'ready_this_week' } },
        { id: 'high_risk', name: 'Flagged & High Risk', query: { preset: 'high_risk' } },
        { id: 'pending_audit', name: 'Audit Queue', query: { preset: 'pending_audit' } },
        { id: 'overdue', name: 'Overdue Invoices', query: { preset: 'overdue' } }
      ],
      integrations: [
        { id: 'INT-SAP', name: 'SAP S/4HANA ERP', category: 'ERP', status: 'connected', lastSync: '2026-10-10T11:45:00Z' },
        { id: 'INT-NETSUITE', name: 'Oracle NetSuite', category: 'ERP', status: 'connected', lastSync: '2026-10-10T11:30:00Z' },
        { id: 'INT-QBO', name: 'QuickBooks Online', category: 'Accounting', status: 'standby', lastSync: '2026-10-09T18:00:00Z' },
        { id: 'INT-BNPP', name: 'BNP Paribas SEPA Gateway', category: 'Bank', status: 'connected', lastSync: '2026-10-10T11:55:00Z' },
        { id: 'INT-VIES', name: 'EU VIES VAT & Registry Lookup', category: 'Registry', status: 'connected', lastSync: '2026-10-10T11:59:00Z' }
      ],
      suppliers: [
        {
          id: 'SUP-01',
          name: 'CloudScale Infrastructure GmbH',
          status: 'verified',
          vatNumber: 'DE812345678',
          regNumber: 'HRB-99201',
          officialDomain: 'cloudscale.de',
          iban: 'DE89370400440532013000',
          bankChangedRecently: false,
          avgInvoiceAmount: 14000,
          riskRating: 'low',
          sanctionsHit: false,
          bankChangeLog: [
            { changedAt: '2025-02-14', previousIban: 'DE12370400440532011111', newIban: 'DE89370400440532013000', changedBy: 'Onboarding', verified: true }
          ]
        },
        {
          id: 'SUP-02',
          name: 'Apex Precision Logistics SAS',
          status: 'verified',
          vatNumber: 'FR44501928374',
          regNumber: 'SIREN-501928374',
          officialDomain: 'apex-logistics.fr',
          iban: 'FR7630006000011234567890189',
          bankChangedRecently: true,
          avgInvoiceAmount: 6500,
          riskRating: 'medium',
          sanctionsHit: false,
          bankChangeLog: [
            { changedAt: '2026-10-08', previousIban: 'FR7630004000059876543210999', newIban: 'FR7630006000011234567890189', changedBy: 'Email Request', verified: false }
          ]
        },
        {
          id: 'SUP-03',
          name: 'Lumiere Office Supplies Ltd',
          status: 'verified',
          vatNumber: 'GB980765432',
          regNumber: 'UK-08123456',
          officialDomain: 'lumiere-office.co.uk',
          iban: 'GB29NWBK60161331926819',
          bankChangedRecently: false,
          avgInvoiceAmount: 2200,
          riskRating: 'low',
          sanctionsHit: false,
          bankChangeLog: []
        },
        {
          id: 'SUP-04',
          name: 'Nordic CyberSec Solutions AB',
          status: 'verified',
          vatNumber: 'SE556677889901',
          regNumber: 'SE-556677',
          officialDomain: 'nordic-cyber.se',
          iban: 'SE4550000000058398257466',
          bankChangedRecently: false,
          avgInvoiceAmount: 28000,
          riskRating: 'low',
          sanctionsHit: false,
          bankChangeLog: []
        },
        {
          id: 'SUP-05',
          name: 'Global Shadow Consulting LLC',
          status: 'blacklisted',
          vatNumber: 'CY10293847L',
          regNumber: 'CY-00912',
          officialDomain: 'shadow-consult.cy',
          iban: 'CY17002001280000001200527600',
          bankChangedRecently: true,
          avgInvoiceAmount: 4000,
          riskRating: 'high',
          sanctionsHit: true,
          bankChangeLog: [
            { changedAt: '2026-10-01', previousIban: 'DE000000000000', newIban: 'CY17002001280000001200527600', changedBy: 'Unverified PDF', verified: false }
          ]
        }
      ],
      invoices: [],
      paymentBatches: [],
      auditLog: []
    };

    const seedInvoices = [
      // 1. RECEIVED / NEW
      {
        id: 'INV-1001',
        invoiceNumber: 'CS-2026-091',
        supplierId: 'SUP-01',
        supplierName: 'CloudScale Infrastructure GmbH',
        vatNumber: 'DE812345678',
        iban: 'DE89370400440532013000',
        amount: 8420.5,
        currency: 'EUR',
        issueDate: '2026-10-09',
        dueDate: '2026-10-24',
        receivedAt: '2026-10-10T09:30:00Z',
        status: STATUSES.RECEIVED,
        department: 'Engineering',
        entity: 'Vaultgard EU',
        assignee: 'Unassigned',
        paymentMethod: 'SEPA',
        poNumber: 'PO-2026-440',
        poAmount: 8420.5,
        grnNumber: 'GRN-440',
        grnStatus: 'matched',
        senderEmail: 'billing@cloudscale.de',
        documentMeta: { tampered: false }
      },
      // 2. PENDING VERIFICATION (SLA breach > 48h)
      {
        id: 'INV-1002',
        invoiceNumber: 'LUM-8821',
        supplierId: 'SUP-03',
        supplierName: 'Lumiere Office Supplies Ltd',
        vatNumber: 'GB980765432',
        iban: 'GB29NWBK60161331926819',
        amount: 1850.0,
        currency: 'GBP',
        issueDate: '2026-10-04',
        dueDate: '2026-10-18',
        receivedAt: '2026-10-05T08:00:00Z',
        status: STATUSES.PENDING_VERIFICATION,
        department: 'Operations',
        entity: 'Vaultgard UK',
        assignee: 'Sophie Mercier',
        paymentMethod: 'Wire',
        poNumber: 'PO-2026-399',
        poAmount: 1850.0,
        grnNumber: 'GRN-399',
        grnStatus: 'matched',
        senderEmail: 'accounts@lumiere-office.co.uk',
        documentMeta: { tampered: false }
      },
      // 3. UNDER REVIEW (Multi-level > 10k, awaiting approval)
      {
        id: 'INV-1003',
        invoiceNumber: 'NCS-2026-404',
        supplierId: 'SUP-04',
        supplierName: 'Nordic CyberSec Solutions AB',
        vatNumber: 'SE556677889901',
        iban: 'SE4550000000058398257466',
        amount: 24500.0,
        currency: 'EUR',
        issueDate: '2026-10-06',
        dueDate: '2026-10-20',
        receivedAt: '2026-10-06T10:00:00Z',
        status: STATUSES.UNDER_REVIEW,
        department: 'Security',
        entity: 'Vaultgard EU',
        assignee: 'Sophie Mercier',
        paymentMethod: 'SEPA',
        poNumber: 'PO-2026-412',
        poAmount: 24500.0,
        grnNumber: 'GRN-412',
        grnStatus: 'matched',
        senderEmail: 'finance@nordic-cyber.se',
        documentMeta: { tampered: false }
      },
      // 4. FLAGGED / SUSPICIOUS (Lookalike domain + IBAN mismatch + just under 10k threshold)
      {
        id: 'INV-1004',
        invoiceNumber: 'APX-9910',
        supplierId: 'SUP-02',
        supplierName: 'Apex Precision Logistics SAS',
        vatNumber: 'FR44501928374',
        iban: 'FR7611112222333344445555666',
        amount: 9850.0,
        currency: 'EUR',
        issueDate: '2026-10-07',
        dueDate: '2026-10-14',
        receivedAt: '2026-10-07T14:20:00Z',
        status: STATUSES.FLAGGED,
        department: 'Logistics',
        entity: 'Vaultgard EU',
        assignee: 'Sophie Mercier',
        paymentMethod: 'SEPA',
        poNumber: 'PO-2026-415',
        poAmount: 6200.0,
        grnNumber: '',
        grnStatus: 'mismatch',
        senderEmail: 'billing@apex-1ogistics.fr',
        documentMeta: { tampered: true, fontMismatch: true }
      },
      // 5. REJECTED / CONFIRMED SCAM (Blacklisted + Sanctions hit + Spoofed email)
      {
        id: 'INV-1005',
        invoiceNumber: 'GSC-666',
        supplierId: 'SUP-05',
        supplierName: 'Global Shadow Consulting LLC',
        vatNumber: 'CY10293847L',
        iban: 'CY17002001280000001200527600',
        amount: 49500.0,
        currency: 'EUR',
        issueDate: '2026-09-28',
        dueDate: '2026-10-05',
        receivedAt: '2026-09-28T16:00:00Z',
        status: STATUSES.REJECTED,
        department: 'Finance',
        entity: 'Vaultgard EU',
        assignee: 'Elena Rostova',
        paymentMethod: 'Wire',
        poNumber: '',
        poAmount: 0,
        grnNumber: '',
        grnStatus: 'missing',
        senderEmail: 'urgent@shadow-consu1t.cy',
        documentMeta: { tampered: true, modifiedAfterIssue: true }
      },
      // 6. VERIFIED & APPROVED (Clean, due later this month)
      {
        id: 'INV-1006',
        invoiceNumber: 'CS-2026-085',
        supplierId: 'SUP-01',
        supplierName: 'CloudScale Infrastructure GmbH',
        vatNumber: 'DE812345678',
        iban: 'DE89370400440532013000',
        amount: 9200.0,
        currency: 'EUR',
        issueDate: '2026-09-25',
        dueDate: '2026-10-25',
        receivedAt: '2026-09-25T09:00:00Z',
        verifiedAt: '2026-09-26T15:00:00Z',
        approvedBy: 'USR-APPROVER-2',
        approvedByName: 'Henri Vance (CFO)',
        approvals: [
          { level: 1, userId: 'USR-APPROVER-2', userName: 'Henri Vance (CFO)', role: 'approver', timestamp: '2026-09-26T15:00:00Z', note: 'Verified against SLA contract' }
        ],
        status: STATUSES.VERIFIED_APPROVED,
        department: 'Engineering',
        entity: 'Vaultgard EU',
        assignee: 'Sophie Mercier',
        paymentMethod: 'SEPA',
        poNumber: 'PO-2026-380',
        poAmount: 9200.0,
        grnNumber: 'GRN-380',
        grnStatus: 'matched',
        earlyDiscountPercent: 2.0,
        earlyDiscountDeadline: '2026-10-15',
        senderEmail: 'billing@cloudscale.de',
        documentMeta: { tampered: false }
      },
      // 7. READY TO PAY (Approved, due within this week / overdue check)
      {
        id: 'INV-1007',
        invoiceNumber: 'NCS-2026-390',
        supplierId: 'SUP-04',
        supplierName: 'Nordic CyberSec Solutions AB',
        vatNumber: 'SE556677889901',
        iban: 'SE4550000000058398257466',
        amount: 7650.0,
        currency: 'EUR',
        issueDate: '2026-09-12',
        dueDate: '2026-10-12',
        receivedAt: '2026-09-12T11:00:00Z',
        verifiedAt: '2026-09-13T17:00:00Z',
        approvedBy: 'USR-APPROVER-1',
        approvedByName: 'Claire Dubois',
        approvals: [
          { level: 1, userId: 'USR-APPROVER-1', userName: 'Claire Dubois', role: 'approver', timestamp: '2026-09-13T17:00:00Z', note: 'Pen-test milestone verified' }
        ],
        status: STATUSES.READY_TO_PAY,
        department: 'Security',
        entity: 'Vaultgard EU',
        assignee: 'Sophie Mercier',
        paymentMethod: 'SEPA',
        poNumber: 'PO-2026-350',
        poAmount: 7650.0,
        grnNumber: 'GRN-350',
        grnStatus: 'matched',
        earlyDiscountPercent: 1.5,
        earlyDiscountDeadline: '2026-10-11',
        senderEmail: 'finance@nordic-cyber.se',
        documentMeta: { tampered: false }
      },
      // 8. SCHEDULED (Payment date set)
      {
        id: 'INV-1008',
        invoiceNumber: 'LUM-8790',
        supplierId: 'SUP-03',
        supplierName: 'Lumiere Office Supplies Ltd',
        vatNumber: 'GB980765432',
        iban: 'GB29NWBK60161331926819',
        amount: 1420.0,
        currency: 'GBP',
        issueDate: '2026-09-10',
        dueDate: '2026-10-10',
        scheduledPaymentDate: '2026-10-10',
        receivedAt: '2026-09-10T10:00:00Z',
        verifiedAt: '2026-09-11T10:00:00Z',
        approvedBy: 'USR-APPROVER-2',
        approvedByName: 'Henri Vance (CFO)',
        approvals: [
          { level: 1, userId: 'USR-APPROVER-2', userName: 'Henri Vance (CFO)', role: 'approver', timestamp: '2026-09-11T10:00:00Z', note: 'Approved' }
        ],
        status: STATUSES.SCHEDULED,
        department: 'Operations',
        entity: 'Vaultgard UK',
        assignee: 'Sophie Mercier',
        paymentMethod: 'SEPA',
        poNumber: 'PO-2026-340',
        poAmount: 1420.0,
        grnNumber: 'GRN-340',
        grnStatus: 'matched',
        senderEmail: 'accounts@lumiere-office.co.uk',
        documentMeta: { tampered: false }
      },
      // 9. PAID (With payment reference & bank reconciliation)
      {
        id: 'INV-1009',
        invoiceNumber: 'CS-2026-070',
        supplierId: 'SUP-01',
        supplierName: 'CloudScale Infrastructure GmbH',
        vatNumber: 'DE812345678',
        iban: 'DE89370400440532013000',
        amount: 8100.0,
        paidAmount: 8100.0,
        currency: 'EUR',
        issueDate: '2026-08-15',
        dueDate: '2026-09-15',
        receivedAt: '2026-08-15T09:00:00Z',
        verifiedAt: '2026-08-16T09:00:00Z',
        paidAt: '2026-09-14T14:00:00Z',
        paymentReference: 'SEPA-20260914-0081',
        reconciled: true,
        approvedBy: 'USR-APPROVER-1',
        approvedByName: 'Claire Dubois',
        paidBy: 'USR-PAYER-1',
        approvals: [
          { level: 1, userId: 'USR-APPROVER-1', userName: 'Claire Dubois', role: 'approver', timestamp: '2026-08-16T09:00:00Z', note: 'Approved' }
        ],
        status: STATUSES.PAID,
        department: 'Engineering',
        entity: 'Vaultgard EU',
        assignee: 'Sophie Mercier',
        paymentMethod: 'SEPA',
        poNumber: 'PO-2026-310',
        poAmount: 8100.0,
        grnNumber: 'GRN-310',
        grnStatus: 'matched',
        senderEmail: 'billing@cloudscale.de',
        documentMeta: { tampered: false }
      },
      // 10. ON HOLD / DISPUTED (Waiting on supplier clarification, also overdue)
      {
        id: 'INV-1010',
        invoiceNumber: 'APX-9840',
        supplierId: 'SUP-02',
        supplierName: 'Apex Precision Logistics SAS',
        vatNumber: 'FR44501928374',
        iban: 'FR7630006000011234567890189',
        amount: 5400.0,
        currency: 'EUR',
        issueDate: '2026-09-01',
        dueDate: '2026-10-01',
        receivedAt: '2026-09-01T12:00:00Z',
        status: STATUSES.ON_HOLD,
        holdReason: 'Awaiting callback confirmation for recent IBAN change & delivery note sign-off',
        department: 'Logistics',
        entity: 'Vaultgard EU',
        assignee: 'Sophie Mercier',
        paymentMethod: 'SEPA',
        poNumber: 'PO-2026-322',
        poAmount: 5400.0,
        grnNumber: 'GRN-322',
        grnStatus: 'pending',
        senderEmail: 'billing@apex-logistics.fr',
        documentMeta: { tampered: false }
      }
    ];

    state.invoices = seedInvoices.map((inv) => ({
      ...inv,
      paidAmount: inv.paidAmount || 0,
      creditNoteAmount: inv.creditNoteAmount || 0,
      appliedDiscountAmount: inv.appliedDiscountAmount || 0,
      approvals: inv.approvals || [],
      comments: inv.comments || [
        {
          id: 'CMT-1',
          timestamp: inv.receivedAt,
          authorId: 'USR-AUDITOR-1',
          authorName: 'Sophie Mercier',
          authorRole: 'auditor',
          text: `Automated intake completed for ${inv.invoiceNumber}. cc @claire.dubois`,
          mentions: ['claire.dubois']
        }
      ],
      attachments: inv.attachments || [
        {
          id: 'ATT-1',
          name: `${inv.invoiceNumber}-original.pdf`,
          type: 'invoice_pdf',
          uploadedBy: 'Ingestion Pipeline',
          uploadedAt: inv.receivedAt,
          sizeKb: 248
        }
      ],
      timeline: [
        {
          id: 'TL-1',
          timestamp: inv.receivedAt,
          event: `Invoice received (${inv.invoiceNumber})`,
          actorName: 'Ingestion Pipeline',
          actorRole: 'system',
          note: `From ${inv.supplierName}`
        }
      ],
      versionHistory: []
    }));

    // Run audit checks on all seeded invoices (except keep RECEIVED with empty or initial preview)
    for (const inv of state.invoices) {
      const res = runAuditChecks(inv, state);
      inv.checklist = res.checklist;
      inv.riskScore = res.riskScore;
      inv.riskLevel = res.riskLevel;
      inv.riskReasons = res.riskReasons;
      inv.requiredApprovalLevels = res.requiredApprovalLevels;
      if (inv.status !== STATUSES.RECEIVED) {
        inv.timeline.push({
          id: `TL-${inv.timeline.length + 1}`,
          timestamp: inv.verifiedAt || inv.receivedAt,
          event: `Audit checks evaluated — Status: ${STATUS_META[inv.status].label}`,
          actorName: inv.assignee !== 'Unassigned' ? inv.assignee : 'Vaultgard Engine',
          actorRole: 'auditor',
          note: inv.riskReasons.join('; ') || 'All 9 fraud & compliance checks passed'
        });
      }
      recordInvoiceVersion(inv, { id: 'system', name: 'System Seed' }, 'Initial state');
    }

    appendAuditLog(state, {
      actorId: 'system',
      actorName: 'Vaultgard Core',
      actorRole: 'system',
      action: 'SYSTEM_INIT',
      entityType: 'system',
      entityId: 'VAULTGARD',
      summary: 'Initialized Invoice Audit & Payment Dashboard with 10 invoices across all 10 lifecycle statuses'
    });

    return state;
  }

  return {
    STATUSES,
    STATUS_META,
    ALL_STATUS_KEYS,
    ROLES,
    ROLE_PERMISSIONS,
    FX_RATES,
    convertCurrency,
    formatMoney,
    hasPermission,
    checkDepartmentAndAmountAccess,
    hasActorApprovedInvoice,
    appendAuditLog,
    verifyAuditLogIntegrity,
    recordInvoiceVersion,
    runAuditChecks,
    getRequiredApprovalLevels,
    computeKPIs,
    queryInvoices,
    exportInvoicesCSV,
    performWorkflowAction,
    getRemainingAmount,
    computeEarlyDiscount,
    canPayInvoice,
    scheduleInvoicePayment,
    generateSepaXml,
    createPaymentBatch,
    recordPaymentOrCredit,
    computeCashFlowForecast,
    setSupplierStatus,
    updateSupplierBankDetails,
    computeAlerts,
    computeAnalytics,
    parseOcrText,
    ingestInvoice,
    maskPII,
    createInitialState
  };
});
