/* Plain ES modules-free JavaScript: no framework, no build step, no CDN.
   The page must work on whatever browser is on a federal desktop. */

(function () {
  "use strict";

  var form = document.getElementById("review-form");
  var dropzone = document.getElementById("dropzone");
  var fileInput = document.getElementById("image");
  var filename = document.getElementById("filename");
  var result = document.getElementById("result");
  var submit = document.getElementById("submit");

  var FIELD_LABELS = {
    brand_name: "Brand name",
    class_type: "Class / type",
    alcohol_content: "Alcohol content",
    proof_consistency: "Proof statement",
    net_contents: "Net contents",
    bottler_name: "Bottler / producer",
    bottler_address: "Bottler address",
    country_of_origin: "Country of origin",
    government_warning: "Government warning",
    warning_typography: "Warning legibility"
  };

  var MARKS = { pass: "✓", flag: "⚠", fail: "✗" };
  var STATUS = { pass: "Pass", flag: "Review", fail: "Fail" };

  /* The checklist keeps a stable running order -- the same one an agent reads a
     label in, and the same one as the paper checklist it replaces. Within the
     list, unresolved items still sort to the top. */
  var FIELD_ORDER = [
    "brand_name", "class_type", "alcohol_content", "proof_consistency",
    "net_contents", "bottler_name", "bottler_address", "country_of_origin",
    "government_warning", "warning_typography"
  ];
  var VERDICT_TEXT = {
    pass: "Passes all checks",
    flag: "Needs agent review",
    fail: "Does not meet requirements"
  };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function setBusy(busy) {
    submit.disabled = busy;
    submit.textContent = busy ? "Checking…" : "Check this label";
  }

  /* --- file selection ------------------------------------------------ */

  dropzone.addEventListener("click", function () { fileInput.click(); });
  dropzone.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
  });
  ["dragenter", "dragover"].forEach(function (ev) {
    dropzone.addEventListener(ev, function (e) {
      e.preventDefault(); dropzone.classList.add("is-over");
    });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    dropzone.addEventListener(ev, function (e) {
      e.preventDefault(); dropzone.classList.remove("is-over");
    });
  });
  dropzone.addEventListener("drop", function (e) {
    if (e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      showFilename();
    }
  });
  fileInput.addEventListener("change", showFilename);

  function showFilename() {
    filename.textContent = fileInput.files.length
      ? "Selected: " + fileInput.files[0].name
      : "";
  }

  /* --- rendering ------------------------------------------------------ */

  function renderError(message) {
    result.innerHTML = "";
    var box = el("div", "alert alert--error");
    box.setAttribute("role", "alert");
    box.appendChild(el("strong", null, "Could not check this label. "));
    box.appendChild(document.createTextNode(message));
    result.appendChild(box);
  }

  function renderWarningDiff(reason) {
    /* The rule engine puts the word-level deviation after the colon. Surfacing
       it verbatim is what lets an agent see WHY, not just that. */
    var idx = reason.indexOf(": ");
    if (idx === -1) return null;
    var box = el("p", "diff");
    box.appendChild(el("strong", null, "Deviation: "));
    box.appendChild(document.createTextNode(reason.slice(idx + 2)));
    return box;
  }

  function renderCheck(check) {
    var li = el("li", "check check--" + check.verdict);

    li.appendChild(el("span", "check__mark", MARKS[check.verdict]));

    var head = el("p", "check__name");
    head.textContent = FIELD_LABELS[check.field] || check.field;
    var status = el("span", "check__status", STATUS[check.verdict]);
    head.appendChild(status);
    if (check.advisory) head.appendChild(el("span", "check__advisory", "advisory"));
    li.appendChild(head);

    var body = el("div", "check__body");

    if (check.field === "government_warning" && check.verdict !== "pass") {
      var diff = renderWarningDiff(check.reason);
      body.appendChild(el("p", "check__reason",
        diff ? check.reason.split(": ")[0] + "." : check.reason));
      if (diff) body.appendChild(diff);
    } else {
      body.appendChild(el("p", "check__reason", check.reason));
    }

    if (check.expected || check.observed) {
      var dl = el("dl", "check__values");
      [["Application", check.expected], ["Label", check.observed]].forEach(function (pair) {
        if (!pair[1]) return;
        var row = el("div");
        row.appendChild(el("dt", null, pair[0] + ":"));
        var value = pair[1].length > 220 ? pair[1].slice(0, 220) + "…" : pair[1];
        row.appendChild(el("dd", null, value));
        dl.appendChild(row);
      });
      if (dl.children.length) body.appendChild(dl);
    }

    if (check.citation) body.appendChild(el("p", "check__cite", check.citation));

    li.appendChild(body);
    return li;
  }

  function renderResult(data) {
    result.innerHTML = "";

    var banner = el("div", "verdict verdict--" + data.verdict);
    banner.appendChild(el("span", "verdict__label", VERDICT_TEXT[data.verdict]));
    var meta = data.cola_id + " · " + (data.elapsed_ms / 1000).toFixed(1) + " s";
    if (data.cache_hit) meta += " · cached";
    banner.appendChild(el("span", "verdict__meta", meta));
    result.appendChild(banner);

    var list = el("ul", "checks");
    /* FAIL first, then FLAG, then PASS: an agent triages exceptions. */
    var order = { fail: 0, flag: 1, pass: 2 };
    data.checks.slice().sort(function (a, b) {
      if (order[a.verdict] !== order[b.verdict]) {
        return order[a.verdict] - order[b.verdict];
      }
      return FIELD_ORDER.indexOf(a.field) - FIELD_ORDER.indexOf(b.field);
    }).forEach(function (c) { list.appendChild(renderCheck(c)); });
    result.appendChild(list);

    if (data.notes && data.notes.length) {
      var notes = el("div", "notes");
      notes.appendChild(el("strong", null, "Image quality notes"));
      var ul = el("ul");
      data.notes.forEach(function (n) { ul.appendChild(el("li", null, n)); });
      notes.appendChild(ul);
      result.appendChild(notes);
    }
  }

  /* --- requests -------------------------------------------------------- */

  async function send(url, options) {
    setBusy(true);
    try {
      var response = await fetch(url, options);
      var payload = await response.json().catch(function () { return {}; });
      if (!response.ok) {
        renderError(payload.detail || "The server returned an unexpected error.");
        return;
      }
      renderResult(payload);
    } catch (err) {
      renderError("The server could not be reached. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!fileInput.files.length) {
      renderError("Choose a label image before checking.");
      return;
    }
    send("/api/review", { method: "POST", body: new FormData(form) });
  });

  Array.prototype.forEach.call(
    document.querySelectorAll("[data-example]"),
    function (btn) {
      btn.addEventListener("click", function () {
        send("/api/review/example/" + btn.getAttribute("data-example"), { method: "POST" });
      });
    }
  );
})();
