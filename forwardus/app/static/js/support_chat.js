/* 고객 상담 — 화면 오른쪽 아래 고래 버튼으로 열리는 상담창.

   대화는 시작 화면의 세 탭과 한 줄기로 이어집니다(chat_store.js).
   탭에서 나눈 말도 여기에 그대로 보이고, 다른 화면으로 옮겨 가면
   이 창이 저절로 열려 하던 대화를 이어 갑니다.
   시작 화면에서는 단추만 두고 저절로 열지 않습니다. 거기서 대화가 시작되면
   같은 대화가 가운데에 크게 뜨므로 단추와 창을 숨깁니다(home.js). */
(function () {
  "use strict";

  const config = window.FORWARDUS_SUPPORT;
  const fab = document.querySelector("[data-support-open]");
  const panel = document.querySelector("[data-support-panel]");
  const chat = window.ForwardusChat;
  if (!config || !fab || !panel || !chat) return;

  const { postJson } = window.Forwardus;
  const log = panel.querySelector("[data-support-log]");
  const chips = panel.querySelector("[data-support-chips]");
  const form = panel.querySelector("[data-support-form]");
  const input = form.elements.question;
  const resetButton = panel.querySelector("[data-support-reset]");
  const SOURCE = "support";

  let busy = false;
  let lastMode = null;

  function bubble(role, html, extraClass) {
    const row = document.createElement("div");
    row.className = `support_msg support_${role}${extraClass ? ` ${extraClass}` : ""}`;
    row.innerHTML = html;
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    return row;
  }

  function plain(text) {
    // 줄바꿈은 살리고 나머지는 글자 그대로 넣습니다.
    return window.Forwardus.escapeHtml(text).replace(/\n/g, "<br>");
  }

  // 어느 탭에서 나눈 말인지 바뀌는 자리에 작은 구분선을 둡니다.
  function modeDivider(mode) {
    if (mode === lastMode) return;
    lastMode = mode;
    const label = chat.MODE_LABELS[mode] || mode;
    const row = document.createElement("div");
    row.className = "support_divider";
    row.textContent = label;
    log.appendChild(row);
  }

  function showMessage(message) {
    modeDivider(message.mode);
    if (message.role === "user") {
      bubble("user", plain(message.text));
    } else {
      bubble("bot", chat.render(message.text),
             message.kind === "note" || message.kind === "warn" ? "support_note" : "support_rich");
    }
  }

  function renderChips() {
    const items = config.intro.suggestions || [];
    chips.innerHTML = items
      .map((text) => `<button type="button" class="support_chip">${window.Forwardus.escapeHtml(text)}</button>`)
      .join("");
  }

  function renderAll() {
    log.innerHTML = "";
    lastMode = null;
    bubble("bot", plain(config.intro.greeting));
    if (!config.intro.available) {
      bubble("bot", plain(config.intro.offline_note), "support_offline");
      input.disabled = true;
      form.querySelector("button[type=submit]").disabled = true;
      chips.innerHTML = "";
      return;
    }
    const messages = chat.messages();
    messages.forEach(showMessage);
    // 추천 질문은 처음 시작할 때만 보여 줍니다.
    if (messages.length) chips.innerHTML = "";
    else renderChips();
  }

  async function send(question) {
    const text = (question || "").trim();
    if (!text || busy) return;
    busy = true;
    chips.innerHTML = "";
    input.value = "";
    const history = chat.history();
    showMessage(chat.append({ role: "user", text, mode: SOURCE }, SOURCE));

    const waiting = bubble("bot", "답변을 준비하고 있습니다…", "support_waiting");
    // 이 창은 서식을 그리지 않으니 짧은 답을 받습니다. (메인 화면은 긴 템플릿 답)
    // history는 이번 질문을 적기 전에 꺼냈으므로 잘라 낼 것이 없습니다.
    const response = await postJson(config.url, { question: text, history, style: "brief" });
    waiting.remove();

    if (response.success) {
      showMessage(chat.append({ role: "assistant", text: response.data.answer, mode: SOURCE },
                              SOURCE));
    } else {
      bubble("bot", plain(response.message || "답변을 받지 못했습니다. 잠시 후 다시 물어봐 주세요."),
             "support_offline");
    }
    busy = false;
    input.focus();
  }

  let rendered = false;
  function open({ focus = true } = {}) {
    if (!rendered) { renderAll(); rendered = true; }
    panel.hidden = false;
    fab.classList.add("is_open");
    log.scrollTop = log.scrollHeight;
    if (focus && !input.disabled) input.focus();
  }

  function close() {
    panel.hidden = true;
    fab.classList.remove("is_open");
    fab.focus();
  }

  // 다른 화면(시작 화면의 탭)에서 더한 말도 여기에 그립니다.
  chat.subscribe((event) => {
    if (event.source === SOURCE) return;
    if (event.type === "clear") { rendered = false; if (!panel.hidden) open({ focus: false }); return; }
    // 시작 화면에서 탭을 바꿔 인사가 바뀌었습니다. 쌓이지 않게 처음부터 다시 그립니다.
    if (event.type === "greeting") { if (rendered) renderAll(); return; }
    if (rendered) {
      chips.innerHTML = "";
      showMessage(event.message);
    }
  });

  fab.addEventListener("click", () => (panel.hidden ? open() : close()));
  panel.querySelector("[data-support-close]").addEventListener("click", close);
  if (resetButton) {
    resetButton.addEventListener("click", () => {
      if (busy || !chat.messages().length) return;
      if (!window.confirm("지금까지의 대화를 지우고 새로 시작할까요?")) return;
      chat.clear(SOURCE);
      renderAll();
      input.focus();
    });
  }
  chips.addEventListener("click", (event) => {
    const chip = event.target.closest(".support_chip");
    if (chip) send(chip.textContent);
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(input.value);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) close();
  });

  // 창은 저절로 열지 않습니다. 기본은 늘 닫힘이고, 오른쪽 아래 단추를 눌렀을 때만 열립니다.
  // (예전에는 다른 화면에 들어오면 저절로 열려 화면 제목을 가렸습니다)
})();
