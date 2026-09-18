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

/* --- batch review ------------------------------------------------------
   Client-orchestrated fan-out over the single-label endpoint. Each label is an
   independent request, so there is no server-side job state to build, store or
   expire -- which for a prototype that keeps nothing is the right trade. The
   cost is that a page refresh loses progress; that is stated in the README.

   The browser holds the concurrency limit. Server-side the work runs on a
   thread pool, so these requests genuinely run in parallel: measured 3.5x on
   eight cores, which takes a 300-label batch from about eight minutes to
   under three. */

(function () {
  "use strict";

  var CONCURRENCY = 8;

  var modeSingle = document.getElementById("mode-single");
  var modeBatch = document.getElementById("mode-batch");
  var panelSingle = document.getElementById("panel-single");
  var panelBatch = document.getElementById("panel-batch");
  var recordsInput = document.getElementById("batch-records");
  var imagesInput = document.getElementById("batch-images");
  var runButton = document.getElementById("batch-run");
  var statusBox = document.getElementById("batch-status");
  var resultsBox = document.getElementById("batch-results");

  if (!modeBatch) return;

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function setMode(batch) {
    modeBatch.classList.toggle("is-active", batch);
    modeSingle.classList.toggle("is-active", !batch);
    modeBatch.setAttribute("aria-pressed", String(batch));
    modeSingle.setAttribute("aria-pressed", String(!batch));
    panelBatch.hidden = !batch;
    panelSingle.hidden = batch;
  }
  modeSingle.addEventListener("click", function () { setMode(false); });
  modeBatch.addEventListener("click", function () { setMode(true); });

  function note(message, kind) {
    statusBox.innerHTML = "";
    var box = el("div", "alert alert--" + (kind || "warn"));
    box.setAttribute("role", kind === "error" ? "alert" : "status");
    box.appendChild(document.createTextNode(message));
    statusBox.appendChild(box);
  }

  /* Match an image to a record by looking for the COLA ID in the file name.
     Longest ID first, so "24-0010" is not claimed by "24-001". */
  function matchImages(records, declared, files) {
    var ids = records.map(function (r) { return r.cola_id; })
                     .sort(function (a, b) { return b.length - a.length; });
    var byId = {};
    var unmatched = [];

    Array.prototype.forEach.call(files, function (file) {
      var name = file.name.toLowerCase();
      for (var id in declared) {
        if (declared[id] && declared[id].toLowerCase() === file.name.toLowerCase()) {
          if (!byId[id]) { byId[id] = file; return; }
        }
      }
      for (var i = 0; i < ids.length; i++) {
        if (name.indexOf(ids[i].toLowerCase()) !== -1 && !byId[ids[i]]) {
          byId[ids[i]] = file;
          return;
        }
      }
      unmatched.push(file.name);
    });
    return { byId: byId, unmatched: unmatched };
  }

  function reviewOne(record, file) {
    var body = new FormData();
    body.append("image", file);
    body.append("cola_id", record.cola_id);
    body.append("brand_name", record.brand_name || "");
    body.append("class_type", record.class_type || "");
    body.append("alcohol_content_pct",
                record.alcohol_content_pct === null || record.alcohol_content_pct === undefined
                  ? "" : String(record.alcohol_content_pct));
    body.append("net_contents", record.net_contents || "");
    body.append("bottler_name", record.bottler_name || "");
    body.append("bottler_address", record.bottler_address || "");
    body.append("country_of_origin", record.country_of_origin || "");

    return fetch("/api/review", { method: "POST", body: body })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (payload) {
          if (!response.ok) {
            return { cola_id: record.cola_id, verdict: "error",
                     error: payload.detail || "Server error", checks: [] };
          }
          return payload;
        });
      })
      .catch(function () {
        return { cola_id: record.cola_id, verdict: "error",
                 error: "Could not reach the server", checks: [] };
      });
  }

  /* Bounded worker pool: start N chains, each pulling the next item. */
  function runPool(items, worker, onProgress) {
    var next = 0;
    var done = 0;
    var results = new Array(items.length);

    function chain() {
      if (next >= items.length) return Promise.resolve();
      var index = next++;
      return worker(items[index]).then(function (value) {
        results[index] = value;
        onProgress(++done, items.length);
        return chain();
      });
    }
    var chains = [];
    for (var i = 0; i < Math.min(CONCURRENCY, items.length); i++) chains.push(chain());
    return Promise.all(chains).then(function () { return results; });
  }

  function renderResults(rows, elapsedMs) {
    resultsBox.innerHTML = "";

    var counts = { pass: 0, flag: 0, fail: 0, error: 0 };
    rows.forEach(function (r) { counts[r.verdict] = (counts[r.verdict] || 0) + 1; });

    var summary = el("div", "summary");
    [["fail", "do not meet requirements"], ["flag", "need review"],
     ["pass", "pass"], ["error", "could not be checked"]].forEach(function (pair) {
      if (!counts[pair[0]]) return;
      summary.appendChild(el("span", "pill pill--" + (pair[0] === "error" ? "none" : pair[0]),
                             counts[pair[0]] + " " + pair[1]));
    });
    summary.appendChild(el("span", "pill pill--none",
      rows.length + " labels in " + (elapsedMs / 1000).toFixed(1) + " s"));
    resultsBox.appendChild(summary);

    var exportBtn = el("button", "btn btn--link", "Download results as CSV");
    exportBtn.type = "button";
    exportBtn.addEventListener("click", function () { downloadCsv(rows); });
    resultsBox.appendChild(exportBtn);

    var table = el("table", "results");
    var thead = el("thead");
    var hrow = el("tr");
    ["COLA ID", "Result", "Findings"].forEach(function (h) {
      hrow.appendChild(el("th", null, h));
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    var order = { fail: 0, error: 1, flag: 2, pass: 3 };
    var tbody = el("tbody");
    rows.slice().sort(function (a, b) { return order[a.verdict] - order[b.verdict]; })
        .forEach(function (r) {
      var tr = el("tr", r.verdict === "fail" ? "is-fail" : (r.verdict === "flag" ? "is-flag" : ""));
      tr.appendChild(el("td", null, r.cola_id));
      tr.appendChild(el("td", "results__verdict results__verdict--" + r.verdict,
                        VERDICT_LABEL[r.verdict] || r.verdict));
      tr.appendChild(el("td", null, findingsOf(r)));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    resultsBox.appendChild(table);
  }

  var VERDICT_LABEL = { pass: "Pass", flag: "Review", fail: "Fail", error: "Not checked" };

  var FIELD_NAMES = {
    brand_name: "brand name", class_type: "class/type", alcohol_content: "alcohol content",
    proof_consistency: "proof statement", net_contents: "net contents",
    bottler_name: "bottler", bottler_address: "bottler address",
    country_of_origin: "country of origin", government_warning: "government warning",
    warning_typography: "warning legibility"
  };

  function findingsOf(r) {
    if (r.error) return r.error;
    var bad = (r.checks || []).filter(function (c) { return c.verdict !== "pass"; });
    if (!bad.length) return "All checks passed";
    return bad.map(function (c) {
      return (FIELD_NAMES[c.field] || c.field) + (c.verdict === "fail" ? " (fail)" : " (review)");
    }).join(", ");
  }

  function downloadCsv(rows) {
    var head = ["cola_id", "verdict", "elapsed_ms", "findings"];
    var lines = [head.join(",")];
    rows.forEach(function (r) {
      lines.push([r.cola_id, r.verdict, r.elapsed_ms || "", findingsOf(r)]
        .map(function (v) { return '"' + String(v).replace(/"/g, '""') + '"'; })
        .join(","));
    });
    var blob = new Blob([lines.join("\n")], { type: "text/csv" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "label-review-results.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  runButton.addEventListener("click", async function () {
    resultsBox.innerHTML = "";
    if (!recordsInput.files.length) { note("Choose a records file first.", "error"); return; }
    if (!imagesInput.files.length) { note("Choose the label images to check.", "error"); return; }

    runButton.disabled = true;
    note("Reading application records…");

    var body = new FormData();
    body.append("records", recordsInput.files[0]);

    var parsed;
    try {
      var response = await fetch("/api/batch/records", { method: "POST", body: body });
      parsed = await response.json();
      if (!response.ok) {
        note(parsed.detail || "Could not read that records file.", "error");
        runButton.disabled = false;
        return;
      }
    } catch (err) {
      note("Could not reach the server.", "error");
      runButton.disabled = false;
      return;
    }

    var matched = matchImages(parsed.records, parsed.images || {}, imagesInput.files);
    var work = parsed.records
      .filter(function (r) { return matched.byId[r.cola_id]; })
      .map(function (r) { return { record: r, file: matched.byId[r.cola_id] }; });

    var problems = [];
    if (parsed.errors && parsed.errors.length) problems = problems.concat(parsed.errors);
    var missing = parsed.records.length - work.length;
    if (missing > 0) problems.push(missing + " record(s) had no matching image file.");
    if (matched.unmatched.length) {
      problems.push(matched.unmatched.length +
        " image(s) matched no COLA ID: " + matched.unmatched.slice(0, 5).join(", ") +
        (matched.unmatched.length > 5 ? "…" : ""));
    }

    if (!work.length) {
      note("No images could be matched to a record. Image file names need to contain "
           + "the COLA ID, or the records file needs an image column.", "error");
      runButton.disabled = false;
      return;
    }

    statusBox.innerHTML = "";
    var progressWrap = el("div", "progress");
    var bar = el("div", "progress__bar");
    progressWrap.appendChild(bar);
    var label = el("p", "filename", "Checking 0 of " + work.length + "…");
    statusBox.appendChild(progressWrap);
    statusBox.appendChild(label);

    var started = performance.now();
    var rows = await runPool(work, function (item) {
      return reviewOne(item.record, item.file);
    }, function (done, total) {
      bar.style.width = (100 * done / total) + "%";
      label.textContent = "Checking " + done + " of " + total + "…";
    });
    var elapsed = performance.now() - started;

    label.textContent = "Finished " + work.length + " labels in "
                        + (elapsed / 1000).toFixed(1) + " s.";
    if (problems.length) {
      var warn = el("div", "alert alert--warn");
      warn.setAttribute("role", "status");
      warn.appendChild(el("strong", null, "Some items were skipped. "));
      warn.appendChild(document.createTextNode(problems.join(" ")));
      statusBox.appendChild(warn);
    }

    renderResults(rows, elapsed);
    runButton.disabled = false;
  });
})();
