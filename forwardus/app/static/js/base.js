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

  window.Forwardus = { escapeHtml, getJson, postJson, formatNumber, toIsoDate };

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

  document.querySelectorAll(".flash_stack .flash").forEach((el) => {
    setTimeout(() => el.classList.add("fade"), 6000);
  });
})();
