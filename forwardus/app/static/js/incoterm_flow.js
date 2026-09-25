/* 인코텀즈 흐름 그림 색칠 — 운송 계획 화면과 인코텀즈 화면이 함께 씁니다.

   비용과 위험을 한 막대로 합치지 않습니다. C조건(CFR·CIF·CPT·CIP)은 판매자가
   주운송 운임까지 내지만 위험은 출발지 쪽에서 이미 넘어가, 두 막대의 끝이 다릅니다.
   이 규칙이 두 군데에 따로 적혀 있으면 한쪽만 고쳐져 그림이 갈라집니다.

   term.flow.costs   단계별 비용 부담 S 판매자 / B Buyer / C 운송계약 확인 / P 인도 장소에 따라
   term.flow.risk_at 위험이 넘어가는 단계 경계(0~8). [a, b]면 약정 장소에 따라 그 사이입니다. */
(function () {
  "use strict";

  const COST_TEXT = { S: "판매자", B: "Buyer", C: "운송계약 확인", P: "인도 장소에 따라" };
  const RISK_TEXT = { S: "판매자", B: "Buyer", P: "인도지에 따라" };

  function escapeHtml(text) {
    return window.Forwardus ? window.Forwardus.escapeHtml(text) : String(text);
  }

  function runs(values, prefix, texts) {
    const groups = [];
    values.forEach((value, index) => {
      const last = groups[groups.length - 1];
      if (last && last.value === value) last.end = index + 1;
      else groups.push({ value, start: index, end: index + 1 });
    });
    return groups.map((run) => `<span class="fbar ${prefix}_${run.value}" style="grid-column: ${run.start + 1} / ${run.end + 1}">`
      + `${escapeHtml(texts[run.value])}</span>`).join("");
  }

  function mark(at, label, total) {
    const edge = at === 0 ? " at_start" : at === total ? " at_end" : "";
    return `<span class="fmark${edge}" style="--at: ${at}">${label ? `<span>${escapeHtml(label)}</span>` : ""}</span>`;
  }

  /* root 안의 흐름 그림을 term에 맞게 칠합니다. term이 없으면 지웁니다.
     total은 단계 수(보통 8)입니다. */
  function render(root, term, total) {
    const scope = root || document;
    const bars = scope.querySelector("[data-flow-bars]");
    const legend = scope.querySelector("[data-flow-legend]");
    const chips = scope.querySelectorAll("[data-flow-chips]");
    const stepEls = scope.querySelectorAll(".flow_step");
    if (!bars) return;
    stepEls.forEach((el) => el.classList.remove("risk_edge", "cost_edge"));
    if (!term || !term.flow) {
      bars.hidden = true;
      if (legend) legend.hidden = true;
      chips.forEach((el) => { el.innerHTML = ""; });
      return;
    }
    const steps = total || stepEls.length || 8;
    const costs = term.flow.costs.split("");
    const [riskFrom, riskTo] = Array.isArray(term.flow.risk_at)
      ? term.flow.risk_at : [term.flow.risk_at, term.flow.risk_at];
    const risks = costs.map((_, index) => (index < riskFrom ? "S" : index < riskTo ? "P" : "B"));
    // 판매자 비용이 끝나는 경계: 판매자(S)가 이어지는 마지막 단계 뒤
    let costEnd = 0;
    while (costEnd < steps && costs[costEnd] === "S") costEnd += 1;

    bars.querySelector('[data-flow-bar="cost"]').innerHTML = runs(costs, "c", COST_TEXT)
      + (costEnd > 0 && costEnd < steps ? mark(costEnd, "비용 이전", steps) : "");
    bars.querySelector('[data-flow-bar="risk"]').innerHTML = runs(risks, "r", RISK_TEXT)
      + (riskFrom === riskTo ? mark(riskFrom, "위험 이전", steps)
        : mark(riskFrom, "위험 이전 범위", steps) + mark(riskTo, "", steps));
    bars.hidden = false;
    if (legend) {
      legend.hidden = false;
      legend.querySelector(".lg_contract").hidden = !costs.includes("C");
      legend.querySelector(".lg_place").hidden = !(costs.includes("P") || riskFrom !== riskTo);
    }
    chips.forEach((el, index) => {
      el.innerHTML = `<span class="chip c_${costs[index]}">비용 ${escapeHtml(COST_TEXT[costs[index]])}</span>`
        + `<span class="chip r_${risks[index]}">위험 ${escapeHtml(RISK_TEXT[risks[index]])}</span>`;
    });
    if (stepEls[riskFrom]) stepEls[riskFrom].classList.add("risk_edge");
    if (costEnd < steps && stepEls[costEnd]) stepEls[costEnd].classList.add("cost_edge");
  }

  window.ForwardusIncotermFlow = { render, COST_TEXT, RISK_TEXT };
})();
