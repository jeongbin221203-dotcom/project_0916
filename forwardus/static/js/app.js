"use strict";

const DATA = window.FORWARDUS_DATA;
const STEP_ORDER = ["route", "terms", "cargo", "schedule", "dashboard"];
const STEP_LABELS = { route: "운송 경로", terms: "인코텀즈", cargo: "화물 정보", schedule: "스케줄", dashboard: "최종 견적" };
const MODE_LABELS = { fcl: "해상 FCL", lcl: "해상 LCL", air: "항공 AIR" };
const SOURCE_LABELS = { mock: "예상값", calculated: "직접 계산", imputed: "대체값" };
const CHART_COLORS = ["#2b66f6", "#12aa8d", "#f3a21a", "#7c62e3", "#9ba9bd", "#ed6a5a"];

const DEFAULT_STATE = {
  trade_direction: "export",
  transport_mode: "fcl",
  quote_name: "2026 북미 화장품 1차 선적",
  foreign_code: "USLAX",
  incoterm: "FOB",
  packing_type: "carton",
  hs_code: "3304.99",
  insurance_enabled: false,
  budget_krw: 5500000,
  schedule_id: "hmm-201",
  sort_schedule: "recommended",
  cargo: {
    length_cm: 60,
    width_cm: 45,
    height_cm: 40,
    box_count: 24,
    weight_per_box_kg: 18,
    declared_value_usd: 18000,
  },
};

let state = load_state();
let current_step = get_step_from_url();
let toast_timer;

function $(selector, parent = document) { return parent.querySelector(selector); }
function $$(selector, parent = document) { return [...parent.querySelectorAll(selector)]; }
function escape_html(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character]));
}
function format_krw(value) { return `${Math.round(Number(value) || 0).toLocaleString("ko-KR")}원`; }
function format_number(value, digits = 0) { return Number(value || 0).toLocaleString("ko-KR", { maximumFractionDigits: digits, minimumFractionDigits: digits }); }

function load_state() {
  try {
    const saved = JSON.parse(localStorage.getItem("forwardus_flask_quote"));
    return saved ? { ...DEFAULT_STATE, ...saved, cargo: { ...DEFAULT_STATE.cargo, ...(saved.cargo || {}) } } : structuredClone(DEFAULT_STATE);
  } catch (_error) {
    localStorage.removeItem("forwardus_flask_quote");
    return structuredClone(DEFAULT_STATE);
  }
}

function save_state() {
  localStorage.setItem("forwardus_flask_quote", JSON.stringify(state));
}

function get_step_from_url() {
  const value = new URLSearchParams(window.location.search).get("step");
  return STEP_ORDER.includes(value) ? value : "home";
}

function show_toast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(toast_timer);
  toast_timer = window.setTimeout(() => toast.classList.remove("visible"), 2500);
}

function navigate_to(step, push = true) {
  const next = step === "home" || STEP_ORDER.includes(step) ? step : "home";
  if (push) {
    const url = new URL(window.location.href);
    if (next === "home") url.searchParams.delete("step");
    else url.searchParams.set("step", next);
    history.pushState({ step: next }, "", `${url.pathname}${url.search}`);
  }
  current_step = next;
  render_page();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function render_page() {
  $$("[data-page]").forEach((panel) => panel.classList.toggle("active", panel.dataset.page === current_step));
  $("#app_main").hidden = current_step === "home";
  $$(".main_nav [data-go]").forEach((button) => button.classList.toggle("active", button.dataset.go === current_step));
  if (current_step !== "home") render_progress();
  if (current_step === "route") render_route();
  if (current_step === "terms") render_terms();
  if (current_step === "cargo") render_cargo();
  if (current_step === "schedule") void render_schedules();
  if (current_step === "dashboard") void render_dashboard();
  update_action_buttons();
}

function render_progress() {
  const index = STEP_ORDER.indexOf(current_step);
  $("#progress_text").textContent = `${index + 1} / ${STEP_ORDER.length}`;
  $("#progress_fill").style.width = `${((index + 1) / STEP_ORDER.length) * 100}%`;
  $$(".progress_steps button").forEach((button, button_index) => {
    button.classList.toggle("complete", button_index <= index);
    button.classList.toggle("active", button.dataset.go === current_step);
  });
}

function available_foreign_locations() {
  const kind = state.transport_mode === "air" ? "airport" : "port";
  return DATA.foreign_locations.filter((item) => item.kind === kind);
}

function normalize_route_state() {
  const available = available_foreign_locations();
  if (!available.some((item) => item.code === state.foreign_code)) state.foreign_code = available[0].code;
  const schedules = DATA.schedules[state.transport_mode];
  if (!schedules.some((item) => item.id === state.schedule_id)) state.schedule_id = schedules[0].id;
}

function get_route_locations() {
  normalize_route_state();
  const korea = DATA.korea_locations[state.transport_mode];
  const foreign = available_foreign_locations().find((item) => item.code === state.foreign_code);
  return {
    korea,
    foreign,
    origin: state.trade_direction === "export" ? korea : foreign,
    destination: state.trade_direction === "export" ? foreign : korea,
  };
}

function render_route() {
  normalize_route_state();
  $("#quote_name").value = state.quote_name;
  $$('[data-direction]').forEach((button) => button.classList.toggle("active", button.dataset.direction === state.trade_direction));
  $$('[data-mode]').forEach((button) => button.classList.toggle("active", button.dataset.mode === state.transport_mode));

  const locations = get_route_locations();
  const option_html = available_foreign_locations().map((item) => `<option value="${item.code}" ${item.code === state.foreign_code ? "selected" : ""}>${item.country} · ${item.name} (${item.code})</option>`).join("");
  $("#origin_select").innerHTML = option_html;
  $("#destination_select").innerHTML = option_html;
  $("#route_type_label").textContent = `${state.trade_direction.toUpperCase()} ROUTE`;
  $("#origin_code").textContent = locations.origin.code;
  $("#origin_name").textContent = locations.origin.name;
  $("#destination_code").textContent = locations.destination.code;
  $("#destination_name").textContent = locations.destination.name;

  const export_mode = state.trade_direction === "export";
  $("#origin_fixed_badge").hidden = !export_mode;
  $("#origin_fixed").hidden = !export_mode;
  $("#origin_select").hidden = export_mode;
  $("#destination_fixed_badge").hidden = export_mode;
  $("#destination_fixed").hidden = export_mode;
  $("#destination_select").hidden = !export_mode;
  $("#origin_fixed").innerHTML = `<span>${locations.korea.name}</span><small>${locations.korea.code}</small>`;
  $("#destination_fixed").innerHTML = `<span>${locations.korea.name}</span><small>${locations.korea.code}</small>`;
  $("#route_hint").textContent = state.transport_mode === "air" ? "항공 운송은 한국 거점이 인천국제공항(ICN)으로 자동 설정됩니다." : "해상 운송은 한국 거점이 부산항(KRPUS)으로 자동 설정됩니다.";
  save_state();
}

function render_terms() {
  if (state.transport_mode === "air" && ["FOB", "CFR", "CIF"].includes(state.incoterm)) state.incoterm = "FCA";
  $("#air_term_notice").hidden = state.transport_mode !== "air";
  $("#incoterm_grid").innerHTML = DATA.incoterms.map((term) => {
    const disabled = state.transport_mode === "air" && term.sea_only;
    return `<button type="button" class="incoterm_button ${term.code === state.incoterm ? "active" : ""}" data-incoterm="${term.code}" ${disabled ? "disabled" : ""}><b>${term.code}</b><span>${term.label}</span></button>`;
  }).join("");
  $$('[data-incoterm]').forEach((button) => button.addEventListener("click", () => { state.incoterm = button.dataset.incoterm; save_state(); render_terms(); }));
  const selected = DATA.incoterms.find((term) => term.code === state.incoterm);
  $("#term_name").textContent = `${selected.code} · ${selected.label}`;
  $("#risk_badge").textContent = `위험 이전: ${selected.risk}`;
  $("#seller_label").textContent = `수출자 ${selected.seller}%`;
  $("#buyer_label").textContent = `수입자 ${100 - selected.seller}%`;
  $("#seller_bar").style.width = `${selected.seller}%`;
  save_state();
}

function cargo_payload() {
  return Object.fromEntries(Object.keys(DEFAULT_STATE.cargo).map((key) => [key, Number($(`#${key}`).value)]));
}

async function request_json(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "요청 처리 중 오류가 발생했습니다.");
  return data;
}

async function update_cargo_metrics() {
  state.cargo = cargo_payload();
  save_state();
  try {
    const metrics = await request_json("/api/calculate", { method: "POST", body: JSON.stringify(state.cargo) });
    $("#metric_cbm").textContent = `${format_number(metrics.total_cbm, 3)} m³`;
    $("#metric_weight").textContent = `${format_number(metrics.total_weight_kg)} kg`;
    $("#metric_rt").textContent = `${format_number(metrics.revenue_ton, 2)} R/T`;
    $("#metric_chargeable").textContent = `${format_number(metrics.chargeable_weight_kg, 1)} kg`;
    const load = Math.min(100, metrics.total_cbm / 33.2 * 100);
    $("#container_load").hidden = state.transport_mode !== "fcl";
    $("#load_percent").textContent = `${format_number(load, 1)}%`;
    $("#load_fill").style.width = `${load}%`;
  } catch (error) {
    show_toast(error.message);
  }
}

function render_hs_codes() {
  $("#hs_code_list").innerHTML = DATA.hs_codes.map((item) => `<button type="button" class="hs_item ${item.code === state.hs_code ? "active" : ""}" data-hs-code="${item.code}"><div><b>${item.code}</b>${item.recommended ? '<span class="success_badge">추천</span>' : ""}</div><div><strong>${item.name}</strong><p>${item.regulation}</p></div><div class="rate_pair"><div><b>${item.mfn_rate}%</b><span>MFN</span></div><div><b>${item.fta_rate}%</b><span>FTA</span></div></div></button>`).join("");
  $$('[data-hs-code]').forEach((button) => button.addEventListener("click", () => { state.hs_code = button.dataset.hsCode; save_state(); render_hs_codes(); }));
}

function render_cargo() {
  $("#packing_type").innerHTML = DATA.packing_types.map((item) => `<option value="${item.value}" ${item.value === state.packing_type ? "selected" : ""}>${item.label} · ${item.note}</option>`).join("");
  const packing = DATA.packing_types.find((item) => item.value === state.packing_type);
  $("#packing_note").textContent = `✓ ${packing.label} 기준으로 견적서에 표시됩니다.`;
  Object.entries(state.cargo).forEach(([key, value]) => { $(`#${key}`).value = value; });
  $("#insurance_enabled").checked = state.insurance_enabled || ["CIF", "CIP"].includes(state.incoterm);
  $("#insurance_enabled").disabled = ["CIF", "CIP"].includes(state.incoterm);
  $("#insurance_help").textContent = ["CIF", "CIP"].includes(state.incoterm) ? "선택한 조건에서 110% 부보가 자동 적용됩니다." : "운송 중 사고와 파손에 대비합니다.";
  $("#budget_krw").value = state.budget_krw;
  render_hs_codes();
  void update_cargo_metrics();
}

async function render_schedules() {
  const locations = get_route_locations();
  $("#schedule_description").textContent = `${locations.origin.name}에서 ${locations.destination.name}까지 이용 가능한 ${MODE_LABELS[state.transport_mode]} 스케줄입니다.`;
  $("#sort_schedule").value = state.sort_schedule;
  try {
    const data = await request_json(`/api/schedules?mode=${encodeURIComponent(state.transport_mode)}&sort=${encodeURIComponent(state.sort_schedule)}`);
    $("#schedule_list").innerHTML = data.items.map((item) => `<button type="button" class="schedule_item ${item.id === state.schedule_id ? "active" : ""}" data-schedule="${item.id}"><div class="carrier_block"><span class="carrier_logo" style="background:${item.accent}">${item.carrier.slice(0, 2)}</span><div><b>${item.carrier}</b><p>${item.service}</p></div></div><div class="schedule_route"><div><b>${item.etd}</b><small>${locations.origin.name}</small></div><div class="transit"><i></i>${item.direct ? "DIRECT" : "1 STOP"}<br>${item.transit_days}일 소요</div><div class="right"><b>${item.eta}</b><small>${locations.destination.name}</small></div></div><div class="price_block"><span>${item.badge}</span><b>${format_krw(item.freight_usd * DATA.exchange_rate.rate)}</b><small>USD ${item.freight_usd.toLocaleString()} · 예상값</small></div></button>`).join("");
    $$('[data-schedule]').forEach((button) => button.addEventListener("click", () => { state.schedule_id = button.dataset.schedule; save_state(); void render_schedules(); }));
  } catch (error) {
    $("#schedule_list").innerHTML = `<div class="warning_box">${escape_html(error.message)}</div>`;
  }
}

function quote_payload() {
  return {
    trade_direction: state.trade_direction,
    transport_mode: state.transport_mode,
    incoterm: state.incoterm,
    packing_type: state.packing_type,
    hs_code: state.hs_code,
    insurance_enabled: state.insurance_enabled,
    budget_krw: Number(state.budget_krw),
    schedule_id: state.schedule_id,
    cargo: state.cargo,
  };
}

function group_quote_items(items) {
  return items.reduce((groups, item) => { (groups[item.category] ||= []).push(item); return groups; }, {});
}

function render_trend_chart() {
  const values = DATA.trend_data;
  const width = 560, height = 230, padding = 28;
  const min = Math.min(...values) - 5, max = Math.max(...values) + 5;
  const points = values.map((value, index) => {
    const x = padding + index * ((width - padding * 2) / (values.length - 1));
    const y = height - padding - ((value - min) / (max - min)) * (height - padding * 2);
    return [x, y];
  });
  const path = points.map((point, index) => `${index ? "L" : "M"}${point[0]},${point[1]}`).join(" ");
  const months = ["10월","11월","12월","1월","2월","3월","4월","5월","6월","7월","8월","9월"];
  $("#trend_chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="최근 12개월 운임 추이"><defs><linearGradient id="trend_fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2b66f6" stop-opacity=".20"/><stop offset="1" stop-color="#2b66f6" stop-opacity="0"/></linearGradient></defs>${[0,.5,1].map((ratio) => `<line x1="${padding}" y1="${padding + ratio * (height-padding*2)}" x2="${width-padding}" y2="${padding + ratio * (height-padding*2)}" stroke="#e7edf5"/>`).join("")}<path d="${path} L${points.at(-1)[0]},${height-padding} L${points[0][0]},${height-padding} Z" fill="url(#trend_fill)"/><path d="${path}" fill="none" stroke="#2b66f6" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>${points.map((point, index) => `<text x="${point[0]}" y="${height-5}" text-anchor="middle">${months[index]}</text>`).join("")}</svg>`;
}

function render_scenarios(total) {
  const values = [
    { name: "현재 조건", value: total },
    { name: state.transport_mode === "lcl" ? "FCL 대안" : "LCL 대안", value: total * (state.transport_mode === "lcl" ? 1.22 : .86) },
    { name: "CPT 대안", value: total * .93 },
  ];
  const max = Math.max(...values.map((item) => item.value));
  $("#scenario_bars").innerHTML = values.map((item) => `<div class="scenario_row"><span>${item.name}</span><div class="scenario_track"><i style="width:${item.value / max * 100}%"></i></div><strong>${format_krw(item.value)}</strong></div>`).join("");
}

async function render_dashboard() {
  const locations = get_route_locations();
  const packing = DATA.packing_types.find((item) => item.value === state.packing_type);
  $("#dashboard_title").textContent = state.quote_name;
  $("#dashboard_summary").textContent = `${state.trade_direction === "export" ? "수출" : "수입"} · ${locations.origin.name} → ${locations.destination.name} · ${MODE_LABELS[state.transport_mode]} · ${state.incoterm} · ${packing.label}`;
  $("#exchange_rate").textContent = `1 USD = ${DATA.exchange_rate.rate.toLocaleString()}원`;
  try {
    const quote = await request_json("/api/quote", { method: "POST", body: JSON.stringify(quote_payload()) });
    const gap_positive = quote.budget_gap_krw >= 0;
    const kpis = [
      { tone: "blue", icon: "＄", label: "Door-to-Door 총 예상비용", value: format_krw(quote.total_krw), note: "세부 항목 합계" },
      { tone: "navy", icon: "◇", label: "수출자 실부담액", value: format_krw(quote.seller_cost_krw), note: `${state.incoterm} 부담 범위 기준` },
      { tone: gap_positive ? "green" : "amber", icon: gap_positive ? "↘" : "!", label: "예산 대비", value: `${gap_positive ? "여유" : "초과"} ${format_krw(Math.abs(quote.budget_gap_krw))}`, note: `입력 예산 ${format_krw(state.budget_krw)}` },
      { tone: quote.budget_rate <= 100 ? "green" : "amber", icon: "◴", label: "예산 사용률", value: `${quote.budget_rate}%`, note: quote.budget_rate <= 100 ? "예산 범위 내" : "예산 조정 필요" },
    ];
    $("#kpi_grid").innerHTML = kpis.map((item) => `<article class="kpi_card ${item.tone}"><span class="kpi_icon">${item.icon}</span><p>${item.label}</p><b>${item.value}</b><small>${item.note}</small></article>`).join("");

    const grouped = group_quote_items(quote.items);
    $("#quote_items").innerHTML = Object.entries(grouped).map(([category, items]) => `<section class="quote_group"><div class="quote_group_header"><span>${category}</span><b>${format_krw(items.reduce((sum, item) => sum + item.krw_amount, 0))}</b></div>${items.map((item) => `<div class="quote_line"><div>${item.name}${item.is_imputed ? '<span class="imputed_badge">대체값</span>' : ""}</div><div>${format_krw(item.krw_amount)}${item.original_currency !== "KRW" ? `<small>${item.original_currency} ${Number(item.original_amount).toLocaleString()}</small>` : ""}</div></div>`).join("")}</section>`).join("");
    $("#quote_total").textContent = format_krw(quote.total_krw);
    $("#donut_total").innerHTML = `총 비용<br>${Math.round(quote.total_krw / 10000).toLocaleString()}만원`;
    const total = quote.category_totals.reduce((sum, item) => sum + item.value, 0) || 1;
    let cursor = 0;
    const segments = quote.category_totals.map((item, index) => { const start = cursor; cursor += item.value / total * 100; return `${CHART_COLORS[index % CHART_COLORS.length]} ${start}% ${cursor}%`; });
    $("#donut_chart").style.background = `conic-gradient(${segments.join(",")})`;
    $("#donut_legend").innerHTML = quote.category_totals.map((item, index) => `<span><i style="background:${CHART_COLORS[index % CHART_COLORS.length]}"></i>${item.name}</span>`).join("");
    $("#insight_one").textContent = `선택한 ${quote.schedule.carrier} 스케줄은 ${quote.schedule.transit_days}일 소요되며 정시도착률은 ${quote.schedule.reliability}%입니다.`;
    $("#insight_two").textContent = gap_positive ? `현재 견적은 예산보다 ${format_krw(quote.budget_gap_krw)} 낮아 진행 여력이 있습니다.` : `현재 견적은 예산을 ${format_krw(Math.abs(quote.budget_gap_krw))} 초과해 운송 방식 재검토가 필요합니다.`;
    render_trend_chart();
    render_scenarios(quote.total_krw);
  } catch (error) {
    show_toast(error.message);
    window.setTimeout(() => navigate_to("cargo"), 500);
  }
}

function update_action_buttons() {
  const previous = $("#previous_button"), next = $("#next_button");
  if (current_step === "home") return;
  const index = STEP_ORDER.indexOf(current_step);
  previous.textContent = index === 0 ? "← 홈" : "← 이전";
  next.textContent = current_step === "schedule" ? "상세 견적 보기 →" : current_step === "dashboard" ? "새 견적 만들기 →" : "다음 단계 →";
}

function validate_current_step() {
  if (current_step === "route" && !state.quote_name.trim()) { show_toast("견적명을 입력해주세요."); return false; }
  if (current_step === "cargo") {
    state.cargo = cargo_payload();
    const invalid = ["length_cm", "width_cm", "height_cm", "box_count", "weight_per_box_kg"].some((key) => !Number.isFinite(state.cargo[key]) || state.cargo[key] <= 0);
    if (invalid) { show_toast("화물 크기, 수량과 중량은 0보다 커야 합니다."); return false; }
  }
  return true;
}

function initialize_events() {
  $$('[data-go]').forEach((button) => button.addEventListener("click", () => navigate_to(button.dataset.go)));
  window.addEventListener("popstate", () => { current_step = get_step_from_url(); render_page(); });
  $("#quote_name").addEventListener("input", (event) => { state.quote_name = event.target.value; save_state(); });
  $$('[data-direction]').forEach((button) => button.addEventListener("click", () => { state.trade_direction = button.dataset.direction; save_state(); render_route(); show_toast(state.trade_direction === "export" ? "수출 출발지를 대한민국으로 고정했습니다." : "수입 도착지를 대한민국으로 고정했습니다."); }));
  $$('[data-mode]').forEach((button) => button.addEventListener("click", () => { state.transport_mode = button.dataset.mode; if (state.transport_mode === "air" && ["FOB", "CFR", "CIF"].includes(state.incoterm)) state.incoterm = "FCA"; normalize_route_state(); save_state(); render_route(); }));
  $("#origin_select").addEventListener("change", (event) => { state.foreign_code = event.target.value; save_state(); render_route(); });
  $("#destination_select").addEventListener("change", (event) => { state.foreign_code = event.target.value; save_state(); render_route(); });
  $("#packing_type").addEventListener("change", (event) => { state.packing_type = event.target.value; save_state(); render_cargo(); });
  Object.keys(DEFAULT_STATE.cargo).forEach((key) => $(`#${key}`).addEventListener("input", () => void update_cargo_metrics()));
  $("#insurance_enabled").addEventListener("change", (event) => { state.insurance_enabled = event.target.checked; save_state(); });
  $("#budget_krw").addEventListener("input", (event) => { state.budget_krw = Math.max(0, Number(event.target.value) || 0); save_state(); });
  $("#sort_schedule").addEventListener("change", (event) => { state.sort_schedule = event.target.value; save_state(); void render_schedules(); });
  $("#previous_button").addEventListener("click", () => { const index = STEP_ORDER.indexOf(current_step); navigate_to(index <= 0 ? "home" : STEP_ORDER[index - 1]); });
  $("#next_button").addEventListener("click", () => {
    if (current_step === "dashboard") { state = structuredClone(DEFAULT_STATE); save_state(); navigate_to("route"); return; }
    if (!validate_current_step()) return;
    const index = STEP_ORDER.indexOf(current_step);
    navigate_to(STEP_ORDER[Math.min(index + 1, STEP_ORDER.length - 1)]);
  });
}

initialize_events();
normalize_route_state();
render_page();
