// 로컬 실행: .env 에 OPENAI_API_KEY=키 를 적고  node server.js  →  http://localhost:3000
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = __dirname;

// 간단한 .env 로더 (의존성 없음). 이미 설정된 환경변수는 덮어쓰지 않음.
try {
  fs.readFileSync(path.join(ROOT, ".env"), "utf8").split(/\r?\n/).forEach(line => {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m && !(m[1] in process.env)) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  });
} catch (e) { /* .env 없음 */ }

const chat = require("./api/chat.js");
const PORT = process.env.PORT || 3000;

const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
  ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon"
};

http.createServer((req, res) => {
  if (req.url === "/api/chat") return chat(req, res);
  if (req.method !== "GET") { res.writeHead(405); return res.end(); }
  let p;
  try { p = decodeURIComponent(req.url.split("?")[0]); } catch (e) { res.writeHead(400); return res.end(); }
  if (p === "/") p = "/index.html";
  const file = path.normalize(path.join(ROOT, p));
  const rel = path.relative(ROOT, file);
  const hidden = rel.split(path.sep).some(seg => seg.startsWith("."));
  if (rel.startsWith("..") || hidden || rel === "server.js" || rel.startsWith("api" + path.sep) || !(path.extname(file) in TYPES)) {
    res.writeHead(403); return res.end("forbidden");
  }
  fs.readFile(file, (err, buf) => {
    if (err) { res.writeHead(404); return res.end("not found"); }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] });
    res.end(buf);
  });
}).listen(PORT, "127.0.0.1", () => {
  const k = process.env.OPENAI_API_KEY;
  console.log("http://localhost:" + PORT + (k ? "   모델: " + (process.env.OPENAI_MODEL || "gpt-4o-mini") : "   (경고: OPENAI_API_KEY 미설정, 챗봇 응답 불가)"));
});
