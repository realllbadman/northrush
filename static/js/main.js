/* NorthRush Outdoors — cart, drawers, filtering, checkout, forms (vanilla JS) */
(function () {
  "use strict";

  var CART_KEY = "northrush_cart_v1";
  var FREE_SHIP = 1500;
  var FLAT_SHIP = 14.99;

  /* ------------------------------------------------------------------ */
  /*  Helpers                                                            */
  /* ------------------------------------------------------------------ */
  function $(sel, ctx) { return (ctx || document).querySelector(sel); }
  function $$(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }
  function money(n) {
    return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function imgUrl(img) {
    if (!img) return "/static/images/placeholder.jpg";
    if (/^https?:\/\//.test(img)) return img;
    return "/static/images/" + img;
  }

  function validEmail(v) {
    return !v || /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v.trim());
  }

  var toastTimer;
  function toast(msg) {
    var el = $("#toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove("is-visible"); }, 2600);
  }

  /* ------------------------------------------------------------------ */
  /*  Cart state                                                         */
  /* ------------------------------------------------------------------ */
  function loadCart() {
    try {
      var raw = JSON.parse(localStorage.getItem(CART_KEY) || "[]");
      return Array.isArray(raw) ? raw : [];
    } catch (e) { return []; }
  }
  function saveCart(cart) {
    localStorage.setItem(CART_KEY, JSON.stringify(cart));
    renderCartUI(cart);
  }
  function cartSubtotal(cart) {
    return cart.reduce(function (s, it) { return s + it.price * it.qty; }, 0);
  }
  function addToCart(item) {
    var cart = loadCart();
    var found = cart.find(function (it) { return it.slug === item.slug; });
    if (found) found.qty += 1;
    else cart.push({ slug: item.slug, name: item.name, price: item.price, qty: 1, image: item.image });
    saveCart(cart);
    toast(item.name + " added to cart");
    openCart();
  }
  function setQty(slug, qty) {
    var cart = loadCart();
    var it = cart.find(function (x) { return x.slug === slug; });
    if (!it) return;
    it.qty = qty;
    if (it.qty <= 0) cart = cart.filter(function (x) { return x.slug !== slug; });
    saveCart(cart);
    renderCheckout();
  }

  /* ------------------------------------------------------------------ */
  /*  Cart drawer UI                                                     */
  /* ------------------------------------------------------------------ */
  function renderCartUI(cart) {
    cart = cart || loadCart();
    var count = cart.reduce(function (s, it) { return s + it.qty; }, 0);
    $$("[data-cart-count]").forEach(function (el) { el.textContent = count; });

    var box = $("#cart-items");
    if (!box) return;
    if (!cart.length) {
      box.innerHTML = '<div class="cart-empty"><p>Your cart is empty.</p><p>Find your next blind →</p></div>';
    } else {
      box.innerHTML = cart.map(function (it) {
        return (
          '<div class="cart-item" data-slug="' + it.slug + '">' +
            '<img class="cart-item__img" src="' + imgUrl(it.image) + '" alt="" ' +
              "onerror=\"this.onerror=null;this.src='/static/images/placeholder.jpg'\">" +
            '<div>' +
              '<div class="cart-item__name">' + it.name + "</div>" +
              '<div class="cart-item__price">' + money(it.price) + " each</div>" +
              '<div class="cart-item__qty">' +
                '<button data-qty="-1" aria-label="Decrease quantity">−</button>' +
                "<span>" + it.qty + "</span>" +
                '<button data-qty="1" aria-label="Increase quantity">+</button>' +
              "</div>" +
            "</div>" +
            '<button class="cart-item__remove" data-remove aria-label="Remove item">&times;</button>' +
          "</div>"
        );
      }).join("");
    }

    var sub = cartSubtotal(cart);
    var subEl = $("#cart-subtotal");
    if (subEl) subEl.textContent = money(sub);
    var ship = $("#cart-ship-note");
    if (ship) {
      if (!cart.length) ship.textContent = "";
      else if (sub > FREE_SHIP) ship.textContent = "✓ You've unlocked FREE domestic shipping";
      else ship.textContent = "Add " + money(FREE_SHIP - sub + 0.01) + " more for free domestic shipping";
    }
  }

  var cartDrawer = $("#cart-drawer");
  var cartBackdrop = $("#cart-backdrop");
  function openCart() {
    if (!cartDrawer) return;
    renderCartUI();
    cartDrawer.classList.add("is-open");
    cartDrawer.setAttribute("aria-hidden", "false");
    cartBackdrop.hidden = false;
    requestAnimationFrame(function () { cartBackdrop.classList.add("is-open"); });
  }
  function closeCart() {
    if (!cartDrawer) return;
    cartDrawer.classList.remove("is-open");
    cartDrawer.setAttribute("aria-hidden", "true");
    cartBackdrop.classList.remove("is-open");
    setTimeout(function () { cartBackdrop.hidden = true; }, 250);
  }

  /* ------------------------------------------------------------------ */
  /*  Mobile drawer                                                      */
  /* ------------------------------------------------------------------ */
  var mobileDrawer = $("#mobile-drawer");
  var mobileBackdrop = $("#mobile-backdrop");
  var hamburger = $("#hamburger");
  function openMobile() {
    mobileDrawer.classList.add("is-open");
    mobileDrawer.setAttribute("aria-hidden", "false");
    hamburger.setAttribute("aria-expanded", "true");
    mobileBackdrop.hidden = false;
    requestAnimationFrame(function () { mobileBackdrop.classList.add("is-open"); });
  }
  function closeMobile() {
    mobileDrawer.classList.remove("is-open");
    mobileDrawer.setAttribute("aria-hidden", "true");
    hamburger.setAttribute("aria-expanded", "false");
    mobileBackdrop.classList.remove("is-open");
    setTimeout(function () { mobileBackdrop.hidden = true; }, 250);
  }

  /* ------------------------------------------------------------------ */
  /*  Products page: live filter + sort                                  */
  /* ------------------------------------------------------------------ */
  function initListing() {
    var grid = $("#product-grid");
    if (!grid) return;
    var search = $("#filter-search");
    var sortSel = $("#sort-select");
    var emptyState = $("#empty-state");
    var countEl = $("#result-count");

    function apply() {
      var q = (search && search.value || "").trim().toLowerCase();
      var cards = $$(".card", grid);
      var visible = 0;
      cards.forEach(function (card) {
        var hay = (card.getAttribute("data-name") || "") + " " +
                  (card.getAttribute("data-subcategory") || "").toLowerCase();
        var show = !q || hay.indexOf(q) !== -1;
        card.style.display = show ? "" : "none";
        if (show) visible++;
      });
      if (countEl) countEl.textContent = visible;
      if (emptyState) emptyState.hidden = visible > 0;
    }

    function sortCards() {
      var mode = sortSel.value;
      var cards = $$(".card", grid);
      cards.sort(function (a, b) {
        if (mode === "name-asc") {
          return (a.getAttribute("data-name") || "").localeCompare(b.getAttribute("data-name") || "");
        }
        var pa = parseFloat(a.getAttribute("data-price")) || 0;
        var pb = parseFloat(b.getAttribute("data-price")) || 0;
        return mode === "price-desc" ? pb - pa : pa - pb;
      });
      cards.forEach(function (c) { grid.appendChild(c); });
    }

    if (search) search.addEventListener("input", apply);
    if (sortSel) sortSel.addEventListener("change", sortCards);

    var toggle = $("#filter-toggle");
    var filters = $("#filters");
    if (toggle && filters) {
      toggle.addEventListener("click", function () {
        var open = filters.classList.toggle("is-open");
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        toggle.textContent = open ? "Close Filters" : "Filters";
      });
    }
  }

  /* ------------------------------------------------------------------ */
  /*  Homepage category chip slider (arrow buttons + edge fades)         */
  /* ------------------------------------------------------------------ */
  function initChipSlider() {
    var slider = $("#chip-slider");
    if (!slider) return;
    var wrap = slider.parentElement;
    var prev = $("#chip-prev");
    var next = $("#chip-next");

    function update() {
      var max = slider.scrollWidth - slider.clientWidth - 1;
      var canLeft = slider.scrollLeft > 1;
      var canRight = slider.scrollLeft < max;
      prev.disabled = !canLeft;
      next.disabled = !canRight;
      wrap.classList.toggle("can-left", canLeft);
      wrap.classList.toggle("can-right", canRight);
    }
    function page(dir) {
      slider.scrollBy({ left: dir * slider.clientWidth * 0.75, behavior: "smooth" });
    }

    prev.addEventListener("click", function () { page(-1); });
    next.addEventListener("click", function () { page(1); });
    slider.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  }

  /* ------------------------------------------------------------------ */
  /*  PDP gallery                                                        */
  /* ------------------------------------------------------------------ */
  function initGallery() {
    var main = $("#pdp-main-img");
    if (!main) return;
    $$(".pdp__thumb").forEach(function (btn) {
      btn.addEventListener("click", function () {
        main.src = btn.getAttribute("data-full");
        $$(".pdp__thumb").forEach(function (b) { b.classList.remove("is-active"); });
        btn.classList.add("is-active");
      });
    });
  }

  /* ------------------------------------------------------------------ */
  /*  Checkout                                                           */
  /* ------------------------------------------------------------------ */
  function freightFee() {
    var sel = $("#freight-region");
    if (!sel) return 0;
    var opt = sel.options[sel.selectedIndex];
    return parseFloat(opt && opt.getAttribute("data-fee")) || 0;
  }

  function checkoutTotals(cart) {
    var sub = cartSubtotal(cart);
    var freight = freightFee();
    var domestic = freight === 0;
    var shipping = !cart.length ? 0 : (domestic ? (sub > FREE_SHIP ? 0 : FLAT_SHIP) : 0);
    return { sub: sub, shipping: shipping, freight: freight, total: sub + shipping + freight, domestic: domestic };
  }

  function renderCheckout() {
    var box = $("#co-items");
    if (!box) return;
    var cart = loadCart();
    if (!cart.length) {
      box.innerHTML = '<div class="cart-empty"><p>Your cart is empty.</p>' +
        '<a class="btn btn--primary btn--sm" href="/products?category=deer-blinds-stands">Shop Blinds</a></div>';
    } else {
      box.innerHTML = cart.map(function (it) {
        return (
          '<div class="cart-item" data-slug="' + it.slug + '">' +
            '<img class="cart-item__img" src="' + imgUrl(it.image) + '" alt="" ' +
              "onerror=\"this.onerror=null;this.src='/static/images/placeholder.jpg'\">" +
            "<div>" +
              '<div class="cart-item__name">' + it.name + "</div>" +
              '<div class="cart-item__price">' + money(it.price) + " each</div>" +
              '<div class="cart-item__qty">' +
                '<button type="button" data-qty="-1" aria-label="Decrease quantity">−</button>' +
                "<span>" + it.qty + "</span>" +
                '<button type="button" data-qty="1" aria-label="Increase quantity">+</button>' +
              "</div>" +
            "</div>" +
            '<button type="button" class="cart-item__remove" data-remove aria-label="Remove item">&times;</button>' +
          "</div>"
        );
      }).join("");
    }
    var t = checkoutTotals(cart);
    $("#co-subtotal").textContent = money(t.sub);
    $("#co-shipping").textContent = !cart.length ? "—" :
      (t.domestic ? (t.shipping === 0 ? "FREE" : money(t.shipping)) : "—");
    $("#co-freight").textContent = money(t.freight);
    $("#co-total").textContent = money(t.total);
  }

  function initCheckout() {
    var form = $("#checkout-form");
    if (!form) return;
    renderCheckout();

    var region = $("#freight-region");
    if (region) region.addEventListener("change", renderCheckout);

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var cart = loadCart();
      if (!cart.length) { toast("Your cart is empty — add a blind first!"); return; }
      var fd = new FormData(form);
      if (!fd.get("first_name") || !fd.get("phone")) {
        toast("Please add your name and phone number");
        return;
      }
      if (!validEmail(fd.get("email"))) {
        toast("That email doesn't look right — please check it");
        return;
      }
      var t = checkoutTotals(cart);
      var payload = {
        first_name: fd.get("first_name") || "",
        last_name: fd.get("last_name") || "",
        phone: fd.get("phone") || "",
        email: fd.get("email") || "",
        company: fd.get("company") || "",
        address: fd.get("address") || "",
        city: fd.get("city") || "",
        state: fd.get("state") || "",
        zip: fd.get("zip") || "",
        country: fd.get("country") || "United States",
        freight_region: fd.get("freight_region") || "United States",
        contact_pref: fd.get("contact_pref") || "Phone",
        best_time: fd.get("best_time") || "",
        payment_method: fd.get("payment_method") || "Bank Transfer",
        notes: fd.get("notes") || "",
        website: fd.get("website") || "",
        items: cart,
        total: Math.round(t.total * 100) / 100
      };
      var btn = $("#checkout-submit");
      btn.disabled = true;
      btn.textContent = "Sending…";
      fetch("/inquiries/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (data) {
        localStorage.removeItem(CART_KEY);
        renderCartUI([]);
        $("#checkout-layout").hidden = true;
        var success = $("#co-success");
        success.hidden = false;
        if (data.message) $("#co-success-msg").textContent = data.message;
        success.scrollIntoView({ behavior: "smooth", block: "center" });
      }).catch(function () {
        toast("Something went wrong — please try again or call us");
        btn.disabled = false;
        btn.textContent = "Submit Order Request";
      });
    });
  }

  /* ------------------------------------------------------------------ */
  /*  Booking forms (financing + contact)                                */
  /* ------------------------------------------------------------------ */
  function initBookingForm(formId, service) {
    var form = document.getElementById(formId);
    if (!form) return;
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var fd = new FormData(form);
      if (!fd.get("first_name")) { toast("Please add your first name"); return; }
      if (!validEmail(fd.get("email"))) {
        toast("That email doesn't look right — please check it");
        return;
      }
      var payload = {
        first_name: fd.get("first_name") || "",
        last_name: fd.get("last_name") || "",
        phone: fd.get("phone") || "",
        email: fd.get("email") || "",
        service: fd.get("service") || service,
        product_interest: fd.get("product_interest") || "",
        details: fd.get("details") || "",
        website: fd.get("website") || ""
      };
      var btn = form.querySelector('button[type="submit"]');
      var orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Sending…";
      fetch("/bookings/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      }).then(function (data) {
        form.reset();
        toast(data.message || "Request sent — we'll be in touch!");
        btn.disabled = false;
        btn.textContent = orig;
      }).catch(function () {
        toast("Something went wrong — please try again or call us");
        btn.disabled = false;
        btn.textContent = orig;
      });
    });
  }

  /* ------------------------------------------------------------------ */
  /*  Global event wiring                                                 */
  /* ------------------------------------------------------------------ */
  document.addEventListener("click", function (e) {
    var add = e.target.closest("[data-add-to-cart]");
    if (add) {
      addToCart({
        slug: add.getAttribute("data-slug"),
        name: add.getAttribute("data-name"),
        price: parseFloat(add.getAttribute("data-price")) || 0,
        image: add.getAttribute("data-image")
      });
      return;
    }
    var qtyBtn = e.target.closest("[data-qty]");
    if (qtyBtn) {
      var row = qtyBtn.closest(".cart-item");
      var slug = row.getAttribute("data-slug");
      var cart = loadCart();
      var it = cart.find(function (x) { return x.slug === slug; });
      if (it) setQty(slug, it.qty + parseInt(qtyBtn.getAttribute("data-qty"), 10));
      return;
    }
    var removeBtn = e.target.closest("[data-remove]");
    if (removeBtn) {
      setQty(removeBtn.closest(".cart-item").getAttribute("data-slug"), 0);
      return;
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { closeCart(); closeMobile(); }
  });

  var el;
  if ((el = $("#cart-open"))) el.addEventListener("click", openCart);
  if ((el = $("#cart-close"))) el.addEventListener("click", closeCart);
  if ((el = $("#cart-continue"))) el.addEventListener("click", closeCart);
  if (cartBackdrop) cartBackdrop.addEventListener("click", closeCart);
  if (hamburger) hamburger.addEventListener("click", openMobile);
  if ((el = $("#mobile-close"))) el.addEventListener("click", closeMobile);
  if (mobileBackdrop) mobileBackdrop.addEventListener("click", closeMobile);

  /* ------------------------------------------------------------------ */
  /*  Boot                                                                */
  /* ------------------------------------------------------------------ */
  renderCartUI();
  initChipSlider();
  initListing();
  initGallery();
  initCheckout();
  initBookingForm("financing-form", "Financing");
  initBookingForm("contact-form", "General");
})();
