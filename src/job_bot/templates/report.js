(function () {
  "use strict";
  var root = document.documentElement;
  var data = JSON.parse(document.getElementById("job-data").textContent);
  var grid = document.getElementById("grid");
  var cards = Array.prototype.slice.call(grid.querySelectorAll(".card"));
  var q = document.getElementById("q");
  var city = document.getElementById("city");
  var source = document.getElementById("source");
  var sort = document.getElementById("sort");
  var reset = document.getElementById("reset");
  var count = document.getElementById("count");
  var empty = document.getElementById("empty");
  var chips = Array.prototype.slice.call(document.querySelectorAll(".chip"));
  var targets = cards.map(function (card) {
    return Array.prototype.slice.call(card.querySelectorAll(".card-title, .card-desc")).map(function (el) {
      return { el: el, html: el.innerHTML };
    });
  });

  function fold(text) {
    var out = "";
    for (var i = 0; i < text.length; i++) {
      out += text[i].normalize("NFD").charAt(0).toLowerCase();
    }
    return out;
  }

  function terms() {
    return fold(q.value).replace(/[^\w\s]+/g, " ").split(/\s+/).filter(Boolean);
  }

  function mark(el, words) {
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (node) {
      var text = node.nodeValue;
      var folded = fold(text);
      var ranges = [];
      words.forEach(function (w) {
        var at = folded.indexOf(w);
        while (at !== -1) {
          ranges.push([at, at + w.length]);
          at = folded.indexOf(w, at + w.length);
        }
      });
      if (!ranges.length) return;
      ranges.sort(function (a, b) { return a[0] - b[0]; });
      var frag = document.createDocumentFragment();
      var last = 0;
      ranges.forEach(function (r) {
        if (r[0] < last) return;
        frag.appendChild(document.createTextNode(text.slice(last, r[0])));
        var m = document.createElement("mark");
        m.className = "q";
        m.textContent = text.slice(r[0], r[1]);
        frag.appendChild(m);
        last = r[1];
      });
      frag.appendChild(document.createTextNode(text.slice(last)));
      node.parentNode.replaceChild(frag, node);
    });
  }

  var current = "";

  var comparators = {
    score: function (a, b) { return data[b].k - data[a].k || data[b].d - data[a].d; },
    recent: function (a, b) { return data[b].d - data[a].d; },
    old: function (a, b) { return data[a].d - data[b].d; },
    distance: function (a, b) {
      var x = data[a].km, y = data[b].km;
      return (x === null) - (y === null) || (x || 0) - (y || 0);
    },
    company: function (a, b) { return data[a].co.localeCompare(data[b].co, "fr"); }
  };

  function apply() {
    var words = terms();
    var contracts = chips.filter(function (c) { return c.getAttribute("aria-pressed") === "true"; })
      .map(function (c) { return c.dataset.contract; });
    var shown = 0;
    var order = cards.map(function (_, i) { return i; }).sort(comparators[sort.value] || comparators.recent);
    order.forEach(function (i) {
      var item = data[i];
      var ok = words.every(function (w) { return item.t.indexOf(w) !== -1; })
        && (!contracts.length || contracts.indexOf(item.c) !== -1)
        && (!city.value || item.v === city.value)
        && (!source.value || item.s === source.value);
      cards[i].hidden = !ok;
      if (ok) shown++;
      targets[i].forEach(function (t) {
        t.el.innerHTML = t.html;
        if (words.length) mark(t.el, words);
      });
    });
    var key = order.join(",");
    if (key !== current) {
      order.forEach(function (i) { grid.appendChild(cards[i]); });
      current = key;
    }
    count.textContent = shown + " sur " + cards.length;
    empty.hidden = shown !== 0;
    reset.hidden = !(words.length || contracts.length || city.value || source.value);
  }

  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      chip.setAttribute("aria-pressed", chip.getAttribute("aria-pressed") === "true" ? "false" : "true");
      apply();
    });
  });
  q.addEventListener("input", apply);
  [city, source, sort].forEach(function (el) { el.addEventListener("change", apply); });
  reset.addEventListener("click", function () {
    q.value = "";
    city.value = "";
    source.value = "";
    chips.forEach(function (c) { c.setAttribute("aria-pressed", "false"); });
    apply();
    q.focus();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && document.activeElement !== q) {
      e.preventDefault();
      q.focus();
    }
  });

  document.getElementById("theme-toggle").addEventListener("click", function () {
    var dark = root.dataset.theme
      ? root.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    var next = dark ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("job-bot-theme", next); } catch (e) {}
  });

  current = cards.map(function (_, i) { return i; }).join(",");
  apply();
})();
