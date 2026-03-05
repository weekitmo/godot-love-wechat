import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { pipeline } from "node:stream";

const port = Number(process.env.MOCK_CDN_PORT || 39090);
const rootDir = path.resolve(
  process.cwd(),
  process.env.MOCK_CDN_ROOT || "mock-cdn-data"
);

fs.mkdirSync(rootDir, { recursive: true });

function setCors(res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET,HEAD,PUT,OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "*");
}

function sendJson(res, statusCode, data) {
  setCors(res);
  res.statusCode = statusCode;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(data, null, 2));
}

function sanitizePathname(pathname) {
  const decoded = decodeURIComponent(pathname || "/");
  const normalized = path.posix.normalize(decoded).replace(/^\/+/, "");
  if (!normalized || normalized === ".") return "";
  if (normalized.startsWith("..") || normalized.includes("/../")) return "";
  return normalized;
}

function contentTypeByExt(filename) {
  const ext = path.extname(filename).toLowerCase();
  if (ext === ".zip") return "application/zip";
  if (ext === ".js") return "application/javascript; charset=utf-8";
  if (ext === ".json") return "application/json; charset=utf-8";
  return "application/octet-stream";
}

const server = http.createServer((req, res) => {
  const requestUrl = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
  const method = req.method || "GET";

  if (method === "OPTIONS") {
    setCors(res);
    res.statusCode = 204;
    res.end();
    return;
  }

  if (requestUrl.pathname === "/health") {
    sendJson(res, 200, { ok: true, rootDir, port });
    return;
  }

  const key = sanitizePathname(requestUrl.pathname);
  if (!key) {
    sendJson(res, 400, { ok: false, error: "Invalid path. Expect /<bucket>/<object-key>" });
    return;
  }

  const absPath = path.resolve(rootDir, key);
  if (!absPath.startsWith(rootDir + path.sep) && absPath !== rootDir) {
    sendJson(res, 400, { ok: false, error: "Unsafe path." });
    return;
  }

  if (method === "PUT") {
    fs.mkdirSync(path.dirname(absPath), { recursive: true });
    const output = fs.createWriteStream(absPath);
    pipeline(req, output, (error) => {
      if (error) {
        sendJson(res, 500, { ok: false, error: error.message });
        return;
      }
      const stat = fs.statSync(absPath);
      sendJson(res, 200, { ok: true, key, bytes: stat.size, path: absPath });
    });
    return;
  }

  if (method === "GET" || method === "HEAD") {
    if (!fs.existsSync(absPath) || !fs.statSync(absPath).isFile()) {
      sendJson(res, 404, { ok: false, error: "Not found", key });
      return;
    }
    const stat = fs.statSync(absPath);
    setCors(res);
    res.statusCode = 200;
    res.setHeader("Content-Type", contentTypeByExt(absPath));
    res.setHeader("Content-Length", stat.size);
    if (method === "HEAD") {
      res.end();
      return;
    }
    fs.createReadStream(absPath).pipe(res);
    return;
  }

  sendJson(res, 405, { ok: false, error: `Method not allowed: ${method}` });
});

server.listen(port, "0.0.0.0", () => {
  console.log(`[mock-cdn] listening on http://127.0.0.1:${port}`);
  console.log(`[mock-cdn] root dir: ${rootDir}`);
  console.log("[mock-cdn] routes: PUT/GET /<bucket>/<object-key>, GET /health");
});
