/* NorthRush Outdoors — scroll reveal, staggered grids, count-up, parallax.
   All vanilla; fully disabled under prefers-reduced-motion. */
(function () {
  "use strict";

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Scroll reveal (+ stagger inside .stagger containers) ---------- */
  var revealed = new WeakSet();
  function revealNow(el) {
    el.classList.add("is-revealed");
    revealed.add(el);
  }

  if (reduced || !("IntersectionObserver" in window)) {
    document.querySelectorAll(".reveal").forEach(revealNow);
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting || revealed.has(entry.target)) return;
        var el = entry.target;
        var parent = el.closest(".stagger");
        var delay = 0;
        if (parent) {
          var siblings = Array.prototype.filter.call(
            parent.querySelectorAll(".reveal"),
            function (s) { return !revealed.has(s); }
          );
          delay = Math.min(siblings.indexOf(el), 8) * 60;
        }
        setTimeout(function () { revealNow(el); }, Math.max(delay, 0));
        io.unobserve(el);
      });
    }, { threshold: 0.12, rootMargin: "0px 0px -30px 0px" });
    document.querySelectorAll(".reveal").forEach(function (el) { io.observe(el); });
  }

  /* ---------- Count-up stats ---------- */
  function countUp(el) {
    var target = parseInt(el.getAttribute("data-countup"), 10) || 0;
    var dur = 1200;
    var start = null;
    function frame(ts) {
      if (!start) start = ts;
      var p = Math.min((ts - start) / dur, 1);
      var eased = 1 - Math.pow(1 - p, 3); // ease-out cubic
      el.textContent = Math.round(target * eased);
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  var counters = document.querySelectorAll("[data-countup]");
  if (counters.length) {
    if (reduced || !("IntersectionObserver" in window)) {
      counters.forEach(function (el) { el.textContent = el.getAttribute("data-countup"); });
    } else {
      var cio = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            countUp(entry.target);
            cio.unobserve(entry.target);
          }
        });
      }, { threshold: 0.4 });
      counters.forEach(function (el) { cio.observe(el); });
    }
  }

  /* ---------- Subtle hero parallax ---------- */
  var parallaxEls = document.querySelectorAll("[data-parallax]");
  if (parallaxEls.length && !reduced) {
    var ticking = false;
    window.addEventListener("scroll", function () {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () {
        parallaxEls.forEach(function (el) {
          var rect = el.getBoundingClientRect();
          if (rect.bottom < 0 || rect.top > window.innerHeight) return;
          // Drift relative to how far the element's center is from the viewport center
          var mid = rect.top + rect.height / 2 - window.innerHeight / 2;
          el.style.transform = "translateY(" + (mid * -0.05).toFixed(1) + "px)";
        });
        ticking = false;
      });
    }, { passive: true });
  }
})();
