'use strict';

const https = require('https');
const http = require('http');

/**
 * 402Proof Express middleware — protects any route behind XRP/RLUSD payment.
 *
 * Usage (Express):
 *   const { proof402 } = require('proof402-middleware');
 *   app.use('/premium', proof402({ endpointId: 'your-endpoint-id', serverUrl: 'https://...' }));
 *
 * On every request the middleware checks for a valid X-Payment-Token header.
 * If missing or expired it returns HTTP 402 with full invoice + instructions.
 */
function proof402({ endpointId, serverUrl = 'https://402proof.onrender.com' }) {
  if (!endpointId) throw new Error('[402Proof] endpointId is required');

  return async function (req, res, next) {
    const token = req.headers['x-payment-token'];

    if (token) {
      try {
        const result = await postJSON(`${serverUrl}/v1/token/verify`, { token, endpoint_id: endpointId });
        if (result.status === 'VALID') {
          req.proof402 = { endpointId: result.endpoint_id, verified: true };
          return next();
        }
      } catch (_) { /* fall through to 402 */ }
    }

    try {
      const inv = await postJSON(`${serverUrl}/v1/invoice`, { endpoint_id: endpointId });
      res.status(402)
        .set({
          'Content-Type': 'application/json',
          'X-Payment-Network': 'XRPL',
          'X-Payment-Address': inv.pay_to,
          'X-Payment-Amount': inv.amount,
          'X-Payment-Asset': inv.asset,
          'X-Invoice-ID': inv.invoice_id,
          'X-Memo-Hex': inv.memo_hex,
          'X-Invoice-Expires': String(inv.expires_at),
          'X-Verify-URL': `${serverUrl}/v1/verify`,
        })
        .json({
          error: 'Payment Required',
          invoice: inv,
          instructions: {
            step1: `Send ${inv.amount} ${inv.asset} on XRPL to ${inv.pay_to}`,
            step2: `Include MemoData: ${inv.memo_hex} in your XRPL payment`,
            step3: `POST ${serverUrl}/v1/verify with { invoice_id, tx_hash, agent_wallet }`,
            step4: 'Retry this request with header: X-Payment-Token: <token>',
          },
        });
    } catch (err) {
      console.error('[402Proof] invoice generation failed:', err.message);
      res.status(503).json({ error: 'Payment service unavailable' });
    }
  };
}

/**
 * 402Proof Next.js App Router middleware helper.
 *
 * Usage (middleware.ts):
 *   import { proof402Next } from 'proof402-middleware';
 *   export default proof402Next({ endpointId: '...', serverUrl: '...' });
 *   export const config = { matcher: ['/premium/:path*'] };
 */
function proof402Next({ endpointId, serverUrl = 'https://402proof.onrender.com' }) {
  if (!endpointId) throw new Error('[402Proof] endpointId is required');

  return async function (request) {
    const { NextResponse } = require('next/server');
    const token = request.headers.get('x-payment-token');

    if (token) {
      try {
        const result = await postJSON(`${serverUrl}/v1/token/verify`, { token, endpoint_id: endpointId });
        if (result.status === 'VALID') return NextResponse.next();
      } catch (_) {}
    }

    try {
      const inv = await postJSON(`${serverUrl}/v1/invoice`, { endpoint_id: endpointId });
      return new NextResponse(JSON.stringify({ error: 'Payment Required', invoice: inv }), {
        status: 402,
        headers: {
          'Content-Type': 'application/json',
          'X-Payment-Network': 'XRPL',
          'X-Payment-Address': inv.pay_to,
          'X-Payment-Amount': inv.amount,
          'X-Payment-Asset': inv.asset,
          'X-Invoice-ID': inv.invoice_id,
          'X-Memo-Hex': inv.memo_hex,
          'X-Invoice-Expires': String(inv.expires_at),
          'X-Verify-URL': `${serverUrl}/v1/verify`,
        },
      });
    } catch (err) {
      return new NextResponse('Payment service unavailable', { status: 503 });
    }
  };
}

/**
 * Cloudflare Workers handler wrapper.
 *
 * Usage:
 *   import { proof402Worker } from 'proof402-middleware';
 *   export default { fetch: proof402Worker({ endpointId: '...', serverUrl: '...', handler: myHandler }) };
 */
function proof402Worker({ endpointId, serverUrl, handler }) {
  return async function (request, env, ctx) {
    const token = request.headers.get('x-payment-token');

    if (token) {
      try {
        const r = await fetch(`${serverUrl}/v1/token/verify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token, endpoint_id: endpointId }),
        });
        if (r.ok) {
          const result = await r.json();
          if (result.status === 'VALID') return handler(request, env, ctx);
        }
      } catch (_) {}
    }

    try {
      const r = await fetch(`${serverUrl}/v1/invoice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ endpoint_id: endpointId }),
      });
      const inv = await r.json();
      return new Response(JSON.stringify({ error: 'Payment Required', invoice: inv }), {
        status: 402,
        headers: {
          'Content-Type': 'application/json',
          'X-Payment-Network': 'XRPL',
          'X-Payment-Address': inv.pay_to,
          'X-Payment-Amount': inv.amount,
          'X-Payment-Asset': inv.asset,
          'X-Invoice-ID': inv.invoice_id,
          'X-Memo-Hex': inv.memo_hex,
        },
      });
    } catch {
      return new Response('Payment service unavailable', { status: 503 });
    }
  };
}

// Zero-dependency JSON POST helper
function postJSON(url, body) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    const parsed = new URL(url);
    const lib = parsed.protocol === 'https:' ? https : http;
    const options = {
      hostname: parsed.hostname,
      port: parsed.port || (parsed.protocol === 'https:' ? 443 : 80),
      path: parsed.pathname + parsed.search,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
    };
    const req = lib.request(options, (res) => {
      let raw = '';
      res.on('data', (c) => (raw += c));
      res.on('end', () => {
        try {
          const parsed = JSON.parse(raw);
          res.statusCode >= 200 && res.statusCode < 300 ? resolve(parsed) : reject(new Error(`${res.statusCode}: ${raw}`));
        } catch {
          reject(new Error(`Non-JSON response: ${raw}`));
        }
      });
    });
    req.on('error', reject);
    req.setTimeout(10000, () => { req.destroy(); reject(new Error('Timeout')); });
    req.write(data);
    req.end();
  });
}

module.exports = { proof402, proof402Next, proof402Worker };
