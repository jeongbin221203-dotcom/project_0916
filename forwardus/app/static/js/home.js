/* 시작 화면. 대화가 중심이고, 칸을 채우는 화면은 사이드바에 있습니다.
   적는 칸 위의 세 단추가 무엇에 대해 이야기할지를 정합니다. */
(function () {
  "use strict";

  const config = window.FORWARDUS_HOME;
  const stage = document.querySelector("[data-home-form]");
  if (!config || !stage) return;

  const { escapeHtml, postJson } = window.Forwardus;

  const input = stage.querySelector("[data-home-input]");
  const chipsBox = stage.querySelector("[data-home-chips]");
  const sendButton = stage.querySelector(".home_send");
  const hintEl = document.querySelector("[data-home-hint]");
  const logEl = document.querySelector("[data-home-log]");
  const centerEl = document.querySelector("[data-home-center]");

  let current = config.actions[0];
  // 대화는 이어서 봅니다. 서버가 뒤쪽 몇 개만 씁니다.
  const history = [];
  // 어느 모드에서 처음 인사를 건넸는지. 같은 말을 두 번 하지 않으려고 둡니다.
  const greeted = new Set();

  // 한 번 묻고 나면 인사를 접고 적는 칸을 화면 아래에 붙입니다.
  // 답이 쌓이는 동안에도 다시 묻는 자리가 늘 같은 곳에 있어야 합니다.
  function startTalking() {
    centerEl.classList.add("talking");
  }

  /* ----- 무엇에 대해 이야기할지 ----- */
  function showAction(action, { greet = false } = {}) {
    current = action;
    input.placeholder = action.placeholder;
    hintEl.innerHTML = action.hint;
    // 칸을 채우는 단추는 성격이 달라 맨 앞에 따로 둡니다.
    const fill = action.fill_label
      ? `<button type="button" class="chip_fill" data-home-fill>${escapeHtml(action.fill_label)}</button>`
      : "";
    chipsBox.innerHTML = fill + (action.examples || [])
      .map((text) => `<button type="button" data-home-chip>${escapeHtml(text)}</button>`)
      .join("");
    if (logEl.children.length) logEl.hidden = false;

    // 사람이 무엇부터 적어야 할지 모르는 것이 가장 흔한 막힘입니다.
    // 단추를 누르면 우리가 먼저 말을 겁니다.
    if (greet && action.opener && !greeted.has(action.key)) {
      greeted.add(action.key);
      say("bot", action.opener);
    }
    resize();
  }

  document.querySelectorAll("[data-home-action]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-home-action]").forEach((other) => {
        const on = other === button;
        other.classList.toggle("active", on);
        other.setAttribute("aria-selected", on ? "true" : "false");
      });
      const picked = config.actions.find((a) => a.key === button.dataset.homeAction);
      showAction(picked || config.actions[0], { greet: true });
      input.focus();
    });
  });

  chipsBox.addEventListener("click", (event) => {
    if (event.target.closest("[data-home-fill]")) { fillDocDraft(); return; }
    const chip = event.target.closest("[data-home-chip]");
    if (!chip) return;
    input.value = chip.textContent;
    resize();
    input.focus();
  });

  /* ----- 적은 글로 서류 초안 채우기 ----- */
  async function fillDocDraft() {
    const text = input.value.trim();
    if (text.length < 5) {
      say("bad", "보내실 화물을 적어 주세요. 어디서 어디로, 무엇을 몇 개 보내는지요.");
      return;
    }
    const button = chipsBox.querySelector("[data-home-fill]");
    button.disabled = true;
    const waiting = say("bot wait", "적으신 내용을 읽고 있습니다…");

    const response = await postJson(config.intakeUrl, { text }, 60000);
    button.disabled = false;
    waiting.remove();

    if (!response.success) {
      say("bad", response.message);
      return;
    }
    // 서류 작성 화면이 집어 갈 수 있게 놓아 둡니다. 탭을 새로 열면
    // 사라지는 것이 맞습니다 — 확정은 그 화면에서 사람이 합니다.
    try {
      window.sessionStorage.setItem("forwardus:doc-draft",
                                    JSON.stringify(response.data.form));
    } catch (error) {
      /* 저장 공간이 없으면 링크만 드립니다. */
    }

    // 무엇을 채웠고 무엇이 비었는지 말해 줍니다. 조용히 채우면 확인을 안 합니다.
    const filled = response.data.filled.length;
    const notes = response.data.notes.length
      ? "\n\n확인해 주세요\n" + response.data.notes.map((note) => `- ${note}`).join("\n")
      : "";
    // 화면을 대신 넘기지 않습니다. 넘기면 이 안내가 가려져서, 무엇이 확인이
    // 필요한 값인지 모른 채 그대로 서류가 만들어집니다.
    say("bot", `칸 ${filled}개를 채웠습니다.` + notes);
    const link = say("bot", "");
    link.innerHTML = `<a class="button primary" href="${escapeHtml(config.docFormUrl)}">`
      + "서류 작성 화면에서 확인하기 →</a>";
    input.value = "";
    resize();
  }

  /* ----- 적는 칸이 내용만큼 늘어나게 ----- */
  function resize() {
    input.style.height = "auto";
    input.style.height = `${input.scrollHeight}px`;
  }
  input.addEventListener("input", resize);

  // Enter로 보내고, Shift+Enter로 줄을 바꿉니다.
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      stage.requestSubmit();
    }
  });

  /* ----- 답변 그리기 -----
     AI는 **굵게**나 "- 목록" 같은 표시를 섞어 씁니다. 글자 그대로 두면
     별표가 그대로 보입니다. 서식만 살려 주되, 넣기 전에 반드시 escape합니다.
     AI가 하는 말에 <script>가 섞여 들어올 수 있습니다. */

  function inline(escaped) {
    return escaped
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function renderAnswer(text) {
    // escapeHtml을 먼저 한 번만 겁니다. 이후로는 우리가 넣는 태그만 살아 있습니다.
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
  }

  function say(kind, text) {
    const row = document.createElement("div");
    row.className = `home_msg ${kind}`;
    if (kind === "bot") {
      row.innerHTML = renderAnswer(text);
    } else {
      row.textContent = text;
    }
    logEl.hidden = false;
    logEl.appendChild(row);
    startTalking();
    // 아래에 붙은 적는 칸이 마지막 줄을 가리지 않게 그 위까지 올립니다.
    row.scrollIntoView({ behavior: "smooth", block: "end" });
    return row;
  }

  async function askSupport(question) {
    say("me", question);
    const waiting = say("bot wait", "답을 찾고 있습니다…");
    sendButton.disabled = true;

    const response = await postJson(config.chatUrl, { question, history });
    sendButton.disabled = false;
    waiting.remove();

    if (!response.success) {
      say("bad", response.message);
      return;
    }
    const answer = response.data.answer;
    say("bot", answer);
    history.push({ role: "user", content: question }, { role: "assistant", content: answer });
  }

  /* ----- 서류 만들기 -----
     "패킹리스트만 만들어줘" 같은 말을 받으면, 그 서식이 요구하는 칸만
     되묻고 채워지는 대로 초안을 그려 보여 줍니다. */
  let docDraft = {};

  async function askAgent(message) {
    say("me", message);
    const waiting = say("bot wait", "보고 있습니다…");
    sendButton.disabled = true;

    const response = await postJson(config.agentUrl, { message, draft: docDraft }, 90000);
    sendButton.disabled = false;
    waiting.remove();

    if (!response.success) {
      say("bad", response.message);
      return;
    }
    const data = response.data;
    docDraft = data.draft || docDraft;
    say("bot", data.reply);

    // AI가 확인 못 한 값이 있으면 같이 알려 줍니다. 조용히 넘어가면
    // 틀린 값이 그대로 서류가 됩니다.
    (data.notes || []).forEach((note) => say("bad", note));

    if (data.preview) showDraft(data);
  }

  function showDraft(data) {
    const row = say("bot", "");
    row.innerHTML = `
      <figure class="draft_sheet">
        <img src="${data.preview}" alt="${escapeHtml(data.title)} 초안">
      </figure>
      <div class="draft_actions">
        <button type="button" class="button primary" data-draft-pdf>PDF로 받기</button>
        <a class="button" href="${escapeHtml(config.planningUrl)}">운송 계획 잡기 →</a>
      </div>`;
    row.querySelector("[data-draft-pdf]").addEventListener("click", (event) =>
      downloadPdf(event.currentTarget, data));
  }

  async function downloadPdf(button, data) {
    button.disabled = true;
    const label = button.textContent;
    button.textContent = "만드는 중…";
    try {
      const response = await fetch(data.file_url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ draft: docDraft }),
      });
      if (!response.ok) throw new Error(String(response.status));
      // 서버에 파일을 남기지 않습니다. 받은 그대로 저장창을 띄웁니다.
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = (data.kind || "document") + "_draft.pdf";
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      say("bad", "PDF를 만들지 못했습니다. 다시 눌러 주세요.");
    }
    button.disabled = false;
    button.textContent = label;
  }

  /* ----- 보내기 ----- */
  stage.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) {
      input.focus();
      return;
    }
    input.value = "";
    resize();
    // 서류 작성에서는 서류를 만드는 창구로, 나머지는 상담으로 보냅니다.
    if (current.key === "documents") askAgent(text);
    else askSupport(text);
  });

  /* ----- 환율 계산기 -----
     송장 금액이 달러인데 원화로 얼마인지는 늘 궁금합니다.
     환율은 펼칠 때 한 번만 받아 둡니다. */
  function setupExchange() {
    const box = document.querySelector("[data-rail-fx]");
    if (!box) return () => {};

    const amountEl = box.querySelector("[data-fx-amount]");
    const fromEl = box.querySelector("[data-fx-from]");
    const toEl = box.querySelector("[data-fx-to]");
    const resultEl = box.querySelector("[data-fx-result]");
    const basisEl = box.querySelector("[data-fx-basis]");
    let rates = null;

    function calculate() {
      const amount = Number(String(amountEl.value).replace(/,/g, ""));
      const from = rates && rates[fromEl.value];
      const to = rates && rates[toEl.value];
      if (!from || !to || !Number.isFinite(amount)) { resultEl.textContent = "—"; return; }
      // rates는 "그 통화 1단위가 몇 원인지"입니다. 원을 거쳐 환산합니다.
      resultEl.textContent = ((amount * from) / to).toLocaleString("ko-KR", {
        maximumFractionDigits: toEl.value === "KRW" ? 0 : 2,
      });
    }

    [amountEl, fromEl, toEl].forEach((el) => {
      el.addEventListener("input", calculate);
      el.addEventListener("change", calculate);
    });
    box.querySelector("[data-fx-swap]").addEventListener("click", () => {
      [fromEl.value, toEl.value] = [toEl.value, fromEl.value];
      calculate();
    });

    return async function load() {
      if (rates) return;
      const response = await getJson(config.ratesUrl);
      if (!response.success) {
        basisEl.textContent = "환율을 받지 못했습니다. 잠시 뒤에 다시 열어 주세요.";
        basisEl.classList.add("is_mock");
        return;
      }
      rates = response.data;
      fillCurrencies();
      // 무슨 환율로 계산했는지 함께 보여 줍니다. 관세청이 멈추면 임시 환율로
      // 떨어지는데, 그걸 모르고 쓰면 금액이 틀립니다.
      basisEl.textContent = response.basis;
      basisEl.classList.toggle("is_mock", response.source !== "api");
      calculate();
    };

    // 고를 수 있는 통화는 실제로 환율을 받은 것뿐입니다. 없는 통화를
    // 목록에 두면 골랐을 때 계산이 안 됩니다.
    function fillCurrencies() {
      const major = ["USD", "KRW", "EUR", "JPY", "CNY"];
      const codes = Object.keys(rates).sort((a, b) => {
        const rank = (code) => (major.indexOf(code) + 1 || 99);
        return rank(a) - rank(b) || a.localeCompare(b);
      });
      [fromEl, toEl].forEach((select) => {
        const keep = select.value;
        select.innerHTML = codes.map((code) => `<option value="${code}">${code}</option>`).join("");
        select.value = codes.includes(keep) ? keep : codes[0];
      });
    }
  }

  const loadRates = setupExchange();

  /* ----- 왼쪽 줄에서 옆으로 펼치는 것들 ----- */
  // 내용이 있는 항목(최근 Shipment, 환율)은 좁은 줄에 넣을 수 없어 옆으로 펼칩니다.
  const flyouts = Array.from(document.querySelectorAll("[data-rail-flyout]"));

  function setFlyout(box, open) {
    box.querySelector(".rail_flyout").hidden = !open;
    box.querySelector("button").setAttribute("aria-expanded", open ? "true" : "false");
  }

  flyouts.forEach((box) => {
    box.querySelector("button").addEventListener("click", (event) => {
      event.stopPropagation();
      const opening = box.querySelector(".rail_flyout").hidden;
      flyouts.forEach((other) => setFlyout(other, other === box && opening));
      if (opening && box.dataset.railFx !== undefined) loadRates();
    });
  });
  // 바깥을 누르거나 Esc를 누르면 닫습니다.
  document.addEventListener("click", (event) => {
    flyouts.forEach((box) => { if (!box.contains(event.target)) setFlyout(box, false); });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") flyouts.forEach((box) => setFlyout(box, false));
  });

  showAction(current);
})();
