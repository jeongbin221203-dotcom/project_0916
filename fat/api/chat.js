// Vercel 서버리스 함수이자 로컬 local-server.js 에서도 공용으로 쓰는 챗 API 핸들러
const fs = require("fs");
const path = require("path");
const vm = require("vm");

let SYSTEM = "당신은 회계·세무 실무 20년 경력의 공인회계사 겸 세무사로서 FAT 1급 학습자를 한국어로 지도합니다.";
try {
  const ctx = {};
  ctx.window = ctx;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "..", "chat-prompt.js"), "utf8"), ctx);
  if (ctx.CHAT_SYSTEM) SYSTEM = ctx.CHAT_SYSTEM;
} catch (e) { /* 기본 프롬프트 사용 */ }

function send(res, code, obj) {
  res.statusCode = code;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(obj));
}

function readBody(req, limit) {
  return new Promise((resolve, reject) => {
    let size = 0; const chunks = [];
    req.on("data", c => { size += c.length; if (size > limit) { reject(new Error("too large")); req.destroy(); } else chunks.push(c); });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") return send(res, 405, { error: "POST 요청만 가능합니다." });

  const KEY = process.env.OPENAI_API_KEY;
  const MODEL = process.env.OPENAI_MODEL || "gpt-4o-mini";
  const ACCESS = process.env.CHAT_ACCESS_CODE;

  if (!KEY) return send(res, 500, { error: "서버에 OPENAI_API_KEY가 설정되지 않았습니다." });
  if (ACCESS && req.headers["x-access-code"] !== ACCESS) {
    return send(res, 401, { error: "접근 코드가 필요하거나 올바르지 않습니다.", needCode: true });
  }

  let data = req.body;
  try {
    if (typeof data === "string") data = JSON.parse(data);
    if (!data || typeof data !== "object") data = JSON.parse(await readBody(req, 200 * 1024));
  } catch (e) { return send(res, 400, { error: "잘못된 요청입니다." }); }

  const msgs = (Array.isArray(data.messages) ? data.messages : [])
    .filter(m => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string" && m.content.trim())
    .slice(-20)
    .map(m => ({ role: m.role, content: m.content.slice(0, 6000) }));
  if (!msgs.length || msgs[0].role !== "user") return send(res, 400, { error: "메시지가 비어 있습니다." });

  let system = SYSTEM;
  if (typeof data.context === "string" && data.context.trim()) {
    system += "\n\n[학습자가 지금 보고 있는 화면]\n" + data.context.slice(0, 500);
  }

  try {
    const r = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: { "content-type": "application/json", "authorization": "Bearer " + KEY },
      body: JSON.stringify({ model: MODEL, max_tokens: 1500, messages: [{ role: "system", content: system }].concat(msgs) })
    });
    const j = await r.json();
    if (!r.ok) return send(res, 502, { error: (j.error && j.error.message) || "API 오류" });
    const text = j.choices && j.choices[0] && j.choices[0].message && j.choices[0].message.content;
    send(res, 200, { reply: text || "(빈 응답)" });
  } catch (e) {
    send(res, 502, { error: "API 호출 실패: " + e.message });
  }
};
