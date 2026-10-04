#!/usr/bin/env node
// Local dev server for the frontend: serves the static files and proxies
// /api/* to the backend, mirroring what frontend/nginx.conf does in
// production. This lets "devbox run llm && devbox run backend && devbox
// run front" exercise the full stack on http://localhost:8081, without
// needing docker compose.
import { createServer } from 'node:http';
import { createReadStream, promises as fs } from 'node:fs';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('.', import.meta.url));
const FRONTEND_PORT = Number(process.env.FRONTEND_PORT ?? 8081);
const BACKEND_PORT = Number(process.env.BACKEND_PORT ?? 8000);
const BACKEND_URL = `http://localhost:${BACKEND_PORT}`;

const CONTENT_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

async function proxyToBackend(req, res) {
  const target = `${BACKEND_URL}${req.url}`;
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const body = chunks.length ? Buffer.concat(chunks) : undefined;

  let backendRes;
  try {
    backendRes = await fetch(target, {
      method: req.method,
      headers: { ...req.headers, host: undefined },
      body,
    });
  } catch (err) {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'backend unavailable' }));
    return;
  }

  const responseBody = Buffer.from(await backendRes.arrayBuffer());
  res.writeHead(backendRes.status, {
    'Content-Type': backendRes.headers.get('content-type') ?? 'application/octet-stream',
  });
  res.end(responseBody);
}

async function serveStatic(req, res) {
  const urlPath = decodeURIComponent(req.url.split('?')[0]);
  const safePath = normalize(urlPath).replace(/^(\.\.[/\\])+/, '');
  let filePath = join(ROOT, safePath === '/' ? 'index.html' : safePath);

  try {
    const stat = await fs.stat(filePath);
    if (stat.isDirectory()) {
      filePath = join(filePath, 'index.html');
    }
  } catch {
    filePath = join(ROOT, 'index.html');
  }

  const contentType = CONTENT_TYPES[extname(filePath)] ?? 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': contentType });
  createReadStream(filePath).pipe(res);
}

const server = createServer((req, res) => {
  if (req.url.startsWith('/api/')) {
    proxyToBackend(req, res);
  } else {
    serveStatic(req, res);
  }
});

server.listen(FRONTEND_PORT, () => {
  console.log(`Frontend dev server: http://localhost:${FRONTEND_PORT}`);
  console.log(`Proxying /api/* -> ${BACKEND_URL}`);
});
