/* 고객 상담 — 화면 오른쪽 아래 버튼으로 열리는 상담창. */
(function () {
  "use strict";

  const config = window.FORWARDUS_SUPPORT;
  const fab = document.querySelector("[data-support-open]");
  const panel = document.querySelector("[data-support-panel]");
  if (!config || !fab || !panel) return;

  const { escapeHtml, postJson } = window.Forwardus;
  const log = panel.querySelector("[data-support-log]");
  const chips = panel.querySelector("[data-support-chips]");
  const form = panel.querySelector("[data-support-form]");
  const input = form.elements.question;

  // 대화는 이 화면에서만 살아 있습니다. 서버에 쌓아 두지 않습니다.
  const history = [];
  let busy = false;

  function bubble(role, text, extraClass) {
    const row = document.createElement("div");
    row.className = `support_msg support_${role}${extraClass ? ` ${extraClass}` : ""}`;
    // 줄바꿈은 살리고 나머지는 글자 그대로 넣습니다.
    row.innerHTML = escapeHtml(text).replace(/\n/g, "<br>");
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
    return row;
  }

  function renderChips() {
    const items = config.intro.suggestions || [];
    chips.innerHTML = items
      .map((text) => `<button type="button" class="support_chip">${escapeHtml(text)}</button>`)
      .join("");
  }

  let started = false;
  function start() {
    if (started) return;
    started = true;
    bubble("bot", config.intro.greeting);
    if (!config.intro.available) {
      bubble("bot", config.intro.offline_note, "support_offline");
      input.disabled = true;
      form.querySelector("button").disabled = true;
      return;
    }
    renderChips();
  }

  async function send(question) {
    const text = (question || "").trim();
    if (!text || busy) return;
    busy = true;
    chips.innerHTML = "";
    input.value = "";
    bubble("user", text);
    history.push({ role: "user", content: text });

    const waiting = bubble("bot", "답변을 준비하고 있습니다…", "support_waiting");
    const response = await postJson(config.url, { question: text, history: history.slice(0, -1) });
    waiting.remove();

    if (response.success) {
      const answer = response.data.answer;
      bubble("bot", answer);
      history.push({ role: "assistant", content: answer });
    } else {
      bubble("bot", response.message || "답변을 받지 못했습니다. 잠시 후 다시 물어봐 주세요.",
             "support_offline");
    }
    busy = false;
    input.focus();
  }

  function open() {
    panel.hidden = false;
    fab.classList.add("is_open");
    start();
    if (!input.disabled) input.focus();
  }

  function close() {
    panel.hidden = true;
    fab.classList.remove("is_open");
    fab.focus();
  }

  fab.addEventListener("click", () => (panel.hidden ? open() : close()));
  panel.querySelector("[data-support-close]").addEventListener("click", close);
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
})();
