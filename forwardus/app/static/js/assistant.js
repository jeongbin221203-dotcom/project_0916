/* AI Export Assistant question box. */
(function () {
  "use strict";

  const { escapeHtml, postJson } = window.Forwardus;
  const form = document.querySelector("[data-ask-form]");
  if (!form) return;
  const answer = document.querySelector("[data-answer]");

  async function ask(question) {
    answer.hidden = false;
    answer.innerHTML = `<p class="muted">데이터를 확인하고 있습니다…</p>`;
    const response = await postJson(form.dataset.url, { question });
    if (!response.success) {
      answer.innerHTML = `<p class="error_text">${escapeHtml(response.message)}</p>`;
      return;
    }
    const data = response.data;
    const actions = data.actions.length
      ? `<p><b>확인 권장사항</b></p><ol>${data.actions.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ol>`
      : "";
    answer.innerHTML = `
      <p class="eyebrow">${escapeHtml(data.title)}</p>
      ${data.lines.map((line) => `<p>${escapeHtml(line)}</p>`).join("")}
      ${actions}`;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    ask(form.question.value);
  });

  document.querySelectorAll("[data-example]").forEach((chip) => {
    chip.addEventListener("click", () => {
      form.question.value = chip.textContent;
      ask(chip.textContent);
    });
  });
})();
