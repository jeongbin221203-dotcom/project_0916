(function () {
  var KEY = "fat1.chat";
  var history = [];
  try { history = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (e) {}
  function persist() { try { localStorage.setItem(KEY, JSON.stringify(history.slice(-40))); } catch (e) {} }

  var panel = document.createElement("aside");
  panel.id = "chatPanel";
  panel.innerHTML =
    '<div class="chat-head"><div><strong>AI 학습 도우미</strong><small>모르는 개념·문제를 물어보세요</small></div>' +
    '<div><button type="button" id="chatClear">대화 지우기</button><button type="button" id="chatClose" aria-label="닫기">✕</button></div></div>' +
    '<div id="chatLog"></div>' +
    '<div class="chat-tools"><button type="button" id="chatGrab">선택한 글 가져오기</button></div>' +
    '<form class="chat-form"><textarea id="chatInput" placeholder="질문 입력 (Enter 전송, Shift+Enter 줄바꿈)"></textarea><button id="chatSend" type="submit">전송</button></form>';
  var toggle = document.createElement("button");
  toggle.id = "chatToggle"; toggle.type = "button"; toggle.title = "AI 도우미 열기"; toggle.textContent = "💬";
  document.body.appendChild(panel);
  document.body.appendChild(toggle);
  var topBtn = document.createElement("button");
  topBtn.id = "topBtn"; topBtn.type = "button"; topBtn.title = "맨 위로"; topBtn.textContent = "TOP";
  topBtn.addEventListener("click", function () { window.scrollTo({ top: 0, behavior: "smooth" }); });
  document.body.appendChild(topBtn);

  var log = panel.querySelector("#chatLog");
  var input = panel.querySelector("#chatInput");
  var sendBtn = panel.querySelector("#chatSend");

  function setOpen(v) {
    document.body.classList.toggle("chat-open", v);
    toggle.textContent = v ? "✕" : "💬";
    toggle.title = v ? "AI 도우미 닫기" : "AI 도우미 열기";
    if (v) { log.scrollTop = log.scrollHeight; setTimeout(function () { input.focus(); }, 50); }
  }
  setOpen(false);
  toggle.addEventListener("click", function () { setOpen(!document.body.classList.contains("chat-open")); });
  panel.querySelector("#chatClose").addEventListener("click", function () { setOpen(false); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.body.classList.contains("chat-open")) setOpen(false);
  });

  function add(role, text) {
    var d = document.createElement("div");
    d.className = "msg " + role;
    d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  function render() {
    log.innerHTML = "";
    if (!history.length) add("bot", "안녕하세요! FAT 1급 공부 중 막히는 개념이나 문제를 물어보세요. 문제 텍스트를 드래그한 뒤 '선택한 글 가져오기'를 누르면 입력창에 붙습니다.");
    history.forEach(function (m) { add(m.role === "user" ? "user" : "bot", m.content); });
  }
  render();

  panel.querySelector("#chatClear").addEventListener("click", function () {
    history = []; persist(); render();
  });

  // 선택이 사라져도 마지막으로 선택한 글(채팅창 밖)을 기억
  var lastSel = "";
  document.addEventListener("selectionchange", function () {
    var sel = window.getSelection && window.getSelection();
    var t = sel ? String(sel).trim() : "";
    if (t && sel.anchorNode && !panel.contains(sel.anchorNode)) lastSel = t;
  });
  panel.querySelector("#chatGrab").addEventListener("mousedown", function (e) { e.preventDefault(); });
  panel.querySelector("#chatGrab").addEventListener("click", function () {
    var t = (window.getSelection ? String(window.getSelection()) : "").trim() || lastSel;
    if (!t) { add("err", "먼저 페이지에서 문제나 문장을 드래그해 선택해 주세요."); return; }
    input.value = (input.value ? input.value + "\n" : "") + t.slice(0, 1500);
    input.focus();
  });

  function context() {
    var t = document.getElementById("studyTitle");
    return t ? t.textContent : "";
  }

  // ---- 응답 요청: API 키는 서버(.env 또는 Vercel 환경변수)에만 둠 ----
  var CODESTORE = "fat1.accesscode";
  function getCode() { try { return localStorage.getItem(CODESTORE) || ""; } catch (e) { return ""; } }
  function setCode(c) { try { if (c) localStorage.setItem(CODESTORE, c); else localStorage.removeItem(CODESTORE); } catch (e) {} }

  function askServer(msgs, retried) {
    return fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-access-code": getCode() },
      body: JSON.stringify({ messages: msgs, context: context() })
    }).then(function (r) {
      return r.json().then(function (j) {
        if (r.status === 401 && j.needCode && !retried) {
          var c = (window.prompt("접근 코드를 입력하세요.") || "").trim();
          if (!c) throw new Error("접근 코드가 필요합니다.");
          setCode(c);
          return askServer(msgs, true);
        }
        if (!r.ok) { if (r.status === 401) setCode(""); throw new Error(j.error || "서버 오류"); }
        return j.reply;
      });
    });
  }

  function ask(msgs) {
    if (!/^https?:$/.test(location.protocol)) {
      return Promise.reject(new Error("이 페이지는 파일로 열려 있어 AI를 쓸 수 없습니다. start.bat을 더블클릭하거나 터미널에서 node local-server.js 실행 후 http://localhost:3000 으로 접속해 주세요."));
    }
    return askServer(msgs).catch(function (err) {
      if (/Failed to fetch|NetworkError|Unexpected token|JSON/.test(err.message || "")) {
        throw new Error("AI 서버에 연결할 수 없습니다. start.bat을 실행했는지 확인해 주세요.");
      }
      throw err;
    });
  }

  var busy = false;
  panel.querySelector(".chat-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || busy) return;
    busy = true; sendBtn.disabled = true;
    input.value = "";
    history.push({ role: "user", content: text });
    add("user", text);
    var wait = add("bot", "답변 작성 중...");
    ask(history.slice(-20)).then(function (reply) {
      wait.textContent = reply;
      history.push({ role: "assistant", content: reply });
      persist();
    }).catch(function (err) {
      history.pop();
      wait.className = "msg err";
      wait.textContent = err.message || "오류가 발생했습니다.";
    }).then(function () {
      busy = false; sendBtn.disabled = false; log.scrollTop = log.scrollHeight; input.focus();
    });
  });

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      panel.querySelector(".chat-form").requestSubmit();
    }
  });
})();
