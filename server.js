// Vaultgard Zero-Dependency HTTP Server & REST API (Node.js stdlib)
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const VG = require('./core.js');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8'
};

function createServer(initialState) {
  const state = initialState || VG.createInitialState();

  function sendJson(res, status, data) {
    res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(data));
  }

  function readJsonBody(req) {
    return new Promise((resolve, reject) => {
      let body = '';
      req.on('data', (chunk) => {
        body += chunk;
        if (body.length > 1e6) req.destroy();
      });
      req.on('end', () => {
        if (!body) return resolve({});
        try {
          resolve(JSON.parse(body));
        } catch (err) {
          reject(new Error('Invalid JSON payload'));
        }
      });
      req.on('error', reject);
    });
  }

  const handleRequest = async (req, res) => {
    const url = new URL(req.url, `http://${req.headers?.host || 'localhost'}`);
    const pathname = url.pathname;

    try {
      // REST API Endpoints (Section 13)
      if (pathname === '/api/kpis' && req.method === 'GET') {
        return sendJson(res, 200, VG.computeKPIs(state));
      }
      if (pathname === '/api/invoices' && req.method === 'GET') {
        const q = Object.fromEntries(url.searchParams.entries());
        return sendJson(res, 200, VG.queryInvoices(state, q));
      }
      if (pathname === '/api/invoices/ingest' && req.method === 'POST') {
        const body = req.body !== undefined ? req.body : await readJsonBody(req);
        const inv = VG.ingestInvoice(state, body, body.source || 'rest_api');
        return sendJson(res, 201, inv);
      }
      if (pathname.startsWith('/api/invoices/') && pathname.endsWith('/action') && req.method === 'POST') {
        const parts = pathname.split('/');
        const invoiceId = parts[3];
        const body = req.body !== undefined ? req.body : await readJsonBody(req);
        const actor = body.actorId
          ? state.users.find((u) => u.id === body.actorId) || state.currentUser
          : state.currentUser;
        const inv = VG.performWorkflowAction(state, invoiceId, body.action, body.payload || {}, actor);
        return sendJson(res, 200, inv);
      }
      if (pathname === '/api/payments/batch' && req.method === 'POST') {
        const body = req.body !== undefined ? req.body : await readJsonBody(req);
        const actor = body.actorId
          ? state.users.find((u) => u.id === body.actorId) || state.currentUser
          : state.currentUser;
        const batch = VG.createPaymentBatch(state, body.invoiceIds || [], body.options || {}, actor);
        return sendJson(res, 201, batch);
      }
      if (pathname === '/api/alerts' && req.method === 'GET') {
        return sendJson(res, 200, VG.computeAlerts(state));
      }
      if (pathname === '/api/audit-log' && req.method === 'GET') {
        return sendJson(res, 200, {
          integrity: VG.verifyAuditLogIntegrity(state.auditLog),
          entries: state.auditLog
        });
      }

      // Static files
      const safeFile = pathname === '/' ? '/index.html' : pathname;
      const resolvedPath = path.resolve(__dirname, '.' + safeFile);
      if (!resolvedPath.startsWith(__dirname) || !fs.existsSync(resolvedPath) || fs.statSync(resolvedPath).isDirectory()) {
        return sendJson(res, 404, { error: 'Not found' });
      }
      const ext = path.extname(resolvedPath);
      res.writeHead(200, { 'Content-Type': MIME_TYPES[ext] || 'application/octet-stream' });
      res.end(fs.readFileSync(resolvedPath));
    } catch (err) {
      sendJson(res, 400, { error: err.message });
    }
  };

  const server = http.createServer(handleRequest);

  return { server, state, handleRequest };
}

if (require.main === module) {
  const port = Number(process.env.PORT) || 3000;
  const { server } = createServer();
  server.listen(port, () => {
    console.log(`Vaultgard Dashboard listening on http://localhost:${port}`);
  });
}

module.exports = { createServer };
