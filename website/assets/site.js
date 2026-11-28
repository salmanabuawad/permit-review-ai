/* Permit360 website — navigation, live committee lookup, interactive demo, demo-request form. No dependencies. */
(function () {
  "use strict";
  var doc = document.documentElement;
  doc.classList.remove("no-js");
  var API = doc.getAttribute("data-api") || "";
  var APP = doc.getAttribute("data-app") || "";
  var LANG = doc.lang || "he";
  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function data(id) { var el = document.getElementById(id); return el ? JSON.parse(el.textContent) : null; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function fmt(n) { try { return new Intl.NumberFormat(LANG === "ar" ? "ar-EG" : LANG).format(n); } catch (e) { return String(n); } }

  /* ---------------- header: mobile menu and guides dropdown */
  var header = $(".site-header"), menuBtn = $(".menu-btn");
  var onScroll = function () { if (header) header.classList.toggle("scrolled", window.scrollY > 8); };
  window.addEventListener("scroll", onScroll, { passive: true }); onScroll();
  if (menuBtn) menuBtn.addEventListener("click", function () {
    var open = header.toggleAttribute("data-open");
    menuBtn.setAttribute("aria-expanded", String(open));
  });
  $$(".nav-drop, .lang-drop").forEach(function (d) {
    var b = $("button", d);
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = d.toggleAttribute("data-open");
      b.setAttribute("aria-expanded", String(open));
    });
  });
  document.addEventListener("click", function (e) {
    $$(".nav-drop[data-open], .lang-drop[data-open]").forEach(function (d) { if (!d.contains(e.target)) { d.removeAttribute("data-open"); $("button", d).setAttribute("aria-expanded", "false"); } });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    $$(".nav-drop[data-open], .lang-drop[data-open]").forEach(function (d) { d.removeAttribute("data-open"); var b = $("button", d); b.setAttribute("aria-expanded", "false"); b.focus(); });
  });

  /* ---------------- reveal on scroll */
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (es) { es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }); }, { rootMargin: "0px 0px -8% 0px" });
    $$(".reveal").forEach(function (el) { io.observe(el); });
  } else { $$(".reveal").forEach(function (el) { el.classList.add("in"); }); }

  /* ---------------- live committee lookup (real data: /api/public/committee) */
  var lookup = $("#lookup-form");
  if (lookup) {
    var L = data("lookup-i18n"), out = $("#lookup-result"), btn = $("button[type=submit]", lookup);
    var DISTRICT = L.districts || {};
    lookup.addEventListener("submit", function (e) {
      e.preventDefault();
      var g = lookup.gush.value.trim(), h = lookup.helka.value.trim();
      if (!/^\d{1,6}$/.test(g) || !/^\d{1,5}$/.test(h) || +g === 0 || +h === 0) { show('<p class="lr-msg" role="alert">' + esc(L.invalid) + "</p>"); return; }
      btn.disabled = true; var label = btn.textContent; btn.textContent = L.checking;
      out.setAttribute("aria-busy", "true");
      fetch(API + "/api/public/committee?gush=" + g + "&helka=" + h, { headers: { "Accept": "application/json" } })
        .then(function (r) { if (r.status === 429) throw "rate"; if (!r.ok) throw "error"; return r.json(); })
        .then(render)
        .catch(function (k) { show('<p class="lr-msg" role="alert">' + esc(L[k === "rate" ? "rate" : "error"]) + "</p>"); })
        .then(function () { btn.disabled = false; btn.textContent = label; out.removeAttribute("aria-busy"); });
    });
    function show(html) { out.innerHTML = html; }
    function facts(rows) {
      return '<dl class="lr-grid">' + rows.filter(function (r) { return r[1]; }).map(function (r) { return "<div><dt>" + esc(r[0]) + "</dt><dd>" + r[1] + "</dd></div>"; }).join("") + "</dl>";
    }
    function render(r) {
      var c = r.candidates || [], linked = c.filter(function (x) { return x.committee; });
      var parcel = r.parcel_area_m2 ? '<span class="m-num">' + fmt(Math.round(r.parcel_area_m2)) + "</span> " + esc(L.sqm) : "";
      var loc = (r.localities || []).join(", ");
      var head = '<div class="lr-title">' + esc(L.gush) + ' <bdi class="m-num">' + esc(r.gush) + "</bdi> · " + esc(L.helka) + ' <bdi class="m-num">' + esc(r.helka) + "</bdi></div>";
      var cont = '<div class="lr-actions"><a class="btn btn-primary btn-sm" href="' + APP + "/apply?lang=" + LANG + '">' + esc(L["continue"]) + ' <span class="arrow" aria-hidden="true">→</span></a></div><p class="lr-note">' + esc(L.note) + "</p>";
      if (r.status === "RESOLVED" && c[0]) {
        var a = c[0];
        show(head + '<div class="lr-title" style="margin-top:10px">' + esc(L.resolved) + '</div><div class="lr-committee" lang="he">' + esc(a.committee) + "</div>" +
          facts([[L.area, '<span lang="he">' + esc(a.area) + "</span>"], [L.code, '<span class="m-num">' + esc(a.code) + "</span>"], [L.district, esc(DISTRICT[a.district] || a.district)],
                 [L.locality, '<span lang="he">' + esc(loc) + "</span>"], [L.parcel_area, parcel]]) + cont);
      } else if (r.status === "AMBIGUOUS") {
        show(head + '<div class="lr-committee" style="font-size:20px">' + esc(L.ambiguous.replace("{n}", c.length)) + '</div><ul class="lr-cands">' +
          c.map(function (x) { return '<li><div><b lang="he">' + esc(x.committee || x.area) + '</b><div class="bar" style="width:' + Math.max(4, Math.round(x.share * 100)) + '%"></div></div><span class="m-num">' + fmt(Math.round(x.share * 1000) / 10) + "% " + esc(L.share) + "</span></li>"; }).join("") +
          "</ul>" + facts([[L.parcel_area, parcel]]) + cont);
      } else if (r.status === "UNLINKED") {
        show(head + '<p class="lr-msg">' + esc(L.unlinked) + "</p>" + (c[0] ? facts([[L.area, '<span lang="he">' + esc(c[0].area) + "</span>"], [L.code, esc(c[0].code)]]) : ""));
      } else {
        show(head + '<p class="lr-msg">' + esc(L.not_found) + "</p>");
      }
    }
  }

  /* ---------------- interactive demo (illustration with example data) */
  var demo = $("#demo");
  if (demo) {
    var D = data("demo-i18n"), M = data("demo-mock"), role = "pro", i = 0;
    var stepsEl = $(".steps", demo), screen = $(".screen-body", demo), counter = $(".stage-nav span", demo), path = $(".screen-bar span", demo);
    function steps() { return role === "pro" ? D.steps_pro : D.steps_authority; }
    function draw() {
      var s = steps();
      stepsEl.innerHTML = s.map(function (st, k) {
        return '<li><button type="button" data-i="' + k + '"' + (k === i ? ' aria-current="step"' : "") + (k < i ? ' class="done"' : "") + '><span class="n">' + (k + 1) + "</span><span><b>" + esc(st.title) + "</b><small>" + esc(st.text) + "</small></span></button></li>";
      }).join("");
      screen.innerHTML = M[role][i];
      screen.style.animation = "none"; void screen.offsetWidth; screen.style.animation = "";
      counter.textContent = D.step.replace("{n}", i + 1);
      path.textContent = (role === "pro" ? "permit360.kortexd.com/apply" : "permit360.kortexd.com/cases/demo") + " · " + (i + 1) + "/6";
      $(".prev", demo).disabled = i === 0; $(".next", demo).disabled = i === s.length - 1;
    }
    $$(".tabs button", demo).forEach(function (b) {
      b.addEventListener("click", function () {
        role = b.getAttribute("data-role"); i = 0;
        $$(".tabs button", demo).forEach(function (x) { x.setAttribute("aria-selected", String(x === b)); x.tabIndex = x === b ? 0 : -1; });
        $("#demo-panel").setAttribute("aria-labelledby", b.id);
        draw();
      });
    });
    $(".tabs", demo).addEventListener("keydown", function (e) {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      var t = $$(".tabs button", demo), k = t.indexOf(document.activeElement); if (k < 0) return;
      var n = t[(k + 1) % t.length]; n.focus(); n.click();
    });
    stepsEl.addEventListener("click", function (e) { var b = e.target.closest("button[data-i]"); if (b) { i = +b.getAttribute("data-i"); draw(); } });
    $(".prev", demo).addEventListener("click", function () { if (i > 0) { i--; draw(); } });
    $(".next", demo).addEventListener("click", function () { if (i < steps().length - 1) { i++; draw(); } });
    draw();
  }

  /* ---------------- demo request form (POST /api/public/demo-request) */
  var form = $("#demo-form");
  if (form) {
    var F = data("form-i18n"), msg = $(".form-msg", form), submit = $("button[type=submit]", form);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      msg.className = "form-msg"; msg.textContent = "";
      if (!form.checkValidity()) { msg.className = "form-msg err"; msg.textContent = F.required; form.reportValidity(); return; }
      var body = { name: form.name.value, email: form.email.value, organization: form.organization.value, role: form.role.value, phone: form.phone.value,
                   message: form.message.value, consent: form.consent.checked, website: form.website.value, lang: LANG };
      submit.disabled = true; var label = submit.textContent; submit.textContent = F.sending;
      fetch(API + "/api/public/demo-request", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        .then(function (r) { if (r.status === 429) throw "rate"; if (r.status === 422) throw "required"; if (!r.ok) throw "error"; })
        .then(function () { form.reset(); msg.className = "form-msg ok"; msg.textContent = F.ok; })
        .catch(function (k) { msg.className = "form-msg err"; msg.textContent = F[k] || F.error; })
        .then(function () { submit.disabled = false; submit.textContent = label; });
    });
  }
})();
