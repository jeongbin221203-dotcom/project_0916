/* Trade document view helpers. */
(function () {
  "use strict";

  document.querySelectorAll("[data-print]").forEach((button) => {
    button.addEventListener("click", () => window.print());
  });

  // Dashboard의 "PDF 저장"으로 들어오면(?print=1) 화면이 그려진 뒤 인쇄 창을 바로 엽니다.
  // 인쇄 창에서 "PDF로 저장"을 고르면 내려받기가 됩니다.
  if (new URLSearchParams(window.location.search).get("print") === "1") {
    window.addEventListener("load", () => window.print(), { once: true });
  }
})();
