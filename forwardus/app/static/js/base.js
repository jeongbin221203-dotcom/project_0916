/* Shared helpers and global UI behavior. */
(function () {
  "use strict";

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  const REQUEST_TIMEOUT_MS = 20000;

  async function requestJson(url, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      try {
        return await response.json();
      } catch (error) {
        return {
          success: false,
          error_code: "INVALID_RESPONSE",
          message: `서버 응답을 해석하지 못했습니다 (HTTP ${response.status}). 다른 서버가 같은 포트를 쓰고 있지 않은지 확인하세요.`,
        };
      }
    } catch (error) {
      const timedOut = error.name === "AbortError";
      return {
        success: false,
        error_code: timedOut ? "TIMEOUT" : "NETWORK_ERROR",
        message: timedOut ? "서버 응답 시간이 초과되었습니다." : "서버와 통신하지 못했습니다. 서버가 실행 중인지 확인하세요.",
      };
    } finally {
      clearTimeout(timer);
    }
  }

  const getJson = (url) => requestJson(url, { headers: { Accept: "application/json" } });
  const postJson = (url, body) => requestJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });

  function formatNumber(value, digits = 0) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
    return Number(value).toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function toIsoDate(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  /* ----- 숫자 입력칸: 천 단위 쉼표 ----- */
  // 화면에는 1,000처럼 보여주고 서버에는 쉼표를 뗀 값을 보냅니다.
  function plainNumber(value) {
    return String(value ?? "").replace(/,/g, "").trim();
  }

  function groupDigits(value) {
    const text = plainNumber(value);
    if (!text || !/^-?\d*\.?\d*$/.test(text)) return text;
    const [whole, fraction] = text.split(".");
    const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return fraction === undefined ? grouped : `${grouped}.${fraction}`;
  }

  function setupNumberInput(input) {
    const step = Number(input.dataset.step || 1);
    const min = input.dataset.min === undefined ? null : Number(input.dataset.min);
    const max = input.dataset.max === undefined ? null : Number(input.dataset.max);

    const format = () => {
      // 커서가 뒤에서 몇 번째인지 기억했다가 쉼표를 넣은 뒤 같은 자리로 돌려놓습니다.
      const fromEnd = input.value.length - (input.selectionStart ?? input.value.length);
      input.value = groupDigits(input.value);
      const caret = Math.max(0, input.value.length - fromEnd);
      try { input.setSelectionRange(caret, caret); } catch (error) { /* 무시 */ }
    };

    input.addEventListener("input", format);
    input.addEventListener("blur", () => { input.value = groupDigits(input.value); });
    // 위아래 화살표로 값을 올리고 내립니다. (숫자 입력칸의 화살표 대신)
    input.addEventListener("keydown", (event) => {
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      event.preventDefault();
      const current = Number(plainNumber(input.value)) || 0;
      let next = current + (event.key === "ArrowUp" ? step : -step);
      if (min !== null) next = Math.max(min, next);
      if (max !== null) next = Math.min(max, next);
      input.value = groupDigits(String(Math.round(next * 1000) / 1000));
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    input.value = groupDigits(input.value);
  }

  document.querySelectorAll("input[data-number]").forEach(setupNumberInput);

  // 우리 코드는 숫자 입력칸에 hidden을 붙이지 않습니다. 그런데도 붙는다면 브라우저
  // 확장 프로그램 등 바깥 스크립트가 한 것이므로 곧바로 되돌리고 콘솔에 남깁니다.
  const unhide = new MutationObserver((records) => {
    records.forEach((record) => {
      const input = record.target;
      if (input.matches && input.matches("input[data-number]") && input.hidden) {
        input.hidden = false;
        console.warn(`[FORWARDUS] 외부 스크립트가 입력칸(${input.name || input.dataset.line})을 숨겨 다시 보이게 했습니다.`
          + " 확장 프로그램을 끄거나 시크릿 창에서 확인해 주세요.");
      }
    });
  });
  unhide.observe(document.body, { attributes: true, attributeFilter: ["hidden"], subtree: true });

  window.Forwardus = { escapeHtml, getJson, postJson, formatNumber, toIsoDate,
                       plainNumber, groupDigits, setupNumberInput };

  const toggle = document.querySelector("[data-nav-toggle]");
  const nav = document.querySelector("[data-nav]");
  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // 날짜 칸은 어디를 눌러도 달력이 열리게 합니다. (기본 동작은 달력 아이콘만)
  document.querySelectorAll('input[type="date"]').forEach((input) => {
    const open = () => {
      if (typeof input.showPicker === "function") {
        try {
          input.showPicker();
        } catch (error) {
          /* 브라우저가 막으면 기본 동작을 씁니다. */
        }
      }
    };
    input.addEventListener("click", open);
    input.addEventListener("focus", open);
  });

  /* ----- 새로고침·로고 클릭은 "처음부터 다시" ----- */
  // 입력하던 내용은 탭 세션에 임시 저장됩니다(메뉴를 오가도 유지).
  // 새로고침하거나 회사 로고를 누르면 그 내용을 지우고 첫 화면으로 돌아갑니다.
  const DRAFT_KEY = "forwardus:planning-draft";
  const brand = document.querySelector(".brand");
  const homeUrl = brand ? brand.getAttribute("href") : "/";

  function clearDraft() {
    [window.sessionStorage, window.localStorage].forEach((store) => {
      try { store.removeItem(DRAFT_KEY); } catch (error) { /* 무시 */ }
    });
  }

  function isReload() {
    const entry = (window.performance && window.performance.getEntriesByType)
      ? window.performance.getEntriesByType("navigation")[0] : null;
    return entry ? entry.type === "reload" : false;
  }

  if (isReload()) {
    clearDraft();
    if (window.location.pathname !== homeUrl) {
      window.location.replace(homeUrl);
      return;
    }
  }
  if (brand) brand.addEventListener("click", clearDraft);

  document.querySelectorAll(".flash_stack .flash").forEach((el) => {
    setTimeout(() => el.classList.add("fade"), 6000);
  });
})();
