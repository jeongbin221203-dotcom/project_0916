(function () {
  var DATA = window.JRNL || [];
  if (!DATA.length) return;
  var DONE_KEY = "fat1.jrnl.done";
  var done = {};
  try { done = JSON.parse(localStorage.getItem(DONE_KEY) || "{}"); } catch (e) {}
  function save() { try { localStorage.setItem(DONE_KEY, JSON.stringify(done)); } catch (e) {} }

  var FILTERS = [
    ["all", "전체", function () { return true; }],
    ["g2", "2급 (1~100)", function (d) { return d.n <= 100; }],
    ["g1", "1급 (101~180)", function (d) { return d.n > 100 && d.n <= 180; }],
    ["cl", "결산 (181~200)", function (d) { return d.n > 180; }],
    ["todo", "안 푼 문제", function (d) { return !done[d.n]; }]
  ];
  var cur = "all";
  var query = "";

  var panel = document.createElement("aside");
  panel.id = "jrnlPanel";
  panel.innerHTML =
    '<div class="jr-head"><div><strong>분개 연습</strong><small id="jrCount"></small></div>' +
    '<div><button type="button" id="jrOpenAll">답 펼치기</button><button type="button" id="jrCloseAll">접기</button><button type="button" id="jrClose" aria-label="닫기">✕</button></div></div>' +
    '<div class="jr-bar"><div class="jr-filters"></div><input id="jrSearch" type="search" placeholder="번호 또는 계정·키워드 검색"></div>' +
    '<div id="jrList"></div>' +
    '<div class="jr-foot">문제: 초이쌤 전산회계 분개 200제 · 정답 분개는 학습용으로 직접 작성</div>';
  var toggle = document.createElement("button");
  toggle.id = "jrnlToggle"; toggle.type = "button"; toggle.title = "분개 연습 열기"; toggle.textContent = "분개";
  document.body.appendChild(panel);
  document.body.appendChild(toggle);

  var fbox = panel.querySelector(".jr-filters");
  FILTERS.forEach(function (f) {
    var b = document.createElement("button");
    b.type = "button"; b.setAttribute("data-f", f[0]); b.textContent = f[1];
    fbox.appendChild(b);
  });

  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function escA(s) { return esc(s).replace(/"/g, "&quot;"); }

  // ---- 정답 입력(차/대) ----
  var drafts = {};
  function normAcct(s) { return String(s).replace(/\([^)]*\)/g, "").replace(/\s/g, ""); }
  function parseLine(l) {
    var i = l.lastIndexOf(" ");
    var a = i < 0 ? l : l.slice(0, i), m = i < 0 ? "" : l.slice(i + 1).replace(/[^\d]/g, "");
    return { a: normAcct(a), m: m ? String(parseInt(m, 10)) : "" };
  }
  function draftOf(n) {
    if (!drafts[n]) drafts[n] = { dr: [["", ""], ["", ""]], cr: [["", ""], ["", ""]] };
    return drafts[n];
  }
  function inputRows(n, side) {
    var rows = draftOf(n)[side];
    return rows.map(function (r, i) {
      return '<div class="jr-row"><input class="jr-a" data-s="' + side + '" data-i="' + i + '" placeholder="계정과목" value="' + escA(r[0]) + '" autocomplete="off"><input class="jr-m" data-s="' + side + '" data-i="' + i + '" inputmode="numeric" placeholder="금액" value="' + escA(r[1]) + '" autocomplete="off"></div>';
    }).join("");
  }
  function inputBlock(d) {
    return '<div class="jr-in"><div class="jr-cols"><div><em>차)</em><div class="jr-rows" data-side="dr">' + inputRows(d.n, "dr") + '</div></div>' +
      '<div><em>대)</em><div class="jr-rows" data-side="cr">' + inputRows(d.n, "cr") + '</div></div></div>' +
      '<div class="jr-act"><button type="button" class="jr-add">행 추가</button><button type="button" class="jr-grade">채점</button><span class="jr-res"></span></div></div>';
  }
  function matchSide(answerLines, userRows) {
    var ans = answerLines.map(parseLine);
    var rows = userRows.filter(function (r) { return r[0].trim() || r[1].trim(); }).map(function (r) {
      var m = r[1].replace(/[^\d]/g, "");
      return { a: normAcct(r[0]), m: m ? String(parseInt(m, 10)) : "" };
    });
    if (rows.length !== ans.length) return false;
    var used = [];
    return ans.every(function (x) {
      for (var k = 0; k < rows.length; k++) {
        if (used[k]) continue;
        if (rows[k].a === x.a && (x.m === "" || rows[k].m === x.m)) { used[k] = true; return true; }
      }
      return false;
    });
  }

  function cell(lines) {
    return lines.map(function (l) {
      var i = l.lastIndexOf(" ");
      return '<div class="jr-line"><span>' + esc(l.slice(0, i)) + '</span><b>' + esc(l.slice(i + 1)) + '</b></div>';
    }).join("");
  }

  function item(d) {
    return '<div class="jr-item' + (done[d.n] ? ' is-done' : '') + '" data-n="' + d.n + '">' +
      '<div class="jr-q"><label><input type="checkbox" class="jr-chk"' + (done[d.n] ? ' checked' : '') + '> <b>[' + d.n + ']</b></label> ' + esc(d.q) + '</div>' +
      inputBlock(d) +
      '<details><summary>정답 분개 보기</summary><div class="jr-ans">' +
      '<div class="jr-col"><em>(차변)</em>' + cell(d.dr) + '</div><div class="jr-col"><em>(대변)</em>' + cell(d.cr) + '</div>' +
      (d.note ? '<p class="jr-note">' + esc(d.note) + '</p>' : '') + '</div></details></div>';
  }

  function render() {
    var f = FILTERS.filter(function (x) { return x[0] === cur; })[0][2];
    var q = query.trim().toLowerCase();
    var list = DATA.filter(f).filter(function (d) {
      if (!q) return true;
      if (/^\d+$/.test(q)) return String(d.n) === q;
      return (d.q + " " + d.dr.join(" ") + " " + d.cr.join(" ")).toLowerCase().indexOf(q) >= 0;
    });
    panel.querySelector("#jrList").innerHTML = list.length ? list.map(item).join("") : '<p class="jr-empty">해당하는 문제가 없습니다.</p>';
    var n = 0; DATA.forEach(function (d) { if (done[d.n]) n++; });
    panel.querySelector("#jrCount").textContent = "완료 " + n + " / " + DATA.length + " · 표시 " + list.length + "개";
    Array.prototype.forEach.call(fbox.children, function (b) { b.classList.toggle("on", b.getAttribute("data-f") === cur); });
  }

  fbox.addEventListener("click", function (e) {
    var f = e.target.getAttribute && e.target.getAttribute("data-f");
    if (f) { cur = f; render(); }
  });
  var listEl = panel.querySelector("#jrList");
  listEl.addEventListener("input", function (e) {
    var el = e.target;
    if (!el.classList || !(el.classList.contains("jr-a") || el.classList.contains("jr-m"))) return;
    var n = el.closest(".jr-item").getAttribute("data-n");
    var s = el.getAttribute("data-s"), i = parseInt(el.getAttribute("data-i"), 10);
    var row = draftOf(n)[s][i];
    if (el.classList.contains("jr-m")) { el.value = el.value.replace(/[^\d,]/g, ""); row[1] = el.value; } else row[0] = el.value;
  });
  listEl.addEventListener("keydown", function (e) {
    var el = e.target;
    if (e.key !== "Enter" || !el.classList || !(el.classList.contains("jr-a") || el.classList.contains("jr-m"))) return;
    e.preventDefault();
    var all = Array.prototype.slice.call(el.closest(".jr-in").querySelectorAll("input"));
    var next = all[all.indexOf(el) + 1];
    if (next) next.focus(); else el.closest(".jr-in").querySelector(".jr-grade").click();
  });
  listEl.addEventListener("click", function (e) {
    var b = e.target;
    if (!b.classList) return;
    var item = b.closest && b.closest(".jr-item");
    if (!item) return;
    var n = parseInt(item.getAttribute("data-n"), 10);
    if (b.classList.contains("jr-add")) {
      var dd = draftOf(n); dd.dr.push(["", ""]); dd.cr.push(["", ""]);
      item.querySelector('.jr-rows[data-side="dr"]').innerHTML = inputRows(n, "dr");
      item.querySelector('.jr-rows[data-side="cr"]').innerHTML = inputRows(n, "cr");
    } else if (b.classList.contains("jr-grade")) {
      var d = DATA.filter(function (x) { return x.n === n; })[0];
      var dd2 = draftOf(n);
      var okD = matchSide(d.dr, dd2.dr), okC = matchSide(d.cr, dd2.cr);
      var res = item.querySelector(".jr-res");
      if (okD && okC) {
        res.className = "jr-res ok"; res.textContent = "정답 ✔ (완료 체크됨)";
        var chk = item.querySelector(".jr-chk");
        if (chk && !chk.checked) { chk.checked = true; chk.dispatchEvent(new Event("change", { bubbles: true })); }
      }
      else { res.className = "jr-res ng"; res.textContent = "오답 ✘ (" + (okD ? "" : "차변") + (!okD && !okC ? "·" : "") + (okC ? "" : "대변") + " 확인)"; item.querySelector("details").open = true; }
    }
  });
  panel.querySelector("#jrSearch").addEventListener("input", function (e) { query = e.target.value; render(); });
  panel.querySelector("#jrList").addEventListener("change", function (e) {
    if (!e.target.classList.contains("jr-chk")) return;
    var box = e.target.closest(".jr-item");
    var n = box.getAttribute("data-n");
    if (e.target.checked) done[n] = 1; else delete done[n];
    box.classList.toggle("is-done", !!done[n]);
    save();
    var c = 0; DATA.forEach(function (d) { if (done[d.n]) c++; });
    var shown = panel.querySelectorAll(".jr-item").length;
    panel.querySelector("#jrCount").textContent = "완료 " + c + " / " + DATA.length + " · 표시 " + shown + "개";
  });
  function setAll(v) { Array.prototype.forEach.call(panel.querySelectorAll("#jrList details"), function (d) { d.open = v; }); }
  panel.querySelector("#jrOpenAll").addEventListener("click", function () { setAll(true); });
  panel.querySelector("#jrCloseAll").addEventListener("click", function () { setAll(false); });

  function setOpen(v) {
    document.body.classList.toggle("jrnl-open", v);
    toggle.classList.toggle("on", v);
    if (v) { var chat = document.body.classList.contains("chat-open"); if (chat) document.getElementById("chatToggle").click(); }
  }
  toggle.addEventListener("click", function () { setOpen(!document.body.classList.contains("jrnl-open")); });
  panel.querySelector("#jrClose").addEventListener("click", function () { setOpen(false); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && document.body.classList.contains("jrnl-open")) setOpen(false);
  });
  // AI 창이 열리면 분개 창은 닫기
  document.addEventListener("click", function (e) {
    if (e.target && e.target.id === "chatToggle" && document.body.classList.contains("jrnl-open") && !document.body.classList.contains("chat-open")) setOpen(false);
  }, true);

  render();
})();
