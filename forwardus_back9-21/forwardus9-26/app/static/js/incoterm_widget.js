/* 대화 답변 안에 들어가는 인코텀즈 표.

   "인코텀즈가 뭔가요"라고 물으면 글만 주는 대신 **그 자리에서 눌러 보는 표**를 답니다.
   화면을 옮기지 않습니다. 답을 읽던 자리에서 EXW·FOB·CIF를 번갈아 눌러 보고,
   비용과 위험이 어느 단계에서 넘어가는지 그림으로 확인합니다.

   그림 색칠(incoterm_flow.js)과 모양(incoterm.css)은 운송 계획·인코텀즈 화면과
   같은 것을 씁니다. 자료(11개 조건)는 서버에서 한 번만 받아 두고 다시 씁니다. */
(function () {
  "use strict";

  const { escapeHtml, getJson } = window.Forwardus;
  const URL = "/lookup/api/incoterms";
  const ICONS = {
    factory: '<path d="M3 20V10l5 3V10l5 3V6h3v14z"/><path d="M16 6V3h3v17"/><path d="M6 17h2M11 17h2"/>',
    truck: '<path d="M2 6h11v10H2z"/><path d="M13 9h4l3 3v4h-7"/><circle cx="6" cy="17.5" r="1.8"/><circle cx="16.5" cy="17.5" r="1.8"/>',
    terminal: '<path d="M3 20h18"/><path d="M4 20v-6h7v6M13 20v-9h7v9"/><path d="M4 17h7M13 14h7M13 17h7"/>',
    crane: '<path d="M6 21V4l12 3"/><path d="M6 7h13"/><path d="M16 7v5"/><path d="M14 12h4v3h-4z"/><path d="M3 21h8"/>',
    main: '<path d="M3 15l2 4h14l2-4z"/><path d="M6 15V9h12v6"/><path d="M9 9V6h6v3"/><path d="M2 21c2 0 2-1 4-1s2 1 4 1 2-1 4-1 2 1 4 1 2-1 4-1"/>',
    warehouse: '<path d="M3 21V9l9-5 9 5v12"/><path d="M7 21v-8h10v8"/><path d="M7 16h10"/>',
  };
  const DUTY_LABELS = {
    export: "수출통관", import: "수입통관", insurance: "보험",
    loading: "싣기", unloading: "내리기",
  };
  const WHO = { seller: "판매자", buyer: "Buyer", none: "의무 없음", varies: "경우에 따라" };

  let loading = null;   // 자료를 받아 오는 약속. 여러 답에 표가 붙어도 한 번만 받습니다.
  let data = null;

  function load() {
    if (data) return Promise.resolve(data);
    if (!loading) {
      loading = getJson(URL).then((response) => {
        data = response && response.success ? response.data : null;
        return data;
      }).catch(() => null);
    }
    return loading;
  }

  function flowHtml(steps) {
    const items = steps.map((step, index) => `
      <li class="flow_step">
        <span class="flow_icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
             stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[step.icon] || ""}</svg></span>
        <span class="flow_label"><span class="flow_no">${index + 1}</span>${escapeHtml(step.label)}<small>${escapeHtml(step.note)}</small></span>
        <span class="flow_chips" data-flow-chips aria-hidden="true"></span>
      </li>`).join("");
    return `<figure class="incoterm_flow">
      <div class="flow_ends" aria-hidden="true"><span>판매자(Seller) 쪽</span><span>Buyer 쪽</span></div>
      <ol class="flow_track">${items}</ol>
      <div class="flow_bars" data-flow-bars aria-hidden="true" hidden>
        <div class="flow_bar_row"><span class="flow_bar_title">비용 부담</span><div class="flow_bar" data-flow-bar="cost"></div></div>
        <div class="flow_bar_row"><span class="flow_bar_title">위험 부담</span><div class="flow_bar" data-flow-bar="risk"></div></div>
      </div>
      <div class="flow_legend" data-flow-legend aria-hidden="true" hidden>
        <span class="lg lg_cost">판매자 비용</span>
        <span class="lg lg_risk">판매자 위험</span>
        <span class="lg lg_buyer">Buyer 부담</span>
        <span class="lg lg_contract">운송계약 확인</span>
        <span class="lg lg_place">인도 장소에 따라</span>
      </div>
    </figure>`;
  }

  function dutyRows(term) {
    const duties = term.duties || {};
    return Object.keys(DUTY_LABELS).filter((key) => duties[key]).map((key) => {
      const [who, note] = duties[key];
      return `<tr><th scope="row">${escapeHtml(DUTY_LABELS[key])}</th>`
        + `<td><span class="duty_who who_${escapeHtml(who)}">${escapeHtml(WHO[who] || who)}</span></td>`
        + `<td>${escapeHtml(note)}</td></tr>`;
    }).join("");
  }

  function detailHtml(term) {
    const mode = term.sea_only ? "해상·내수로 전용" : "모든 운송수단";
    return `
      <header class="incoterm_detail_head">
        <h2>${escapeHtml(term.code)} · ${escapeHtml(term.name)}</h2>
        <p class="incoterm_detail_sub">${escapeHtml(term.label)} · ${escapeHtml(mode)}</p>
      </header>
      <p class="incoterm_summary">${escapeHtml(term.summary)}</p>
      <p>${escapeHtml(term.detail)}</p>
      <dl class="tip_facts">
        <div><dt>판매자 주요 비용</dt><dd>${escapeHtml(term.seller_cost)}</dd></div>
        <div><dt>Buyer 주요 비용</dt><dd>${escapeHtml(term.buyer_cost)}</dd></div>
        <div><dt>위험 이전</dt><dd>${escapeHtml(term.risk)}</dd></div>
      </dl>
      <table class="duty_table"><caption>누가 무엇을 하나</caption><tbody>${dutyRows(term)}</tbody></table>
      <p class="incoterm_caution"><i>헷갈리기 쉬운 점</i>${escapeHtml(term.caution)}</p>`;
  }

  /* 답변 덩어리(row) 안에 표를 붙입니다. start는 처음 열어 둘 조건입니다. */
  function attach(row, start) {
    if (!row) return;
    const box = document.createElement("div");
    box.className = "incoterm_widget";
    box.innerHTML = '<p class="incoterm_widget_wait">인코텀즈 표를 불러오는 중입니다…</p>';
    // 글보다 표가 먼저입니다. 눌러 보면 바로 알 수 있는 것을 아래로 내리면
    // 사람은 긴 글부터 읽다가 표가 있는 줄도 모르고 지나갑니다.
    row.prepend(box);

    load().then((loaded) => {
      if (!loaded || !(loaded.terms || []).length) {
        // 자료를 못 받았으면 표 대신 화면으로 가는 길만 남깁니다. 빈 칸을 두지 않습니다.
        box.innerHTML = '<p class="incoterm_widget_wait">'
          + '<a href="/lookup/incoterms">📊 인코텀즈 한눈에 보기 화면에서 확인하기</a></p>';
        return;
      }
      const byCode = Object.fromEntries(loaded.terms.map((term) => [term.code, term]));
      const cards = loaded.terms.map((term) => `
        <div class="incoterm_card" data-incoterm="${escapeHtml(term.code)}">
          <button type="button" class="incoterm_pick" data-widget-pick="${escapeHtml(term.code)}"
                  aria-pressed="false">${escapeHtml(term.code)}</button>
        </div>`).join("");
      box.innerHTML = `
        <p class="incoterm_widget_title">조건을 눌러 보세요. 비용과 위험이 어디서 넘어가는지 그림이 바뀝니다.</p>
        ${flowHtml(loaded.steps)}
        <div class="incoterm_area"><div class="incoterm_grid">${cards}</div></div>
        <div class="incoterm_detail" data-widget-detail></div>
        <p class="incoterm_widget_more"><a href="/lookup/incoterms">📊 큰 화면에서 보기</a></p>`;

      const detail = box.querySelector("[data-widget-detail]");
      function show(code) {
        const term = byCode[code];
        if (!term) return;
        detail.innerHTML = detailHtml(term);
        box.querySelectorAll("[data-widget-pick]").forEach((button) => {
          const on = button.dataset.widgetPick === code;
          button.setAttribute("aria-pressed", on ? "true" : "false");
          button.closest(".incoterm_card").classList.toggle("active", on);
        });
        window.ForwardusIncotermFlow.render(box, term, loaded.steps.length);
      }
      box.querySelectorAll("[data-widget-pick]").forEach((button) => {
        button.addEventListener("click", () => show(button.dataset.widgetPick));
      });
      show(byCode[String(start || "").toUpperCase()] ? start.toUpperCase() : loaded.terms[0].code);
    });
  }

  window.ForwardusIncotermWidget = { attach };
})();
