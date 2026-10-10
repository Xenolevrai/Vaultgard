// VaultGuard — graphiques de l'espace de travail (SVG, sans dépendance).
// Le tracé du schéma de parcours reprend le moteur écrit pour la maquette (archive/maquette-front/core.js).
// Aucun style en ligne : les couleurs passent par des attributs SVG et les règles sont dans styles.css (CSP).
(function (root) {
  'use strict';

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function empty(width, height, message) {
    return `<svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" class="chart-svg" role="img" aria-label="${esc(message)}">` +
      `<text x="${width / 2}" y="${height / 2}" text-anchor="middle" class="chart-empty">${esc(message)}</text></svg>`;
  }

  // data : { stages: [titres], nodes: [{id, label, stage, value, count, ids, color}], links: [{source, target, value, ids}], total }
  function sankey(data, options) {
    const width = (options && options.width) || 920;
    const height = (options && options.height) || 340;
    const money = (options && options.money) || String;
    const nodeWidth = 18;
    const nodePadding = 16;
    const nodes = ((data && data.nodes) || []).filter((n) => n.value > 0);
    const links = ((data && data.links) || []).filter((l) => l.value > 0);
    if (!data || !(data.total > 0) || nodes.length === 0) {
      return empty(width, height, 'Aucune facture reçue pour le moment');
    }

    const padding = { top: 38, right: 30, bottom: 25, left: 30 };
    const innerWidth = width - padding.left - padding.right - nodeWidth;
    const innerHeight = height - padding.top - padding.bottom;

    const stageMap = new Map();
    for (const n of nodes) {
      if (!stageMap.has(n.stage)) stageMap.set(n.stage, []);
      stageMap.get(n.stage).push(n);
    }
    const stageKeys = Array.from(stageMap.keys()).sort((a, b) => a - b);
    const numStages = Math.max(...stageKeys) + 1;

    let maxGaps = 0;
    for (const s of stageKeys) maxGaps = Math.max(maxGaps, stageMap.get(s).length - 1);
    const totalGap = Math.min(innerHeight * 0.45, maxGaps * nodePadding);
    const gap = maxGaps > 0 ? totalGap / maxGaps : 0;
    const scale = (innerHeight - totalGap) / Math.max(0.01, data.total);

    const layout = new Map();
    for (const s of stageKeys) {
      const stageNodes = stageMap.get(s);
      const used = stageNodes.reduce((sum, n) => sum + Math.max(4, n.value * scale), 0) + (stageNodes.length - 1) * gap;
      let y = padding.top + Math.max(0, (innerHeight - used) / 2);
      const x = padding.left + (numStages > 1 ? (s / (numStages - 1)) * innerWidth : 0);
      for (const n of stageNodes) {
        const h = Math.max(4, n.value * scale);
        layout.set(n.id, Object.assign({}, n, { x, y, w: nodeWidth, h }));
        y += h + gap;
      }
    }

    const outOffset = new Map();
    const inOffset = new Map();
    const sorted = links.slice().sort((a, b) => {
      const sa = layout.get(a.source), sb = layout.get(b.source), ta = layout.get(a.target), tb = layout.get(b.target);
      if (!sa || !sb || !ta || !tb) return 0;
      return sa.y !== sb.y ? sa.y - sb.y : ta.y - tb.y;
    });

    const ribbons = [];
    const gradients = [];
    sorted.forEach((link, index) => {
      const src = layout.get(link.source);
      const tgt = layout.get(link.target);
      if (!src || !tgt) return;
      const thick = Math.max(1, link.value * scale);
      const so = outOffset.get(src.id) || 0;
      const to = inOffset.get(tgt.id) || 0;
      outOffset.set(src.id, so + thick);
      inOffset.set(tgt.id, to + thick);
      const y0 = src.y + so, y1 = tgt.y + to;
      const x0 = src.x + src.w, x1 = tgt.x;
      const cx = Math.max(1, x1 - x0) * 0.48;
      const f = (v) => v.toFixed(1);
      const d = `M ${f(x0)},${f(y0)} C ${f(x0 + cx)},${f(y0)} ${f(x1 - cx)},${f(y1)} ${f(x1)},${f(y1)} ` +
        `L ${f(x1)},${f(y1 + thick)} C ${f(x1 - cx)},${f(y1 + thick)} ${f(x0 + cx)},${f(y0 + thick)} ${f(x0)},${f(y0 + thick)} Z`;
      const gradId = `sankey-grad-${index}`;
      gradients.push(`<linearGradient id="${gradId}" x1="0%" y1="0%" x2="100%" y2="0%">` +
        `<stop offset="0%" stop-color="${esc(src.color)}" stop-opacity="0.45"/>` +
        `<stop offset="100%" stop-color="${esc(tgt.color)}" stop-opacity="0.45"/></linearGradient>`);
      ribbons.push(`<path class="sankey-link" d="${d}" fill="url(#${gradId})" data-ids="${esc((link.ids || []).join(','))}">` +
        `<title>${esc(src.label)} → ${esc(tgt.label)} : ${esc(money(link.value))}</title></path>`);
    });

    const headers = (data.stages || []).slice(0, numStages).map((name, s) => {
      const x = padding.left + (numStages > 1 ? (s / (numStages - 1)) * innerWidth : 0);
      const anchor = s === 0 ? 'start' : s === numStages - 1 ? 'end' : 'middle';
      const hx = s === 0 ? x : s === numStages - 1 ? x + nodeWidth : x + nodeWidth / 2;
      return `<text class="sankey-stage" x="${hx.toFixed(1)}" y="20" text-anchor="${anchor}">${esc(name)}</text>`;
    });

    const rects = [];
    const labels = [];
    for (const node of layout.values()) {
      const plural = node.count > 1 ? 's' : '';
      rects.push(`<rect class="sankey-node-rect" x="${node.x.toFixed(1)}" y="${node.y.toFixed(1)}" width="${node.w}" ` +
        `height="${node.h.toFixed(1)}" rx="4" fill="${esc(node.color)}" data-ids="${esc((node.ids || []).join(','))}">` +
        `<title>${esc(node.label)} : ${esc(money(node.value))} (${node.count} facture${plural})</title></rect>`);
      // Libellé à droite de la barre, sauf pour la dernière colonne (à gauche, faute de place).
      const last = node.stage === numStages - 1;
      const lx = last ? node.x - 8 : node.x + node.w + 8;
      const anchor = last ? 'end' : 'start';
      const ly = node.y + Math.max(10, node.h / 2);
      labels.push(`<text class="sankey-node-label" x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" text-anchor="${anchor}" dominant-baseline="central">` +
        `<tspan class="sankey-label-name">${esc(node.label)}</tspan>` +
        `<tspan class="sankey-label-val" dx="4">(${esc(money(node.value))})</tspan></text>`);
    }

    return `<svg id="sankey-svg" viewBox="0 0 ${width} ${height}" width="100%" class="sankey-svg" role="img" aria-label="Parcours des factures">` +
      `<defs>${gradients.join('')}</defs><g>${headers.join('')}</g><g>${ribbons.join('')}</g><g>${rects.join('')}</g><g>${labels.join('')}</g></svg>`;
  }

  // months : [{label, ok, review, refused}] (montants en euros)
  function monthly(months, options) {
    const money = (options && options.money) || String;
    const width = 460, height = 220;
    const pad = { top: 34, right: 16, bottom: 34, left: 62 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    if (!months || months.length === 0) return empty(width, height, 'Pas encore de facture');

    const totals = months.map((m) => m.ok + m.review + m.refused);
    const maxVal = Math.max(1, ...totals) * 1.15;
    const band = plotW / months.length;
    const barW = Math.min(48, Math.max(14, band * 0.52));
    const base = pad.top + plotH;

    const grid = [0, maxVal / 2, maxVal].map((v) => {
      const y = base - (v / maxVal) * plotH;
      return `<line x1="${pad.left}" y1="${y.toFixed(1)}" x2="${width - pad.right}" y2="${y.toFixed(1)}" class="chart-grid"/>` +
        `<text x="${pad.left - 8}" y="${(y + 3).toFixed(1)}" text-anchor="end" class="chart-tick">${esc(money(v, true))}</text>`;
    }).join('');

    const parts = [['ok', 'chart-fill-ok', 'Acceptées'], ['review', 'chart-fill-review', 'À vérifier'], ['refused', 'chart-fill-refused', 'Refusées']];
    const bars = months.map((m, i) => {
      const x = pad.left + i * band + (band - barW) / 2;
      let y = base;
      let out = '';
      for (const [key, cls, name] of parts) {
        const h = (m[key] / maxVal) * plotH;
        if (h <= 0) continue;
        y -= h;
        out += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" rx="3" class="${cls}">` +
          `<title>${esc(m.label)} — ${name} : ${esc(money(m[key]))}</title></rect>`;
      }
      const cx = x + barW / 2;
      return out + `<text x="${cx.toFixed(1)}" y="${(y - 6).toFixed(1)}" text-anchor="middle" class="chart-value">${esc(money(totals[i], true))}</text>` +
        `<text x="${cx.toFixed(1)}" y="${base + 18}" text-anchor="middle" class="chart-label">${esc(m.label)}</text>`;
    }).join('');

    const legend = parts.map(([, cls, name], i) =>
      `<rect x="${pad.left + i * 104}" y="6" width="10" height="10" rx="2" class="${cls}"/>` +
      `<text x="${pad.left + i * 104 + 15}" y="15" class="chart-legend">${name}</text>`).join('');

    return `<svg viewBox="0 0 ${width} ${height}" width="100%" class="chart-svg" role="img" aria-label="Montants reçus par mois">${grid}${bars}${legend}</svg>`;
  }

  // rows : [{name, total, risky}] (5 au plus)
  function suppliers(rows, options) {
    const money = (options && options.money) || String;
    const width = 460, height = 220;
    const pad = { top: 16, right: 96, bottom: 12, left: 138 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    if (!rows || rows.length === 0) return empty(width, height, 'Pas encore de facture');

    const maxVal = Math.max(1, ...rows.map((r) => r.total)) * 1.08;
    const rowH = plotH / rows.length;
    const barH = Math.min(22, rowH * 0.58);
    const body = rows.map((r, i) => {
      const y = pad.top + i * rowH + (rowH - barH) / 2;
      const w = Math.max(4, (r.total / maxVal) * plotW);
      const name = r.name.length > 19 ? r.name.slice(0, 18) + '…' : r.name;
      const mid = (y + barH / 2 + 4).toFixed(1);
      return `<text x="${pad.left - 10}" y="${mid}" text-anchor="end" class="chart-name">${esc(name)}</text>` +
        `<rect x="${pad.left}" y="${y.toFixed(1)}" width="${plotW}" height="${barH.toFixed(1)}" rx="4" class="chart-track"/>` +
        `<rect x="${pad.left}" y="${y.toFixed(1)}" width="${w.toFixed(1)}" height="${barH.toFixed(1)}" rx="4" class="${r.risky ? 'chart-fill-refused' : 'chart-fill-neutral'}">` +
        `<title>${esc(r.name)} : ${esc(money(r.total))}${r.risky ? ' — au moins une facture refusée' : ''}</title></rect>` +
        `<text x="${(pad.left + w + 8).toFixed(1)}" y="${mid}" class="${r.risky ? 'chart-value chart-text-danger' : 'chart-value'}">${esc(money(r.total, true))}</text>`;
    }).join('');

    return `<svg viewBox="0 0 ${width} ${height}" width="100%" class="chart-svg" role="img" aria-label="Principaux fournisseurs">${body}</svg>`;
  }

  root.VGCharts = { sankey, monthly, suppliers };
})(typeof globalThis !== 'undefined' ? globalThis : this);
