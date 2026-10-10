(function () {
  var CIR = ["①", "②", "③", "④"];

  // ===== 복습 모음: 문제마다 체크해 두면 10-17 패널에서 그것만 모아 봅니다 =====
  var RV_KEY = "fat1.review";
  var RV_MAP = {};
  function rvId(q) {
    var s = String(q[0]) + "|" + String(q[1]), h = 5381;
    for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return "q" + (h >>> 0).toString(36);
  }
  function rvLoad() {
    try { var v = JSON.parse(localStorage.getItem(RV_KEY) || "[]"); return Array.isArray(v) ? v : []; } catch (e) { return []; }
  }
  function rvSave(list) {
    try { localStorage.setItem(RV_KEY, JSON.stringify(list)); } catch (e) {}
  }
  function rvHas(id) {
    return rvLoad().some(function (x) { return x.id === id; });
  }
  function rvAdd(q) {
    var id = rvId(q), list = rvLoad();
    if (!list.some(function (x) { return x.id === id; })) { list.push({ id: id, q: q }); rvSave(list); }
    return id;
  }
  function rvRemove(id) {
    rvSave(rvLoad().filter(function (x) { return x.id !== id; }));
  }
  function rvButton(q) {
    var id = rvId(q);
    RV_MAP[id] = q;
    var on = rvHas(id);
    return '<button type="button" class="btn rv' + (on ? ' on' : '') + '" data-rv="' + id + '">' + (on ? '★ 복습에 담김' : '☆ 복습에 담기') + '</button>';
  }
  function rvRefreshButtons() {
    Array.prototype.forEach.call(document.querySelectorAll("button.rv"), function (b) {
      var on = rvHas(b.getAttribute("data-rv"));
      b.classList.toggle("on", on);
      b.textContent = on ? "★ 복습에 담김" : "☆ 복습에 담기";
    });
  }
  function buildReview(el) {
    if (!el) return;
    el.innerHTML = '<h4>복습 모음 <small id="rvCount"></small></h4>' +
      '<p class="source">문제 아래의 "☆ 복습에 담기"를 누르면 여기에 모입니다. 모의시험 결과 화면에서 틀린 이론 문제를 한 번에 담을 수도 있습니다. 이 브라우저에만 저장됩니다.</p>' +
      toolbar() + '<div class="qset" id="rvSet"></div>' +
      '<p><button type="button" class="btn" id="rvClear">복습 목록 비우기</button></p>';
    function render() {
      var list = rvLoad();
      el.querySelector("#rvCount").textContent = "(" + list.length + "문제)";
      el.querySelector("#rvSet").innerHTML = list.length ? list.map(function (x, i) { return qHtml(x.q, i + 1); }).join("") : '<div class="placeholder">아직 담은 문제가 없습니다. 기출·필수 문제 아래의 "☆ 복습에 담기"를 눌러 보세요.</div>';
    }
    render();
    el.addEventListener("click", function (e) {
      var act = e.target.getAttribute && e.target.getAttribute("data-act");
      if (act) {
        var set = e.target.parentNode.nextElementSibling;
        Array.prototype.forEach.call(set.querySelectorAll(".q details"), function (d) { d.open = act === "open"; });
        return;
      }
      if (e.target.id === "rvClear" && window.confirm("복습 목록을 모두 비울까요?")) { rvSave([]); render(); rvRefreshButtons(); }
    });
    document.addEventListener("rvchange", render);
  }
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("button.rv");
    if (!b) return;
    var id = b.getAttribute("data-rv"), q = RV_MAP[id];
    if (!q) return;
    if (rvHas(id)) rvRemove(id); else rvAdd(q);
    rvRefreshButtons();
    document.dispatchEvent(new Event("rvchange"));
  });
  // 모의시험 결과: 틀리거나 미응답인 이론 문항을 복습에 담는 단추
  function rvAddWrong(list) {
    list.forEach(function (q) { rvAdd(q); });
    rvRefreshButtons();
    document.dispatchEvent(new Event("rvchange"));
  }


  function qHtml(q, n) {
    var src = q[0];
    var tag = "";
    if (src === "필수예제") tag = '<span class="src">(필수 예제)</span> ';
    else if (src && src !== "-") tag = '<span class="src">(' + src + ')</span> ';
    var h = '<div class="q"><p><b>Q' + n + '.</b> ' + tag + q[1] + '</p>';
    for (var i = 0; i < q[2].length; i++) {
      h += '<div class="opt">' + CIR[i] + ' ' + q[2][i] + '</div>';
    }
    h += '<details><summary>정답 · 해설 보기</summary><div><b>정답 ' + q[3] + '</b>' + (q[4] ? ' — ' + q[4] : '') + '</div></details><p style="margin:6px 0 0">' + rvButton(q) + '</p></div>';
    return h;
  }

  function groupsHtml(groups, continuous) {
    var counter = 0;
    return groups.map(function (g) {
      var inner = g[1].map(function (q, i) {
        counter++;
        return qHtml(q, continuous ? counter : i + 1);
      }).join("");
      return '<details><summary>' + g[0] + ' <small>(' + g[1].length + '문제)</small></summary><div>' + inner + '</div></details>';
    }).join("");
  }

  function theoryHtml(list) {
    return list.map(function (t, i) {
      return '<details' + (i === 0 ? ' open' : '') + '><summary>' + t[0] + '</summary><div>' + t[1] + '</div></details>';
    }).join("");
  }

  function toolbar() {
    return '<div class="tools"><button type="button" class="btn" data-act="open">정답 모두 펼치기</button> <button type="button" class="btn" data-act="close">정답 모두 접기</button></div>';
  }

  function build(el, theory, basic, main, mainTitle) {
    if (!el) return;
    var total = 0;
    main.forEach(function (g) { total += g[1].length; });
    var basicCount = 0;
    basic.forEach(function (g) { basicCount += g[1].length; });
    el.innerHTML =
      '<h4>' + mainTitle.split(' ')[0] + ' 이론 정리</h4>' + theoryHtml(theory) +
      '<h4>단원별 기출문제 풀어보기 <small>(' + basicCount + '문제)</small></h4>' + toolbar() + '<div class="qset">' + groupsHtml(basic, false) + '</div>' +
      '<h4>' + mainTitle + ' <small>(' + total + '문제)</small></h4>' + toolbar() + '<div class="qset">' + groupsHtml(main, true) + '</div>' +
      '<p class="source">참고: 『2025년 전산세무2급 핵심요약 교재』 © 전산회계다윤(고다윤). 개인 학습용으로 정리함.</p>';

    el.addEventListener("click", function (e) {
      var act = e.target.getAttribute && e.target.getAttribute("data-act");
      if (!act) return;
      var set = e.target.parentNode.nextElementSibling;
      Array.prototype.forEach.call(set.querySelectorAll(".q details"), function (d) { d.open = act === "open"; });
      if (act === "open") {
        Array.prototype.forEach.call(set.querySelectorAll(":scope > details"), function (d) { d.open = true; });
      }
    });
  }

  var PAST_PAGES = {73:[6,7],74:[4,5],75:[5,6],76:[5,6],77:[4,6],78:[5,6],79:[4,6],80:[4,6],81:[4,5],82:[5,7],83:[5,7],84:[4,7],85:[3,6],86:[4,6],87:[5,6],88:[4,7],89:[5,6],90:[4,5],91:[5,7],92:[4,7]};
  function sheet(prefix, n, count) {
    var h = "";
    for (var i = 1; i <= count; i++) {
      h += '<img loading="lazy" src="past/' + prefix + n + '_' + i + '.jpg" alt="제' + n + '회 ' + (prefix === "q" ? "시험지" : "정답·해설지") + ' ' + i + '쪽" style="display:block;width:100%;max-width:760px;margin:8px auto;border:1px solid #bbb;background:#fff">';
    }
    return h;
  }
  function pastGroupsHtml(groups) {
    return groups.map(function (g) {
      var n = parseInt(g[0].replace(/\D/g, ""), 10);
      var pg = PAST_PAGES[n];
      var inner = g[1].map(function (q, i) { return qHtml(q, i + 1); }).join("");
      var raw = pg ? '<details class="rawsheet"><summary>시험지 원본 그대로 보기 (인쇄 화면)</summary><div>' + sheet("q", n, pg[0]) + '</div></details>' +
        '<details class="rawsheet"><summary>정답·해설지 원본 그대로 보기</summary><div>' + sheet("a", n, pg[1]) + '</div></details>' : "";
      return '<details><summary>' + g[0] + ' <small>(' + g[1].length + '문제)</small></summary><div>' + raw + inner + '</div></details>';
    }).join("");
  }

  // ===== 시험 화면 재현 모드: 다크 네이비 PDF 뷰어 + 답안 패널 =====
  function openExamViewer(cur, n, onSaved) {
    var pages = (PAST_PAGES[n] || [0])[0];
    var total = cur[1].length;
    var answers = {};
    function starRid(qq) {
      var id = rvId(qq); RV_MAP[id] = qq;
      var on = rvHas(id);
      return '<button type="button" class="xv-star' + (on ? ' on' : '') + '" data-rid="' + id + '" title="복습 모음에 담기/빼기">' + (on ? '★' : '☆') + '</button>';
    }
    function syncRid() {
      Array.prototype.forEach.call(root.querySelectorAll('.xv-star[data-rid]'), function (b) {
        var on = rvHas(b.getAttribute('data-rid')); b.classList.toggle('on', on); b.textContent = on ? '★' : '☆';
      });
    }
    var zoom = 95, curPage = 1, sec = 60 * 60, timer = null, done = false;
    var root = document.createElement("div");
    root.className = "xv";
    var thumbs = "", sheets = "";
    for (var i = 1; i <= pages; i++) {
      thumbs += '<a class="xv-th" data-p="' + i + '"><img loading="lazy" src="past/q' + n + '_' + i + '.jpg" alt=""><span>' + i + '</span></a>';
      sheets += '<img class="xv-pg" data-p="' + i + '" src="past/q' + n + '_' + i + '.jpg" alt="제' + n + '회 시험지 ' + i + '쪽">';
    }
    var rows = "";
    for (var q = 0; q < total; q++) {
      rows += '<div class="xv-row" data-q="' + q + '">' + starRid(cur[1][q]) + '<b>' + (q + 1) + '</b>';
      rows += '<input class="xv-in" type="text" inputmode="numeric" maxlength="1" autocomplete="off" aria-label="' + (q + 1) + '번 답">';
      rows += '</div>';
    }
    root.innerHTML =
      '<div class="xv-top">' +
      
      '<span class="xv-title">제' + n + '회 FAT 1급 · 실무이론평가</span>' +
      '<span class="xv-mid"><span class="xv-pn"><input class="xv-cur" value="1" size="2" aria-label="현재 쪽"> / ' + pages + '</span>' +
      '<span class="xv-sep"></span><button type="button" class="xv-ic" data-a="zout">−</button><span class="xv-zm">' + zoom + '%</span><button type="button" class="xv-ic" data-a="zin">+</button></span>' +
      '<span class="xv-right"><span class="xv-time">60:00</span><button type="button" class="xv-ic" data-a="ans" title="답안 패널">✎</button>' +
      '<button type="button" class="xv-sub" data-a="submit">제출</button><button type="button" class="xv-ic" data-a="close" title="닫기">✕</button></span></div>' +
      '<div class="xv-body">' +
      '<aside class="xv-ans"><h4>답안 입력 <small class="xv-cnt">0 / ' + total + '</small></h4>' + rows +
      '<p class="xv-note">시험지를 보면서 번호별로 답(1~4)을 숫자로 입력하세요. 입력하면 다음 문항으로 넘어가며, 제출 전에는 언제든 바꿀 수 있습니다.</p></aside>' +
      '<div class="xv-main">' + sheets + '</div></div>';
    document.body.appendChild(root);
    document.body.classList.add("xv-open");
    var main = root.querySelector(".xv-main");

    function fmt(s) { var m = Math.floor(s / 60), r = s % 60; return (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r; }
    function applyZoom() {
      Array.prototype.forEach.call(main.querySelectorAll(".xv-pg"), function (im) { im.style.width = (zoom * 8) / 1 + "px"; im.style.maxWidth = "none"; });
      root.querySelector(".xv-zm").textContent = zoom + "%";
    }
    function setPage(p) {
      curPage = p;
      root.querySelector(".xv-cur").value = p;
      Array.prototype.forEach.call(root.querySelectorAll(".xv-th"), function (a) { a.classList.toggle("on", parseInt(a.getAttribute("data-p"), 10) === p); });
    }
    function goPage(p) {
      p = Math.max(1, Math.min(pages, p));
      var im = main.querySelector('.xv-pg[data-p="' + p + '"]');
      if (im) main.scrollTop = im.offsetTop - 12;
      setPage(p);
    }
    function onScroll() {
      var best = 1, y = main.scrollTop + main.clientHeight / 3;
      Array.prototype.forEach.call(main.querySelectorAll(".xv-pg"), function (im) { if (im.offsetTop <= y) best = parseInt(im.getAttribute("data-p"), 10); });
      if (best !== curPage) setPage(best);
    }
    function count() {
      var c = Object.keys(answers).length;
      root.querySelector(".xv-cnt").textContent = c + " / " + total;
    }
    function finish() {
      if (done) return;
      done = true;
      clearInterval(timer);
      var ok = 0, un = 0, h = "", wrong = [];
      cur[1].forEach(function (qq, i) {
        var a = answers[i], good = a === qq[3];
        if (!a) un++; else if (good) ok++;
        if (!good) wrong.push(qq);
        h += '<div class="xv-r ' + (!a ? "un" : good ? "ok" : "ng") + '">' + starRid(qq) + '<b>[' + (i + 1) + ']</b> ' + (!a ? "미응답" : good ? "정답 ✔" : "오답 ✘ (내 답 " + a + ")") + ' · 정답 ' + qq[3] +
          '<details><summary>문제·해설</summary><div><p>' + qq[1] + '</p>' + qq[2].map(function (o, k) { return '<div>' + CIR[k] + ' ' + o + '</div>'; }).join("") + '<p><b>해설</b> ' + qq[4] + '</p></div></details></div>';
      });
      var score = ok * 3;
      var used = 60 * 60 - sec;
      var res = document.createElement("div");
      res.className = "xv-result";
      res.innerHTML = '<div class="xv-card"><h3>채점 결과 · 제' + n + '회</h3><p class="xv-big">' + score + '점 <small>/ 30점 (정답 ' + ok + ' · 미응답 ' + un + ' · 소요 ' + Math.floor(used / 60) + '분 ' + (used % 60) + '초)</small></p>' + h +
        '<p>' + (wrong.length ? '<button type="button" class="xv-sub" data-a="rv">틀린·미응답 ' + wrong.length + '문제 복습에 담기</button> ' : '') + '<button type="button" class="xv-sub" data-a="close">닫기</button></p></div>';
      root.appendChild(res);
      root.rvList = wrong;
      if (onSaved) onSaved(score);
    }
    function close() {
      clearInterval(timer);
      document.body.classList.remove("xv-open");
      if (root.parentNode) root.parentNode.removeChild(root);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("rvchange", syncRid);
    }
    function onKey(e) { if (e.key === "Escape") close(); }
    document.addEventListener("keydown", onKey);

    document.addEventListener("rvchange", syncRid);
    root.addEventListener("click", function (e) {
      var t = e.target;
      var sb = t.closest && t.closest(".xv-star");
      if (sb) {
        var rid = sb.getAttribute("data-rid");
        if (rvHas(rid)) rvRemove(rid); else rvAdd(RV_MAP[rid]);
        rvRefreshButtons();
        document.dispatchEvent(new Event("rvchange"));
        return;
      }
      var th = t.closest && t.closest(".xv-th");
      if (th) { goPage(parseInt(th.getAttribute("data-p"), 10)); return; }
      var btn = t.closest && t.closest("[data-a]");
      if (btn) {
        var a = btn.getAttribute("data-a");
        if (a === "close") close();
        else if (a === "rv") { rvAddWrong(root.rvList || []); btn.textContent = "복습에 담았습니다 ✔"; btn.disabled = true; }
        else if (a === "side") root.classList.toggle("no-side");
        else if (a === "ans") root.classList.toggle("no-ans");
        else if (a === "zin") { zoom = Math.min(200, zoom + 10); applyZoom(); }
        else if (a === "zout") { zoom = Math.max(40, zoom - 10); applyZoom(); }
        else if (a === "submit") {
          var left = total - Object.keys(answers).length;
          if (left && !window.confirm("답을 선택하지 않은 문항이 " + left + "개 있습니다. 제출할까요?")) return;
          finish();
        }
        return;
      }
    });
    root.querySelector(".xv-ans").addEventListener("input", function (e) {
      var inp = e.target;
      if (!inp.classList || !inp.classList.contains("xv-in") || done) return;
      var qi = parseInt(inp.parentNode.getAttribute("data-q"), 10);
      var d = inp.value.replace(/[^1-4]/g, "");
      inp.value = d;
      if (d) { answers[qi] = CIR[parseInt(d, 10) - 1]; var nx = root.querySelector('.xv-row[data-q="' + (qi + 1) + '"] .xv-in'); if (nx) nx.focus(); }
      else delete answers[qi];
      count();
    });
    root.querySelector(".xv-ans").addEventListener("keydown", function (e) {
      var inp = e.target;
      if (!inp.classList || !inp.classList.contains("xv-in")) return;
      var qi = parseInt(inp.parentNode.getAttribute("data-q"), 10), to = null;
      if (e.key === "ArrowDown" || e.key === "Enter") to = qi + 1; else if (e.key === "ArrowUp") to = qi - 1;
      if (to !== null) { var el = root.querySelector('.xv-row[data-q="' + to + '"] .xv-in'); if (el) { e.preventDefault(); el.focus(); el.select(); } }
    });
    root.querySelector(".xv-cur").addEventListener("change", function (e) { goPage(parseInt(e.target.value, 10) || 1); });
    main.addEventListener("scroll", onScroll);
    timer = setInterval(function () {
      sec--;
      root.querySelector(".xv-time").textContent = fmt(Math.max(0, sec));
      root.querySelector(".xv-time").classList.toggle("low", sec <= 300);
      if (sec <= 0) finish();
    }, 1000);
    if (window.innerWidth < 900) root.classList.add("no-side", "no-ans");
    applyZoom();
    setPage(1);
    return { root: root, goPage: goPage, answers: answers, finish: finish, close: close };
  }

  // ===== 모의시험: 이론 + 실무(평가문제) 한 번에, 60분, 100점 (답안 입력줄·결과마다 ☆ 즐겨찾기 → 복습 모음) =====
  var FULL_KEY = "fat1.full";
  function fullSaved() {
    try { return JSON.parse(localStorage.getItem(FULL_KEY) || "{}"); } catch (e) { return {}; }
  }
  function escH(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  // 조회 메뉴 → 같은 회차의 관련 수행과제 풀이 (필요한 부분만 첨부)
  function relatedSolHtml(n, menu) {
    var P = (window.STUDY || {}).practice;
    if (!P) return "";
    var rules = [
      [/영수증수취/, [["거래자료입력", "3만원 초과 거래·영수증수취명세서"]]],
      [/부가가치세|세금계산서|계산서합계|매입매출/, [["부가가치세", null]]],
      [/받을어음|지급어음|예적금|자금|일일/, [["거래자료입력", "어음관리"], ["거래자료입력", "통장거래"]]],
      [/고정자산/, [["부가가치세", null]]],
      [/회사등록|거래처등록|사업자|전기분|이익잉여금|초기이월/, [["기초정보관리", null]]],
      [/재무상태표|손익계산서|합계잔액|제조원가|결산/, [["결산", null]]],
      [/거래처원장|총계정|계정별|현금출납|월계표|일계표/, [["거래자료입력", null]]]
    ];
    var want = [];
    for (var r = 0; r < rules.length; r++) { if (rules[r][0].test(menu)) { want = rules[r][1]; break; } }
    var out = [];
    want.forEach(function (w) {
      P.groups.forEach(function (g) {
        if (g[0] !== w[0]) return;
        g[2].forEach(function (s) {
          if (w[1] && s[0] !== w[1]) return;
          s[1].forEach(function (it) { if (it[0] === n && out.length < 4) out.push(it); });
        });
      });
    });
    return out.map(function (it) {
      var lines = it[4].slice(0, 10).map(escH).join("<br>");
      return '<details><summary>관련 수행과제 풀이 · ' + escH(it[1]) + '</summary><div>' + lines + (it[4].length > 10 ? '<br>… (전체는 답안지 원본 참고)' : '') + '</div></details>';
    }).join("");
  }
  // 복습 모음에 담을 문제 형태 [출처, 문제, 보기, 정답, 해설]
  function fullTuple(n, it) {
    if (it.sec === "이론") return [n + "회 " + it.no + "번", it.q, it.opts, CIR[parseInt(it.a, 10) - 1], it.ex];
    var stem = it.q.split(" / ").map(escH).join("<br>") + '<br><i>[' + escH(it.label) + '] · ' + it.pt + '점</i>';
    var ex = "";
    if (it.sec === "분석" && it.ex) ex += escH(it.ex);
    ex += (ex ? "<br>" : "") + relatedSolHtml(n, it.label);
    return ["제" + n + "회 " + (it.sec === "분석" ? "회계정보분석 " : "실무 ") + it.no + "번", stem, [], it.t === "c" ? it.a + "번" : it.a, ex];
  }
  function openFullExam(n, thPages, psPages, prPages) {
    var S2 = window.STUDY || {};
    var group = (S2.pastExam || []).filter(function (g) { return parseInt(g[0].replace(/\D/g, ""), 10) === n; })[0];
    var real = (S2.fullExam || {})[String(n)];
    if (!group || !real) return null;
    var theory = group[1];
    var items = [];
    theory.forEach(function (q, i) { items.push({ no: i + 1, sec: "이론", label: "", t: "c", a: CIR.indexOf(q[3]) + 1 + "", pt: 3, q: q[1], ex: q[4], opts: q[2] }); });
    real.forEach(function (r) { items.push({ no: r[0], sec: r[1], label: r[2], t: r[4], a: r[5], pt: r[6], q: r[3], ex: r[7] || "" }); });
    items.forEach(function (it) { it.tuple = fullTuple(n, it); it.id = rvId(it.tuple); RV_MAP[it.id] = it.tuple; });
    var imgs = [];
    for (var i = 1; i <= thPages; i++) imgs.push("past/q" + n + "_" + i + ".jpg");
    for (var j = 1; j <= psPages; j++) imgs.push("past/ps" + n + "_" + j + ".jpg");
    var total = imgs.length;
    var answers = {};
    var zoom = 95, curPage = 1, sec = 60 * 60, timer = null, done = false;
    var root = document.createElement("div");
    root.className = "xv";
    var sheets = imgs.map(function (s, k) { return '<img class="xv-pg" data-p="' + (k + 1) + '" src="' + s + '" alt="제' + n + '회 시험지 ' + (k + 1) + '쪽">'; }).join("");
    function star(idx) {
      var on = rvHas(items[idx].id);
      return '<button type="button" class="xv-star' + (on ? " on" : "") + '" data-i="' + idx + '" title="복습 모음에 담기/빼기">' + (on ? "★" : "☆") + '</button>';
    }
    var rows = "", lastSec = "";
    var SEC_TITLE = { "이론": "이론 (30점)", "실무": "실무 평가문제 (62점)", "분석": "회계정보분석 (8점)" };
    items.forEach(function (it, idx) {
      if (it.sec !== lastSec) { rows += '<h5 class="xv-sec">' + SEC_TITLE[it.sec] + '</h5>'; lastSec = it.sec; }
      rows += '<div class="xv-row" data-q="' + idx + '">' + star(idx) + '<b>' + it.no + '</b><input class="xv-in" type="text" inputmode="numeric" maxlength="12" autocomplete="off" aria-label="' + it.no + '번 답"></div>';
    });
    root.innerHTML =
      '<div class="xv-top"><span class="xv-title">제' + n + '회 FAT 1급 · 이론+실무 모의시험</span>' +
      '<span class="xv-mid"><span class="xv-pn"><input class="xv-cur" value="1" size="2" aria-label="현재 쪽"> / ' + total + '</span>' +
      '<span class="xv-sep"></span><button type="button" class="xv-ic" data-a="zout">−</button><span class="xv-zm">' + zoom + '%</span><button type="button" class="xv-ic" data-a="zin">+</button></span>' +
      '<span class="xv-right"><span class="xv-time">60:00</span><button type="button" class="xv-ic" data-a="ans" title="답안 패널">✎</button>' +
      '<button type="button" class="xv-sub" data-a="submit">제출</button><button type="button" class="xv-ic" data-a="close" title="닫기">✕</button></span></div>' +
      '<div class="xv-body"><aside class="xv-ans"><h4>답안 입력 <small class="xv-cnt">0 / ' + items.length + '</small></h4>' + rows +
      '<p class="xv-note">☆를 누르면 그 문제가 10-17 복습 모음에 담깁니다(제출 전·후 모두 가능). 이론은 1~4, 실무 평가문제는 프로그램에서 조회한 값(숫자·코드) 또는 보기 번호(1~4)를 입력하세요. 금액은 콤마·단위 없이 숫자만, 코드는 자릿수 그대로(예: 00113) 입력합니다.</p></aside>' +
      '<div class="xv-main">' + sheets + '</div></div>';
    document.body.appendChild(root);
    document.body.classList.add("xv-open");
    var main = root.querySelector(".xv-main");

    function fmt(s) { var m = Math.floor(s / 60), r = s % 60; return (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r; }
    function applyZoom() {
      Array.prototype.forEach.call(main.querySelectorAll(".xv-pg"), function (im) { im.style.width = (zoom * 8) + "px"; im.style.maxWidth = "none"; });
      root.querySelector(".xv-zm").textContent = zoom + "%";
    }
    function setPage(p) { curPage = p; root.querySelector(".xv-cur").value = p; }
    function goPage(p) {
      p = Math.max(1, Math.min(total, p));
      var im = main.querySelector('.xv-pg[data-p="' + p + '"]');
      if (im) main.scrollTop = im.offsetTop - 12;
      setPage(p);
    }
    function onScroll() {
      var best = 1, y = main.scrollTop + main.clientHeight / 3;
      Array.prototype.forEach.call(main.querySelectorAll(".xv-pg"), function (im) { if (im.offsetTop <= y) best = parseInt(im.getAttribute("data-p"), 10); });
      if (best !== curPage) setPage(best);
    }
    function count() { root.querySelector(".xv-cnt").textContent = Object.keys(answers).length + " / " + items.length; }
    function norm(s) { return String(s).replace(/[\s,원매건명개]/g, ""); }
    function syncStars() {
      Array.prototype.forEach.call(root.querySelectorAll(".xv-star"), function (b) {
        var on = rvHas(items[parseInt(b.getAttribute("data-i"), 10)].id);
        b.classList.toggle("on", on);
        b.textContent = on ? "★" : "☆";
      });
    }
    function finish() {
      if (done) return;
      done = true;
      clearInterval(timer);
      var sc = { "이론": 0, "실무": 0, "분석": 0 }, h = "", un = 0, wrong = [];
      items.forEach(function (it, idx) {
        var a = answers[idx], good = a !== undefined && norm(a) === norm(it.a);
        if (a === undefined) un++;
        if (good) sc[it.sec] += it.pt;
        if (!good) wrong.push(it.tuple);
        var shown = it.t === "c" ? it.a + "번" : it.a;
        h += '<div class="xv-r ' + (a === undefined ? "un" : good ? "ok" : "ng") + '">' + star(idx) + '<b>' + (it.sec === "이론" ? "[이론 " : "[") + it.no + ']</b> ' + (a === undefined ? "미응답" : good ? "정답 ✔" : "오답 ✘ (내 답 " + escH(a) + ")") + ' · 정답 ' + escH(shown) + ' · ' + it.pt + '점' +
          '<details><summary>' + escH(it.label || "문제·해설") + '</summary><div><p>' + (it.sec === "이론" ? it.q : escH(it.q)) + '</p>' +
          (it.opts ? it.opts.map(function (o, k) { return '<div>' + CIR[k] + ' ' + o + '</div>'; }).join("") : "") + (it.ex ? '<p><b>해설</b> ' + (it.sec === "실무" ? "" : it.ex) + '</p>' : '') +
          (it.sec !== "이론" ? relatedSolHtml(n, it.label) : "") + '</div></details></div>';
      });
      var score = sc["이론"] + sc["실무"] + sc["분석"];
      var used = 60 * 60 - sec;
      var pr = "";
      for (var k = 1; k <= prPages; k++) pr += '<img loading="lazy" src="past/pr' + n + '_' + k + '.jpg" alt="답안지 ' + k + '쪽" style="display:block;width:100%;max-width:760px;margin:8px auto;background:#fff">';
      var res = document.createElement("div");
      res.className = "xv-result";
      res.innerHTML = '<div class="xv-card"><h3>채점 결과 · 제' + n + '회 이론+실무</h3><p class="xv-big">' + score + '점 <small>/ 100점 · ' + (score >= 70 ? "합격선(70점) 통과 ✔" : "합격선(70점)까지 " + (70 - score) + "점 부족") + '</small></p>' +
        '<p>이론 ' + sc["이론"] + '/30 · 실무 평가문제 ' + sc["실무"] + '/62 · 회계정보분석 ' + sc["분석"] + '/8 · 미응답 ' + un + ' · 소요 ' + Math.floor(used / 60) + '분 ' + (used % 60) + '초</p>' +
        '<p class="xv-hint">각 문항 앞의 ☆를 누르면 10-17 복습 모음에 담기고, 해당 문제의 정답·해설만 따로 볼 수 있습니다.</p>' + h +
        '<details class="xv-r"><summary>답안지 원본(수행과제 풀이 포함) 보기</summary><div>' + pr + '</div></details>' +
        '<p>' + (wrong.length ? '<button type="button" class="xv-sub" data-a="rv">틀린·미응답 ' + wrong.length + '문제 복습에 담기</button> ' : '') + '<button type="button" class="xv-sub" data-a="close">닫기</button></p></div>';
      root.appendChild(res);
      root.rvList = wrong;
      var saved = fullSaved();
      saved[n] = score;
      try { localStorage.setItem(FULL_KEY, JSON.stringify(saved)); } catch (e) {}
    }
    function close() {
      clearInterval(timer);
      document.body.classList.remove("xv-open");
      if (root.parentNode) root.parentNode.removeChild(root);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("rvchange", syncStars);
    }
    function onKey(e) { if (e.key === "Escape") close(); }
    document.addEventListener("keydown", onKey);
    document.addEventListener("rvchange", syncStars);
    root.addEventListener("click", function (e) {
      var st = e.target.closest && e.target.closest(".xv-star");
      if (st) {
        var it = items[parseInt(st.getAttribute("data-i"), 10)];
        if (rvHas(it.id)) rvRemove(it.id); else rvAdd(it.tuple);
        rvRefreshButtons();
        document.dispatchEvent(new Event("rvchange"));
        return;
      }
      var btn = e.target.closest && e.target.closest("[data-a]");
      if (!btn) return;
      var a = btn.getAttribute("data-a");
      if (a === "close") close();
      else if (a === "rv") { rvAddWrong(root.rvList || []); btn.textContent = "복습에 담았습니다 ✔"; btn.disabled = true; }
      else if (a === "ans") root.classList.toggle("no-ans");
      else if (a === "zin") { zoom = Math.min(200, zoom + 10); applyZoom(); }
      else if (a === "zout") { zoom = Math.max(40, zoom - 10); applyZoom(); }
      else if (a === "submit") {
        var left = items.length - Object.keys(answers).length;
        if (left && !window.confirm("답을 입력하지 않은 문항이 " + left + "개 있습니다. 제출할까요?")) return;
        finish();
      }
    });
    var ans = root.querySelector(".xv-ans");
    ans.addEventListener("input", function (e) {
      var inp = e.target;
      if (!inp.classList || !inp.classList.contains("xv-in") || done) return;
      var qi = parseInt(inp.parentNode.getAttribute("data-q"), 10);
      var v = inp.value.replace(/[^0-9\-.,]/g, "");
      inp.value = v;
      if (v) answers[qi] = v; else delete answers[qi];
      if (items[qi].sec === "이론" && v && /^[1-4]$/.test(v)) {
        var nx = root.querySelector('.xv-row[data-q="' + (qi + 1) + '"] .xv-in');
        if (nx) nx.focus();
      }
      count();
    });
    ans.addEventListener("keydown", function (e) {
      var inp = e.target;
      if (!inp.classList || !inp.classList.contains("xv-in")) return;
      var qi = parseInt(inp.parentNode.getAttribute("data-q"), 10), to = null;
      if (e.key === "ArrowDown" || e.key === "Enter") to = qi + 1; else if (e.key === "ArrowUp") to = qi - 1;
      if (to !== null) { var el = root.querySelector('.xv-row[data-q="' + to + '"] .xv-in'); if (el) { e.preventDefault(); el.focus(); el.select(); } }
    });
    root.querySelector(".xv-cur").addEventListener("change", function (e) { goPage(parseInt(e.target.value, 10) || 1); });
    main.addEventListener("scroll", onScroll);
    timer = setInterval(function () {
      sec--;
      root.querySelector(".xv-time").textContent = fmt(Math.max(0, sec));
      root.querySelector(".xv-time").classList.toggle("low", sec <= 300);
      if (sec <= 0) finish();
    }, 1000);
    if (window.innerWidth < 900) root.classList.add("no-ans");
    applyZoom();
    setPage(1);
    return { root: root, items: items, answers: answers, finish: finish, close: close };
  }

  function buildMock(box, groups) {
    var KEY = "fat1.mock";
    var saved = {};
    try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
    function num(g) { return parseInt(g[0].replace(/\D/g, ""), 10); }
    var opts = groups.map(function (g) {
      var n = num(g);
      return '<option value="' + n + '">' + g[0] + (saved[n] != null ? " (최근 " + saved[n] + "점)" : "") + '</option>';
    }).join("");
    box.innerHTML = '<div class="tools"><select id="mockSel">' + opts + '</select> <button type="button" class="btn" id="mockStart">실전 풀이 시작</button> <button type="button" class="btn" id="mockViewer">시험 화면으로 풀기 (다크)</button> <span id="mockTime" style="margin-left:8px"></span></div><div id="mockArea"></div>';
    var timer = null, sec = 0, cur = null;
    function stop() { if (timer) { clearInterval(timer); timer = null; } }
    function tick() { sec++; var m = Math.floor(sec / 60), r = sec % 60; box.querySelector("#mockTime").textContent = "경과 " + (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r + " / 이론 권장 15분"; }
    box.querySelector("#mockViewer").addEventListener("click", function () {
      var n = parseInt(box.querySelector("#mockSel").value, 10);
      var g = groups.filter(function (x) { return num(x) === n; })[0];
      openExamViewer(g, n, function (score) {
        saved[n] = score;
        try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) {}
      });
    });
    box.querySelector("#mockStart").addEventListener("click", function () {
      var n = parseInt(box.querySelector("#mockSel").value, 10);
      cur = groups.filter(function (g) { return num(g) === n; })[0];
      stop(); sec = 0; tick(); timer = setInterval(tick, 1000);
      var h = '<h5>' + cur[0] + ' 실무이론평가 (문항당 3점)</h5>';
      cur[1].forEach(function (q, i) {
        h += '<div class="q" data-i="' + i + '"><p><b>[' + (i + 1) + ']</b> ' + q[1] + '</p>';
        q[2].forEach(function (o, k) {
          h += '<label class="opt" style="display:block;cursor:pointer"><input type="radio" name="m' + i + '" value="' + CIR[k] + '"> ' + CIR[k] + ' ' + o + '</label>';
        });
        h += '<div class="mres"></div></div>';
      });
      h += '<p><button type="button" class="btn" id="mockSubmit">제출·채점</button></p><div id="mockScore"></div>';
      box.querySelector("#mockArea").innerHTML = h;
      box.querySelector("#mockSubmit").addEventListener("click", function () {
        stop();
        var ok = 0, un = 0;
        Array.prototype.forEach.call(box.querySelectorAll("#mockArea .q"), function (el) {
          var i = parseInt(el.getAttribute("data-i"), 10), q = cur[1][i];
          var sel = el.querySelector("input:checked");
          var res = el.querySelector(".mres");
          if (!sel) { un++; res.innerHTML = '<b style="color:#ffb454">미응답</b> — 정답 ' + q[3] + '<br>' + q[4]; }
          else if (sel.value === q[3]) { ok++; res.innerHTML = '<b style="color:#6fd08c">정답 ✔</b><br>' + q[4]; }
          else { res.innerHTML = '<b style="color:#ff7b72">오답 ✘</b> (내 답 ' + sel.value + ' / 정답 ' + q[3] + ')<br>' + q[4]; }
        });
        var score = ok * 3;
        box.querySelector("#mockScore").innerHTML = '<b>' + ok + ' / ' + cur[1].length + ' 정답 · ' + score + '점 (30점 만점)</b>' + (un ? ' · 미응답 ' + un : '') + ' · 소요 ' + Math.floor(sec / 60) + '분 ' + (sec % 60) + '초';
        saved[num(cur)] = score;
        try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch (e) {}
      });
    });
  }

  function buildPast(el, groups) {
    if (!el) return;
    var total = 0;
    groups.forEach(function (g) { total += g[1].length; });
    el.insertAdjacentHTML("beforeend",
      '<h4>이론 기출문제 <small>(제' + groups[groups.length - 1][0].replace(/\D/g, "") + '회~제' + groups[0][0].replace(/\D/g, "") + '회 · ' + total + '문제)</small></h4>' +
      '<div id="mockBox" class="card"><h5>실전 모의시험</h5></div>' +
      toolbar() + '<div class="qset">' + pastGroupsHtml(groups) + '</div>' +
      '<p class="source">문제·해설: 한국공인회계사회 FAT 1급 기출(실무이론평가). 그림이 있는 문제는 글로 옮겨 적었습니다. 개인 학습용.</p>');
    buildMock(el.querySelector("#mockBox"), groups);
    el.addEventListener("click", function (e) {
      var act = e.target.getAttribute && e.target.getAttribute("data-act");
      if (!act) return;
      var set = e.target.parentNode.nextElementSibling;
      Array.prototype.forEach.call(set.querySelectorAll(".q details"), function (d) { d.open = act === "open"; });
      if (act === "open") {
        Array.prototype.forEach.call(set.querySelectorAll(":scope > details"), function (d) { d.open = true; });
      }
    });
  }

  // 실기: 92회는 따라하기(문제+풀이 같은 쪽), 중간 회차는 실전(문제만 → 정답·풀이는 접어서 확인), 마지막 날은 합격률 최저 2개 회차 이론+실무 최종 모의시험. [회차, 답안지 쪽수, 합격률, 문제지 쪽수, 형태]
  var PRACTICE = [[[92, 19, "61.61", 0], [90, 18, "56.7", 16, "full"]], [[88, 20, "57.28", 17, "full"], [86, 20, "53.39", 17, "full"]], [[85, 20, "59.53", 18, "full"], [83, 19, "57.28", 16, "full"]], [[80, 19, "54.49", 17, "full"], [75, 20, "58.02", 17, "full"]], [[91, 21, "45.61", 18, "full", "final"], [77, 18, "49.55", 14, "full", "final"]]];
  function praImgs(prefix, n, cnt) {
    var h = "";
    for (var i = 1; i <= cnt; i++) {
      h += '<img loading="lazy" src="past/' + prefix + n + '_' + i + '.jpg" alt="제' + n + '회 실무 ' + i + '쪽" style="display:block;width:100%;max-width:760px;margin:8px auto;border:1px solid #bbb;background:#fff">';
    }
    return h;
  }
  function buildPractice() {
    var mock = 0, final = 0;
    PRACTICE.forEach(function (day, di) {
      var el = document.getElementById("praBody" + (di + 1));
      if (!el) return;
      var h = "";
      day.forEach(function (e) {
        var rate = "FAT 1급 합격률 " + e[2] + "%";
        if (e[4] === "full") {
          var best = fullSaved()[e[0]];
          var th = (PAST_PAGES[e[0]] || [0])[0];
          var fin = e[5] === "final";
          if (fin) final++; else mock++;
          h += '<div class="card" style="margin-bottom:12px"><h5>' + (fin ? '최종 모의시험 ' + final : '실전 모의시험 ' + mock) + '회 · 제' + e[0] + '회 <small>(' + rate + (fin ? ' · 최근 20회 중 합격률 ' + (final === 1 ? "최저" : "두 번째로 낮음") : "") + ')</small></h5>' +
            '<p>이론 10문항(30점) + 실무 평가문제 22문항(70점) · 60분 · 합격선 70점. 시험지는 이론 → 실무 순서로 이어서 보입니다.</p>' +
            '<p class="source">실무는 SmartA 프로그램에서 직접 입력·조회한 뒤, 평가문제 답(금액·코드·보기 번호)을 왼쪽 답안 패널에 입력합니다. 답안 줄 앞의 ☆로 문제를 복습 모음(10-17)에 담을 수 있고, 제출하면 100점 만점으로 채점해 정답과 풀이 원본을 보여 줍니다.</p>' +
            '<button type="button" class="btn" data-full="' + e[0] + '" data-th="' + th + '" data-ps="' + e[3] + '" data-pr="' + e[1] + '">시험 시작 (다크 시험 화면)</button>' +
            (best != null ? ' <span class="source">최근 점수 ' + best + '점</span>' : '') + '</div>';
        } else if (!e[3]) {
          h += '<details open><summary>따라하기 1회 · 제' + e[0] + '회 <small>(' + rate + ' · ' + e[1] + '쪽)</small></summary><div>' +
            '<p class="source">원본 인쇄 화면 그대로입니다. 문제(자료설명·수행과제)를 먼저 읽고 프로그램에 직접 입력해 본 뒤, 같은 쪽 아래의 <b>수행과제 풀이</b>와 맞춰 보세요. 마지막 쪽들은 평가문제와 정답입니다.</p>' +
            praImgs("pr", e[0], e[1]) + '</div></details>';
        }
      });
      el.innerHTML = h;
      if (!el.getAttribute("data-fullbound")) {
        el.setAttribute("data-fullbound", "1");
        el.addEventListener("click", function (ev) {
          var b = ev.target.closest && ev.target.closest("[data-full]");
          if (b) openFullExam(parseInt(b.getAttribute("data-full"), 10), parseInt(b.getAttribute("data-th"), 10), parseInt(b.getAttribute("data-ps"), 10), parseInt(b.getAttribute("data-pr"), 10));
        });
      }
    });
  }
  function buildPracticeTopics(el) {
    var P = (window.STUDY || {}).practice;
    if (!el || !P) return;
    function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
    function ans(s) { return esc(s).replace(/⟦/g, '<b class="ans">').replace(/⟧/g, "</b>"); }
    function flow(lines) {
      var out = [];
      lines.forEach(function (l) {
        if (!out.length || /^(\d+\.\s|\d+\)|[①-⑨]|[-•◦·∙*]\s?|\[|\()/.test(l)) out.push(l); else out[out.length - 1] += " " + l;
      });
      return out;
    }
    function pre(lines) { return '<pre class="vsol">' + esc(lines.join("\n")) + "</pre>"; }
    function item(it) {
      var n = it[0], h = '<details><summary>제' + n + '회 · ' + esc(it[1]) + "</summary><div>";
      if (it[2].length) h += '<p><b>자료설명</b></p>' + pre(flow(it[2]));
      if (it[3].length) h += '<p><b>수행과제</b></p>' + pre(flow(it[3]));
      if (it[4].length) h += '<p><b>수행과제 풀이</b></p>' + pre(it[4]);
      h += '<details class="rawsheet"><summary>원본 화면 보기 (자료·풀이 화면 포함)</summary><div>';
      it[5].forEach(function (k) {
        h += '<img loading="lazy" src="past/pr' + n + '_' + k + '.jpg" alt="제' + n + '회 실무 ' + k + '쪽" style="display:block;width:100%;max-width:760px;margin:8px auto;border:1px solid #bbb;background:#fff">';
      });
      return h + "</div></details></div></details>";
    }
    var h = '<h4>실무 유형별 정리 <small>(제75~91회 정답·풀이 포함, 실전 문제를 푼 뒤 복습용)</small></h4>' +
      '<p class="source">출제범위 항목별로 회차를 모았습니다. 자료설명과 수행과제를 읽고 직접 입력한 뒤 풀이와 맞춰 보세요. 풀이 화면(프로그램 캡처)은 "원본 화면 보기"에서 볼 수 있습니다.</p>';
    P.groups.forEach(function (g) {
      var cnt = 0;
      g[2].forEach(function (s) { cnt += s[1].length; });
      h += '<details><summary>' + esc(g[0]) + ' <small>(' + cnt + '건)</small></summary><div><p class="source">' + esc(g[1]) + '</p>';
      g[2].forEach(function (s) {
        if (s[0]) h += '<h5>' + esc(s[0]) + ' <small>(' + s[1].length + '건)</small></h5>';
        s[1].forEach(function (it) { h += item(it); });
      });
      h += "</div></details>";
    });
    h += '<details><summary>자료조회 <small>(평가문제 정답 포함)</small></summary><div><p class="source">부가세 조회, 자금정보 조회, 재무제표·장부 조회 문제입니다. 노란 표시가 정답입니다. 객관식은 옳지 않은 것을 고르는 유형이 많습니다.</p>';
    P.eval.forEach(function (g) {
      h += '<h5>' + esc(g[0]) + ' <small>(' + g[1].length + '문제)</small></h5>';
      g[1].forEach(function (q) {
        h += '<div class="q"><p><b>제' + q[0] + '회 ' + q[1] + '번</b> <span class="src">[' + esc(q[2]) + ']</span></p><pre class="vsol">' + ans(q[3].join("\n")) + "</pre></div>";
      });
    });
    h += '<h5>회계정보분석 <small>(회차별)</small></h5>';
    P.ana.forEach(function (a) {
      h += '<details><summary>제' + a[0] + '회</summary><div><pre class="vsol">' + esc(a[1].join("\n")) + "</pre></div></details>";
    });
    h += "</div></details>";
    var d = document.createElement("div");
    d.id = "practiceTopics";
    d.innerHTML = h;
    el.insertBefore(d, el.firstChild);
  }
  // 이론 정리 항목 제목에 출제 빈도 별표 표시 (제73~92회 이론 200문제 기준)
  function addStars(root, map) {
    if (!root) return;
    var first = null;
    Array.prototype.forEach.call(root.querySelectorAll(":scope > details > summary"), function (s) {
      var m = s.textContent.match(/^(\d+)\./);
      if (!m || !map[m[1]]) return;
      var span = document.createElement("span");
      span.className = "stars";
      span.textContent = " " + new Array(map[m[1]] + 1).join("★");
      s.appendChild(span);
      if (!first) first = s.parentNode;
    });
    if (first) {
      var p = document.createElement("p");
      p.className = "source";
      p.textContent = "★★★ 자주 출제 · ★★ 보통 · ★ 드묾 (제73~92회 이론 기출 기준)";
      root.insertBefore(p, first);
    }
  }
  var S = window.STUDY || {};
  function buildVat(el) {
    if (!el || !S.vatTheory) return;
    var n = 0;
    S.vatQ.forEach(function (g) { n += g[1].length; });
    var d = document.createElement('div');
    d.id = 'vatSection';
    d.innerHTML =
      '<h4>부가가치세 · 기출 60문제 빈출 정리</h4>' + theoryHtml(S.vatTheory) +
      '<h4>부가가치세 필수 문제 <small>(' + n + '문제)</small></h4>' + toolbar() + '<div class="qset">' + groupsHtml(S.vatQ, true) + '</div>';
    el.insertBefore(d, el.firstChild);
    el.addEventListener("click", function (e) {
      var act = e.target.getAttribute && e.target.getAttribute("data-act");
      if (!act) return;
      var set = e.target.parentNode.nextElementSibling;
      Array.prototype.forEach.call(set.querySelectorAll(".q details"), function (d2) { d2.open = act === "open"; });
    });
  }

  build(document.getElementById("finBody"), S.finTheory || [], S.finBasic || [], S.fin60 || [], "재무회계 60제");
  // 원가회계는 FAT 1급 출제범위가 아니라 화면에서 숨김 (cost-*.js 파일은 보관)
  buildVat(document.getElementById("vatBody"));
  addStars(document.getElementById("finBody"), { 1: 3, 2: 3, 3: 3, 4: 1, 5: 2, 6: 1, 7: 1, 8: 1, 9: 3, 10: 1, 11: 2 });
  addStars(document.getElementById("vatSection"), { 1: 2, 2: 3, 3: 3, 4: 3, 5: 2, 6: 3, 7: 3 });
  buildPractice();
  buildPracticeTopics(document.getElementById("praBody1"));
  buildReview(document.getElementById("reviewBody"));
  buildPast(document.getElementById("pastBody"), S.pastExam || []);
})();
