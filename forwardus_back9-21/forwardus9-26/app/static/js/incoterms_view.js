/* 인코텀즈 화면(/lookup/incoterms) — 조건을 눌러 세부 내용을 봅니다.

   여기서는 조건을 "고르는" 것이 아니라 "읽는" 것입니다. 그래서 운송 계획 화면과 달리
   radio도 팝업도 없습니다. 누른 조건의 내용이 아래 칸에서 바뀌고, 위의 흐름 그림이
   그 조건에 맞게 칠해집니다. 주소에 #FOB 처럼 적어 두면 그 조건이 열린 채로 시작합니다. */
(function () {
  "use strict";

  const data = window.FORWARDUS_INCOTERMS;
  const detail = document.querySelector("[data-incoterm-detail]");
  if (!data || !detail) return;

  const { escapeHtml } = window.Forwardus;
  const byCode = Object.fromEntries(data.terms.map((term) => [term.code, term]));
  const DUTY_LABELS = {
    export: "수출통관", import: "수입통관", insurance: "보험",
    loading: "싣기", unloading: "내리기",
  };
  // 의무를 누가 지는지. 글자 색만으로 알리지 않고 말로도 적습니다.
  const WHO = { seller: "판매자", buyer: "Buyer", none: "의무 없음", varies: "경우에 따라" };

  function dutyRows(term) {
    const duties = term.duties || {};
    return Object.keys(DUTY_LABELS).filter((key) => duties[key]).map((key) => {
      const [who, note] = duties[key];
      return `<tr><th scope="row">${escapeHtml(DUTY_LABELS[key])}</th>`
        + `<td><span class="duty_who who_${escapeHtml(who)}">${escapeHtml(WHO[who] || who)}</span></td>`
        + `<td>${escapeHtml(note)}</td></tr>`;
    }).join("");
  }

  function render(code) {
    const term = byCode[code];
    if (!term) return;
    const mode = term.sea_only ? "해상·내수로 전용" : "모든 운송수단";
    detail.innerHTML = `
      <header class="incoterm_detail_head">
        <h2>${escapeHtml(term.code)} · ${escapeHtml(term.name)}</h2>
        <p class="incoterm_detail_sub">${escapeHtml(term.label)} · ${escapeHtml(mode)}
          · ${escapeHtml(term.group)}그룹</p>
      </header>
      <p class="incoterm_summary">${escapeHtml(term.summary)}</p>
      <p>${escapeHtml(term.detail)}</p>
      <dl class="tip_facts">
        <div><dt>판매자 주요 비용</dt><dd>${escapeHtml(term.seller_cost)}</dd></div>
        <div><dt>Buyer 주요 비용</dt><dd>${escapeHtml(term.buyer_cost)}</dd></div>
        <div><dt>위험 이전</dt><dd>${escapeHtml(term.risk)}</dd></div>
      </dl>
      <table class="duty_table">
        <caption>누가 무엇을 하나</caption>
        <tbody>${dutyRows(term)}</tbody>
      </table>
      <p class="incoterm_caution"><i>헷갈리기 쉬운 점</i>${escapeHtml(term.caution)}</p>`;

    document.querySelectorAll("[data-incoterm-view]").forEach((button) => {
      const on = button.dataset.incotermView === code;
      button.setAttribute("aria-selected", on ? "true" : "false");
      button.closest(".incoterm_card").classList.toggle("active", on);
    });
    window.ForwardusIncotermFlow.render(document, term, data.steps.length);
  }

  document.querySelectorAll("[data-incoterm-view]").forEach((button) => {
    button.addEventListener("click", () => {
      const code = button.dataset.incotermView;
      render(code);
      // 뒤로 가기로 앞서 보던 조건으로 돌아갈 수 있게 주소에 남깁니다.
      history.replaceState(null, "", `#${code}`);
    });
  });

  const asked = decodeURIComponent(location.hash.replace("#", "")).toUpperCase();
  render(byCode[asked] ? asked : data.terms[0].code);
})();
