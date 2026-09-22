/* 대화 한 줄기.

   시작 화면의 세 탭(무역 상담 · 운송 계획 · 서류 작성)과 고래 상담창은
   같은 대화를 나눠 씁니다. 어디서 말하든 양쪽에 똑같이 보이고, 다른 화면으로
   옮겨 가도 이어집니다.

   브라우저 탭의 sessionStorage에 둡니다. 탭을 닫으면 사라지고, 서버에는
   쌓지 않습니다. 회원마다 따로 두어 한 탭에서 계정을 바꿔도 섞이지 않습니다.

   메시지 모양: { role, text, mode, kind }
     role  "user" | "assistant"
     mode  "consult" | "planning" | "documents" | "support" (어디서 나눈 말인지)
     kind  "" 보통 대화 · "greeting" 먼저 건넨 인사 · "note" 안내 · "warn" 확인할 것
           (kind가 있는 줄은 AI에게 앞 대화로 넘기지 않습니다) */
(function () {
  "use strict";

  const SCOPE = (window.FORWARDUS_CHAT && window.FORWARDUS_CHAT.scope) || "guest";
  const KEY = `forwardus:chat:${SCOPE}`;
  // 오래 쓰면 저장 공간을 넘습니다. 뒤쪽만 남깁니다.
  const MAX_MESSAGES = 200;
  // AI에게 넘기는 앞 대화. 서버도 뒤쪽 몇 개만 쓰지만 보내는 양부터 줄입니다.
  const MAX_HISTORY = 20;

  const listeners = [];

  function empty() {
    return { messages: [], docDraft: {} };
  }

  function read() {
    try {
      const raw = window.sessionStorage.getItem(KEY);
      if (!raw) return empty();
      const state = JSON.parse(raw);
      return { ...empty(), ...state,
               messages: Array.isArray(state.messages) ? state.messages : [] };
    } catch (error) {
      return empty();
    }
  }

  function write(state) {
    try {
      window.sessionStorage.setItem(KEY, JSON.stringify(state));
    } catch (error) {
      /* 저장 공간이 없으면 이 화면에서만 이어집니다. */
    }
  }

  function emit(event) {
    listeners.forEach((fn) => {
      try { fn(event); } catch (error) { console.error(error); }
    });
  }

  const ForwardusChat = {
    messages() {
      return read().messages;
    },

    /* 한 줄을 더합니다. source는 더한 쪽 화면입니다. 그 화면은 이미 그렸으니
       다시 그리지 않고, 나머지 화면만 그립니다. */
    append(message, source) {
      const state = read();
      const entry = { role: message.role, text: String(message.text || ""),
                      mode: message.mode || "support", kind: message.kind || "" };
      // 시작 화면이 다시 그릴 때 쓰는 덧붙임(서류 칸 목록 등). 작은 것만 둡니다.
      if (message.extra) entry.extra = message.extra;
      state.messages.push(entry);
      if (state.messages.length > MAX_MESSAGES) {
        state.messages = state.messages.slice(-MAX_MESSAGES);
      }
      write(state);
      emit({ type: "append", message: entry, source });
      return entry;
    },

    /* 탭 인사는 한 번에 하나만 둡니다. 앞 탭의 인사는 지우고 새 인사를 맨 뒤에 붙입니다.
       탭을 오갈 때마다 인사가 쌓이면 무엇을 하던 중인지 알아보기 어렵습니다. */
    replaceGreeting(message, source) {
      const state = read();
      state.messages = state.messages.filter((m) => m.kind !== "greeting");
      if (message) {
        state.messages.push({ role: "assistant", text: String(message.text || ""),
                              mode: message.mode || "support", kind: "greeting" });
      }
      write(state);
      emit({ type: "greeting", source });
    },

    /* AI에게 넘길 앞 대화. 인사·안내는 빼고 주고받은 말만 보냅니다. */
    history() {
      return read().messages
        .filter((m) => !m.kind && (m.role === "user" || m.role === "assistant") && m.text)
        .slice(-MAX_HISTORY)
        .map((m) => ({ role: m.role, content: m.text }));
    },

    get(field) {
      return read()[field];
    },

    set(field, value) {
      const state = read();
      state[field] = value;
      write(state);
    },

    clear(source) {
      write(empty());
      emit({ type: "clear", source });
    },

    subscribe(fn) {
      listeners.push(fn);
    },

    /* 답변 그리기.
       AI는 **굵게**나 "- 목록" 같은 표시를 섞어 씁니다. 글자 그대로 두면
       별표가 그대로 보입니다. 서식만 살려 주되, 넣기 전에 반드시 escape합니다.
       AI가 하는 말에 <script>가 섞여 들어올 수 있습니다. */
    render(text) {
      const { escapeHtml } = window.Forwardus;
      return escapeHtml(text).split(/\n{2,}/).map((block) => {
        const lines = block.split("\n").filter((line) => line.trim());
        if (!lines.length) return "";
        // 한 덩어리가 전부 목록이면 목록으로, 아니면 문단으로 그립니다.
        if (lines.every((line) => /^\s*(?:[-*•]|\d+\.)\s+/.test(line))) {
          const items = lines.map((line) =>
            `<li>${inline(line.replace(/^\s*(?:[-*•]|\d+\.)\s+/, ""))}</li>`).join("");
          return /^\s*\d+\./.test(lines[0]) ? `<ol>${items}</ol>` : `<ul>${items}</ul>`;
        }
        if (lines.length === 1 && /^#{1,4}\s+/.test(lines[0])) {
          return `<h4>${inline(lines[0].replace(/^#{1,4}\s+/, ""))}</h4>`;
        }
        return `<p>${lines.map(inline).join("<br>")}</p>`;
      }).join("");
    },

    MODE_LABELS: { consult: "무역 상담", planning: "운송 계획",
                   documents: "서류 작성", support: "고래 상담" },
  };

  function inline(escaped) {
    return escaped
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      // {{ }}로 감싼 것은 빨갛게. 꼭 있어야 하는 칸과 운송 계획에서
      // 정해지는 칸을 눈에 띄게 하려는 표시입니다.
      .replace(/\{\{(.+?)\}\}/g, '<em class="need">$1</em>')
      // [글](주소). 주소는 http(s)만 받습니다. javascript: 같은 것이
      // 들어오면 링크로 만들지 않고 글자 그대로 둡니다.
      .replace(/\[([^\]]+)\]\((https?:&#x2F;&#x2F;[^)\s]+|https?:\/\/[^)\s]+)\)/g,
        (whole, label, url) => {
          const clean = url.replace(/&#x2F;/g, "/");
          return `<a href="${clean}" target="_blank" rel="noopener">${label}</a>`;
        })
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  // 로그아웃하면 그 회원의 대화를 지웁니다. 같은 컴퓨터를 다른 사람이 쓸 수 있습니다.
  document.addEventListener("submit", (event) => {
    if (event.target.closest && event.target.closest(".nav_logout")) ForwardusChat.clear("logout");
  });

  window.ForwardusChat = ForwardusChat;
})();
