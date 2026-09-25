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

  const { postJson, escapeHtml } = window.Forwardus;
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
    return escapeHtml(text).replace(/\n/g, "<br>");
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

  // 그린 말풍선을 돌려줍니다. 답 아래에 관련 링크를 덧붙이는 데 씁니다.
  function showMessage(message) {
    modeDivider(message.mode);
    if (message.role === "user") {
      return bubble("user", plain(message.text));
    }
    return bubble("bot", chat.render(message.text),
                  message.kind === "note" || message.kind === "warn" ? "support_note" : "support_rich");
  }

  function renderChips() {
    const items = config.intro.suggestions || [];
    chips.innerHTML = items
      .map((text) => `<button type="button" class="support_chip">${escapeHtml(text)}</button>`)
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
      const row = showMessage(chat.append({ role: "assistant", text: response.data.answer, mode: SOURCE },
                                          SOURCE));
      appendLinks(row, response.data.links);
    } else {
      bubble("bot", plain(response.message || "답변을 받지 못했습니다. 잠시 후 다시 물어봐 주세요."),
             "support_offline");
    }
    busy = false;
    input.focus();
  }

  // 답 아래의 관련 링크. 주소는 서버 표에서만 옵니다. (support_chat_service · answer_links)
  function appendLinks(row, links) {
    if (!row || !(links || []).length) return;
    const box = document.createElement("p");
    box.className = "answer_links";
    box.innerHTML = links.map((link) => {
      const outside = /^https?:/.test(link.url);
      const attrs = outside ? ` target="_blank" rel="noopener"` : "";
      return `<a class="answer_link${outside ? " is_outside" : ""}" href="${escapeHtml(link.url)}"${attrs}>`
        + `${escapeHtml(link.label)}${outside ? " ↗" : ""}</a>`;
    }).join("");
    row.appendChild(box);
  }

  let rendered = false;
  function open({ focus = true } = {}) {
    if (!rendered) { renderAll(); rendered = true; }
    panel.hidden = false;
    fab.classList.add("is_open");
    log.scrollTop = log.scrollHeight;
    if (focus && !input.disabled) input.focus();
  }

  // focus: 접은 뒤 [고객 상담] 단추로 초점을 되돌릴지.
  // 닫기(×)나 Esc로 접을 때는 되돌립니다 — 키보드만 쓰는 사람이 초점을
  // 잃으면 화면 맨 처음부터 다시 훑어야 합니다.
  // 바깥을 눌러 접을 때는 되돌리지 않습니다. 방금 누른 곳에서 초점을
  // 빼앗아 오면 누른 단추가 안 눌립니다.
  function close({ focus = true } = {}) {
    panel.hidden = true;
    fab.classList.remove("is_open");
    if (focus) fab.focus();
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
  panel.querySelector("[data-support-close]").addEventListener("click", () => close());

  // 창 바깥을 누르면 접습니다.
  //
  // 이 창은 화면 오른쪽 아래를 덮습니다. 뒤에 있는 서류 카드나 단추를 누르려다
  // 창에 가려 못 누르는 일이 있었습니다. 닫기(×)를 찾아 누르게 하는 것보다,
  // 쓰던 곳을 그냥 누르면 비켜 주는 편이 자연스럽습니다.
  //
  // 적던 글이 있으면 접지 않습니다. 물어보려고 쓰다가 잠깐 딴 곳을 봤을 뿐인데
  // 글이 사라지면 처음부터 다시 써야 합니다. (대화 내용은 chat이 들고 있어
  // 접었다 펴도 남지만, 아직 보내지 않은 글은 입력칸에만 있습니다)
  document.addEventListener("pointerdown", (event) => {
    if (panel.hidden) return;
    if (panel.contains(event.target) || fab.contains(event.target)) return;
    if (input.value.trim()) return;
    close({ focus: false });
  });

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
