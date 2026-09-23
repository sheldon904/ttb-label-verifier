/* Plain JavaScript: no framework, no build step, no CDN. The page must work on
   whatever browser is on a federal desktop. Markup and components follow the
   U.S. Web Design System (USWDS), which is served from this app. */

(function () {
  "use strict";

  /* --- shared ------------------------------------------------------------ */

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function plural(n, one, many) {
    return n + " " + (n === 1 ? one : (many || one + "s"));
  }

  /* "1.3 s", or "under 0.1 s" for a label already read. */
  function seconds(ms) {
    return ms < 100 ? "under 0.1 s" : (ms / 1000).toFixed(1) + " s";
  }

  var TRIAGE_TEXT = function (p) {
    if (p >= 0.6) return "Likely a real problem with the label";
    if (p <= 0.4) return "Likely a reading problem, not the label";
    return "Unclear whether the label or the image is at fault";
  };

  /* A USWDS file input that refused a file shows its own error and keeps no
     file; the page says what to do instead of asking for a file again. */
  function refusedFile(input) {
    var wrap = input.closest(".usa-file-input");
    return Boolean(wrap && wrap.querySelector(".has-invalid-file"));
  }

  initSingle();
  initBatch();

  /* --- one label --------------------------------------------------------- */

  function initSingle() {
    var form = document.getElementById("review-form");
    var fileInput = document.getElementById("image");
    var result = document.getElementById("result");
    var status = document.getElementById("result-status");
    var submit = document.getElementById("submit");
    var artwork = document.getElementById("artwork");
    var artworkImg = document.getElementById("artwork-img");
    var artworkCaption = document.getElementById("artwork-caption");
    var printButton = document.getElementById("print");
    var boxesSvg = document.getElementById("artwork-boxes");
    var boxesToggle = document.getElementById("boxes-toggle");
    var boxesToggleWrap = document.getElementById("boxes-toggle-wrap");
    var SVG_NS = "http://www.w3.org/2000/svg";
    var ACCEPTED = /^image\/(jpeg|png|webp|tiff)$/;

    /* Rows that share the line they were read from share its box. */
    var BOX_OF = { alcohol_format: "alcohol_content", proof_consistency: "alcohol_content" };
    var LAYERS = [
      ["application", "Label against the application"],
      ["regulation", "Label against the regulation"]
    ];

    var FIELD_LABELS = {
      brand_name: "Brand name",
      class_type: "Class / type",
      alcohol_content: "Alcohol content",
      alcohol_format: "Alcohol statement wording",
      proof_consistency: "Proof statement",
      net_contents: "Net contents",
      bottler_name: "Bottler / producer",
      bottler_address: "Bottler address",
      country_of_origin: "Country of origin",
      government_warning: "Government warning",
      warning_typography: "Warning type and size"
    };

    /* Where a row's expected value comes from, when it is not the application:
       the warning is compared with the statute, and the proof with twice the
       label's own percentage. */
    var EXPECTED_FROM = { government_warning: "Required", proof_consistency: "Expected" };

    var MARKS = { pass: "✓", flag: "⚠", fail: "✗" };
    var STATUS = { pass: "Pass", flag: "Review", fail: "Fail" };

    /* The checklist keeps a stable running order -- the same one an agent reads a
       label in, and the same one as the paper checklist it replaces. Within the
       list, unresolved items still sort to the top. */
    var FIELD_ORDER = [
      "brand_name", "class_type", "alcohol_content", "alcohol_format", "proof_consistency",
      "net_contents", "bottler_name", "bottler_address", "country_of_origin",
      "government_warning", "warning_typography"
    ];
    var VERDICT_TEXT = {
      pass: "Passes all checks",
      flag: "Needs agent review",
      fail: "Does not meet requirements"
    };
    var ALERT_KIND = { pass: "success", flag: "warning", fail: "error" };

    /* A USWDS alert: kind is success, warning, error or info. */
    function alertBox(kind, heading, text) {
      var box = el("div", "usa-alert usa-alert--" + kind);
      var body = el("div", "usa-alert__body");
      if (heading) body.appendChild(el("h3", "usa-alert__heading", heading));
      var p = el("p", "usa-alert__text");
      if (typeof text === "string") p.textContent = text; else if (text) p.appendChild(text);
      body.appendChild(p);
      box.appendChild(body);
      return box;
    }

    /* Screen readers hear one short sentence per result, not the whole
       checklist read out again. A newer sentence replaces one still waiting. */
    var announceTimer = 0;
    function announce(text) {
      window.clearTimeout(announceTimer);
      status.textContent = "";
      announceTimer = window.setTimeout(function () { status.textContent = text; }, 50);
    }

    function setBusy(busy) {
      submit.disabled = busy;
      submit.textContent = busy ? "Checking…" : "Check this label";
    }

    /* --- artwork preview -------------------------------------------------
       Jenny checks "with my eyes". The checklist is only useful next to the
       thing it describes, so whatever is being checked is shown beside it. */

    var previewUrl = null;

    /* `ownsUrl` marks a blob URL made for an uploaded file. The previous one is
       released when a new image replaces it, never the one being shown: an
       earlier version revoked the new URL itself and every upload previewed as a
       broken image. */
    function showArtwork(src, caption, ownsUrl) {
      if (previewUrl && previewUrl !== src) URL.revokeObjectURL(previewUrl);
      previewUrl = ownsUrl ? src : null;
      artworkImg.hidden = false;
      artworkImg.src = src;
      artworkCaption.textContent = caption || "";
      artwork.hidden = false;
      clearBoxes();
    }

    /* A file the browser cannot draw (TIFF in Chrome and Edge) keeps its
       caption and loses the broken-image icon; the server sends a picture of
       it with the result. */
    artworkImg.addEventListener("error", function () {
      artworkImg.hidden = true;
    });

    /* --- evidence boxes --------------------------------------------------
       Where on the artwork each field was read, coloured by its result. The
       OCR works on a straightened, enlarged copy; the server maps every box
       back onto the picture as it is shown here, so a tilted photo gets
       tilted boxes. Clicking a checklist row picks out its box. */

    function clearBoxes() {
      while (boxesSvg.firstChild) boxesSvg.removeChild(boxesSvg.firstChild);
      boxesToggleWrap.hidden = true;
    }

    function drawBoxes(boxes, checks) {
      clearBoxes();
      if (!boxes || artworkImg.hidden) return;
      var rank = { pass: 0, flag: 1, fail: 2 };
      var worst = {};
      checks.forEach(function (c) {
        var key = BOX_OF[c.field] || c.field;
        if (!(key in worst) || rank[c.verdict] > rank[worst[key]]) worst[key] = c.verdict;
      });
      var drawn = 0;
      Object.keys(boxes).forEach(function (key) {
        var quad = boxes[key];
        var poly = document.createElementNS(SVG_NS, "polygon");
        poly.setAttribute("points", quad.map(function (p) { return p[0] + "," + p[1]; }).join(" "));
        poly.setAttribute("class", "box box--" + (worst[key] || "pass"));
        poly.setAttribute("data-field", key);
        boxesSvg.appendChild(poly);
        drawn++;
      });
      boxesToggleWrap.hidden = drawn === 0;
      boxesSvg.style.display = boxesToggle.checked ? "" : "none";
    }

    function highlightBox(field) {
      var key = BOX_OF[field] || field;
      Array.prototype.forEach.call(boxesSvg.querySelectorAll("polygon"), function (p) {
        p.classList.toggle("is-active", p.getAttribute("data-field") === key);
      });
    }

    boxesToggle.addEventListener("change", function () {
      boxesSvg.style.display = boxesToggle.checked ? "" : "none";
    });

    function showArtworkFile(file) {
      showArtwork(URL.createObjectURL(file), file.name, true);
    }

    /* --- file selection ------------------------------------------------
       The USWDS file input provides the drop target, the file name and its own
       thumbnail; the full-size preview goes beside the checklist. */

    /* A sample fills in its application details, so the checklist can be read
       against what the application says. With no file chosen, "Check this
       label" checks the sample again against the form as it now stands: change
       the alcohol content and the alcohol row fails. Choosing a file ends the
       sample. */
    var currentSample = null;
    var FORM_FIELDS = ["cola_id", "brand_name", "class_type", "alcohol_content_pct",
                       "net_contents", "bottler_name", "bottler_address", "country_of_origin"];

    function fillForm(record) {
      FORM_FIELDS.forEach(function (name) {
        var value = record[name];
        form.elements[name].value = value === null || value === undefined ? "" : String(value);
      });
    }

    /* USWDS has no reset for its file input, so this undoes what it draws when
       a file is chosen: the preview, the "Selected file" heading and the
       hidden instructions. */
    function clearFileInput() {
      fileInput.value = "";
      var wrap = fileInput.closest(".usa-file-input");
      if (!wrap) return;
      Array.prototype.forEach.call(
        wrap.querySelectorAll(".usa-file-input__preview, .usa-file-input__preview-heading"),
        function (node) { node.parentNode.removeChild(node); });
      var instructions = wrap.querySelector(".usa-file-input__instructions");
      if (instructions) instructions.removeAttribute("hidden");
    }

    fileInput.addEventListener("change", function () {
      /* USWDS checks the type first and clears a refused file. A PDF or a
         GIF is never previewed, and whatever was on show goes with it. */
      var file = fileInput.files[0];
      if (file && ACCEPTED.test(file.type)) {
        currentSample = null;
        showArtworkFile(file);
      } else if (refusedFile(fileInput)) {
        currentSample = null;
        artwork.hidden = true;
      }
    });

    /* --- rendering ------------------------------------------------------ */

    /* The alert speaks for itself; a "Checking" sentence still waiting must
       not follow it. */
    function renderError(message) {
      result.innerHTML = "";
      printButton.hidden = true;
      clearBoxes();
      window.clearTimeout(announceTimer);
      status.textContent = "";
      var box = alertBox("error", "Could not check this label", message);
      box.setAttribute("role", "alert");
      result.appendChild(box);
    }

    /* While a label is being checked the previous result is gone: a verdict
       under someone else's artwork is worse than no verdict. */
    function renderChecking() {
      result.innerHTML = "";
      printButton.hidden = true;
      clearBoxes();
      var line = el("p", "pending-line");
      line.appendChild(el("span", "spinner"));
      line.appendChild(document.createTextNode(" Checking this label…"));
      result.appendChild(line);
      announce("Checking the label.");
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
      var tag = el("span", "usa-tag check__status", STATUS[check.verdict]);
      head.appendChild(tag);
      if (check.advisory) head.appendChild(el("span", "check__advisory", "advisory"));
      if (check.source === "second_opinion") {
        head.appendChild(el("span", "check__source", "from a second reading"));
      }
      li.appendChild(head);
      li.tabIndex = 0;
      li.addEventListener("click", function () { highlightBox(check.field); });
      li.addEventListener("focus", function () { highlightBox(check.field); });

      var body = el("div", "check__body");

      var wordingDiff = check.field === "government_warning" && check.verdict === "fail"
        && check.reason.indexOf("statutory wording: ") !== -1;
      if (wordingDiff) {
        var diff = renderWarningDiff(check.reason);
        body.appendChild(el("p", "check__reason",
          diff ? check.reason.split(": ")[0] + "." : check.reason));
        if (diff) body.appendChild(diff);
      } else {
        body.appendChild(el("p", "check__reason", check.reason));
      }

      if (check.expected || check.observed) {
        var dl = el("dl", "check__values");
        [[EXPECTED_FROM[check.field] || "Application", check.expected],
         ["Label", check.observed]].forEach(function (pair) {
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

    /* `ocrMs` is set when this result carries a second reading: the time shown
       is then the OCR's, followed by the model's, never "from memory".
       Returns the sentence announced to screen readers. */
    function renderResult(data, ocrMs) {
      result.innerHTML = "";

      var meta = data.cola_id + " · ";
      var so = data.second_opinion;
      meta += ocrMs === undefined ? seconds(data.elapsed_ms)
        : "OCR " + seconds(ocrMs) + ", second reading " + seconds(data.elapsed_ms);
      if (so && so.pending) {
        meta += " · second reading in progress";
      } else if (so && so.cleared && so.cleared.length) {
        meta += " · " + plural(so.cleared.length, "row") + " cleared by a second reading ("
          + so.model + ")";
      } else if (so && so.unavailable) {
        meta += " · second reading unavailable, referral stands";
      } else if (so) {
        meta += " · second reading (" + so.model + ") did not change the result";
      }
      var banner = alertBox(ALERT_KIND[data.verdict], VERDICT_TEXT[data.verdict], meta);
      banner.className += " verdict verdict--" + data.verdict;
      result.appendChild(banner);

      /* On paper the checklist has to say which application it is and when it
         was checked; on screen the form beside it says so. */
      result.appendChild(el("p", "print-only",
        "COLA ID " + data.cola_id + ", checked " + new Date().toLocaleString() + "."));

      if (data.verdict === "flag" && data.triage) {
        var t = el("p", "triage-line");
        t.appendChild(el("strong", null, TRIAGE_TEXT(data.triage.probability) + ". "));
        t.appendChild(document.createTextNode(
          "Referral triage (" + data.triage.provider + ") puts the chance of a genuine defect at "
          + Math.round(data.triage.probability * 100) + "%. It orders the queue; it does not decide."));
        result.appendChild(t);
      }

      /* Two questions, answered separately. Within each, FAIL first, then
         FLAG, then PASS: an agent triages exceptions. */
      var order = { fail: 0, flag: 1, pass: 2 };
      LAYERS.forEach(function (layer) {
        var rows = data.checks.filter(function (c) { return (c.layer || "application") === layer[0]; });
        if (!rows.length) return;
        result.appendChild(el("h3", "layer-heading", layer[1]));
        var list = el("ul", "checks");
        rows.sort(function (a, b) {
          if (order[a.verdict] !== order[b.verdict]) {
            return order[a.verdict] - order[b.verdict];
          }
          return FIELD_ORDER.indexOf(a.field) - FIELD_ORDER.indexOf(b.field);
        }).forEach(function (c) { list.appendChild(renderCheck(c)); });
        result.appendChild(list);
      });

      if (data.preview) {
        artworkImg.hidden = false;
        artworkImg.src = data.preview;
      }
      drawBoxes(data.boxes, data.checks);

      if (data.notes && data.notes.length) {
        var notes = el("div", "notes");
        notes.appendChild(el("strong", null, "Image quality notes"));
        var ul = el("ul");
        data.notes.forEach(function (n) { ul.appendChild(el("li", null, n)); });
        notes.appendChild(ul);
        result.appendChild(notes);
      }

      printButton.hidden = false;

      var failed = data.checks.filter(function (c) { return c.verdict === "fail"; }).length;
      var review = data.checks.filter(function (c) { return c.verdict === "flag"; }).length;
      var said = "Result for " + data.cola_id + ": " + VERDICT_TEXT[data.verdict] + "."
                 + (failed ? " " + plural(failed, "check") + " failed." : "")
                 + (review ? " " + plural(review, "check") + (review === 1 ? " needs" : " need")
                             + " review." : "");
      announce(said);
      return said;
    }

    printButton.addEventListener("click", function () { window.print(); });

    /* --- requests -------------------------------------------------------- */

    /* Two steps for one label. The OCR result arrives in about a second and
       is shown at once. If some of it could not be read and a second reading is
       switched on, the page asks for the same label again with the reading
       included, and redraws when it lands, a few seconds later. OCR is cached
       on the server, so the second request costs only the model call. A newer
       check always wins: a late answer for a label no longer on screen is
       dropped. */
    var generation = 0;

    async function send(url, options) {
      var mine = ++generation;
      setBusy(true);
      renderChecking();
      try {
        var response = await fetch(url + "?second_opinion=defer", options);
        var payload = await response.json().catch(function () { return {}; });
        if (mine !== generation) return;
        if (!response.ok) {
          renderError(payload.detail || "The server returned an unexpected error.");
          return;
        }
        var said = renderResult(payload);
        /* On a narrow screen the result sits below the form, out of sight. */
        if (window.matchMedia && window.matchMedia("(max-width: 63.99em)").matches) {
          document.getElementById("result-heading").scrollIntoView({ behavior: "smooth", block: "start" });
        }
        if (payload.second_opinion && payload.second_opinion.pending) {
          secondReading(url, options, mine, payload.second_opinion.model, payload.elapsed_ms, said);
        }
      } catch (err) {
        if (mine === generation) {
          renderError("The server could not be reached. Check your connection and try again.");
        }
      } finally {
        if (mine === generation) setBusy(false);
      }
    }

    /* `said` is the OCR result's sentence. The second reading's own sentence
       would replace it before a screen reader spoke it, so the two go as one. */
    async function secondReading(url, options, mine, model, ocrMs, said) {
      var line = el("p", "pending-line");
      line.appendChild(el("span", "spinner"));
      line.appendChild(document.createTextNode(
        " Checking the parts OCR could not read with a second reading (" + model + ")…"));
      result.insertBefore(line, result.children[1] || null);
      announce(said + " A second reading of the parts OCR could not read is in progress.");
      try {
        var response = await fetch(url + "?second_opinion=inline", options);
        var payload = await response.json().catch(function () { return {}; });
        if (mine !== generation) return;
        if (!response.ok) {
          line.textContent = "The second reading could not be completed, so the referral stands.";
          announce(said + " " + line.textContent);
          return;
        }
        renderResult(payload, ocrMs);
      } catch (err) {
        if (mine === generation) {
          line.textContent = "The second reading could not be reached, so the referral stands.";
          announce(said + " " + line.textContent);
        }
      }
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (fileInput.files.length) {
        /* The artwork panel must show what is being checked. */
        showArtworkFile(fileInput.files[0]);
        send("/api/review", { method: "POST", body: new FormData(form) });
      } else if (currentSample) {
        var body = new FormData(form);
        body.delete("image");
        send("/api/review/example/" + currentSample, { method: "POST", body: body });
      } else if (refusedFile(fileInput)) {
        renderError("That file type is not accepted. Choose a JPEG, PNG, WEBP or TIFF image "
                    + "of the label. A PDF can be saved as an image first.");
      } else {
        renderError("Choose a label image before checking.");
      }
    });

    Array.prototype.forEach.call(
      document.querySelectorAll("[data-example]"),
      function (btn) {
        btn.addEventListener("click", function () {
          var id = btn.getAttribute("data-example");
          currentSample = id;
          clearFileInput();
          fillForm(JSON.parse(btn.getAttribute("data-record")));
          showArtwork("/examples/" + id + "/image", "Sample: " + btn.textContent.trim());
          send("/api/review/example/" + id, { method: "POST" });
        });
      }
    );
  }

  /* --- batch review ------------------------------------------------------
     Client-orchestrated fan-out over the single-label endpoint. Each label is an
     independent request, so there is no server-side job state to build, store or
     expire -- which for a prototype that keeps nothing is the right trade. The
     cost is that a page refresh loses progress; that is stated in the README.

     The browser holds one half of the concurrency limit and the server holds
     the other: the page reads MAX_BATCH_CONCURRENCY from the server so the two
     agree, and the server's semaphore caps the total across every open tab.
     Server-side the work runs on a thread pool, so these requests genuinely run
     in parallel. */

  function initBatch() {
    var modeSingle = document.getElementById("mode-single");
    var modeBatch = document.getElementById("mode-batch");
    var panelSingle = document.getElementById("panel-single");
    var panelBatch = document.getElementById("panel-batch");
    var recordsInput = document.getElementById("batch-records");
    var imagesInput = document.getElementById("batch-images");
    var runButton = document.getElementById("batch-run");
    var sampleButton = document.getElementById("batch-sample");
    var statusBox = document.getElementById("batch-status");
    var resultsBox = document.getElementById("batch-results");

    if (!modeBatch) return;

    var CONCURRENCY = parseInt(runButton.getAttribute("data-concurrency"), 10) || 4;
    var MAX_LABELS = parseInt(runButton.getAttribute("data-max-labels"), 10) || 500;
    /* A 429 says "wait", not "fail": the page waits the time the server asks
       for, up to this many times per label. */
    var MAX_WAITS = 30;

    function setMode(batch) {
      modeBatch.classList.toggle("usa-button--outline", !batch);
      modeSingle.classList.toggle("usa-button--outline", batch);
      modeBatch.setAttribute("aria-pressed", String(batch));
      modeSingle.setAttribute("aria-pressed", String(!batch));
      panelBatch.hidden = !batch;
      panelSingle.hidden = batch;
    }
    modeSingle.addEventListener("click", function () { setMode(false); });
    modeBatch.addEventListener("click", function () { setMode(true); });

    /* A USWDS slim alert. */
    function slimAlert(kind, text) {
      var box = el("div", "usa-alert usa-alert--slim usa-alert--" + kind + " margin-top-3");
      var body = el("div", "usa-alert__body");
      var p = el("p", "usa-alert__text");
      if (typeof text === "string") p.textContent = text; else p.appendChild(text);
      body.appendChild(p);
      box.appendChild(body);
      return box;
    }

    function note(message, kind) {
      statusBox.innerHTML = "";
      var box = slimAlert(kind === "error" ? "error" : "info", message);
      box.setAttribute("role", kind === "error" ? "alert" : "status");
      statusBox.appendChild(box);
    }

    function setRunning(running) {
      runButton.disabled = running;
      if (sampleButton) sampleButton.disabled = running;
    }

    /* Match an image to a record: first by the file name the records declare,
       then by looking for the COLA ID in the file name. Longest ID first, so
       "24-0010" is not claimed by "24-001". */
    function matchImages(records, declared, files) {
      var ids = records.map(function (r) { return r.cola_id; })
                       .sort(function (a, b) { return b.length - a.length; });
      var byId = {};
      var unmatched = [];

      Array.prototype.forEach.call(files, function (file) {
        var name = file.name.toLowerCase();
        for (var id in declared) {
          if (declared[id] && declared[id].toLowerCase() === name) {
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

      return postWithRetry(body, 0)
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

    /* A public deployment rate-limits each address. A batch that outruns the
       limit waits the time the server asks for and carries on, rather than
       marking labels "not checked". */
    function postWithRetry(body, attempt) {
      return fetch("/api/review", { method: "POST", body: body }).then(function (response) {
        if (response.status !== 429 || attempt >= MAX_WAITS) return response;
        var wait = Math.min(parseInt(response.headers.get("Retry-After"), 10) || 5, 60);
        return new Promise(function (resolve) { setTimeout(resolve, wait * 1000); })
          .then(function () { return postWithRetry(body, attempt + 1); });
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

    var VERDICT_LABEL = { pass: "Pass", flag: "Review", fail: "Fail", error: "Not checked" };

    var FIELD_NAMES = {
      brand_name: "brand name", class_type: "class/type", alcohol_content: "alcohol content",
      alcohol_format: "alcohol wording", proof_consistency: "proof statement",
      net_contents: "net contents", bottler_name: "bottler", bottler_address: "bottler address",
      country_of_origin: "country of origin", government_warning: "government warning",
      warning_typography: "warning type"
    };

    function findingsOf(r) {
      if (r.error) return r.error;
      var bad = (r.checks || []).filter(function (c) { return c.verdict !== "pass"; });
      if (!bad.length) return "All checks passed";
      return bad.map(function (c) {
        return (FIELD_NAMES[c.field] || c.field) + (c.verdict === "fail" ? " (fail)" : " (review)");
      }).join(", ");
    }

    function renderResults(rows, elapsedMs) {
      resultsBox.innerHTML = "";

      var counts = { pass: 0, flag: 0, fail: 0, error: 0 };
      rows.forEach(function (r) { counts[r.verdict] = (counts[r.verdict] || 0) + 1; });

      var summary = el("div", "summary");
      [["fail", "does not meet requirements", "do not meet requirements"],
       ["flag", "needs review", "need review"], ["pass", "passes", "pass"],
       ["error", "could not be checked", "could not be checked"]].forEach(function (words) {
        var n = counts[words[0]];
        if (!n) return;
        summary.appendChild(el("span", "usa-tag usa-tag--big tag--" + words[0],
                               n + " " + (n === 1 ? words[1] : words[2])));
      });
      summary.appendChild(el("span", "usa-tag usa-tag--big tag--none",
        plural(rows.length, "label") + " in " + (elapsedMs / 1000).toFixed(1) + " s"));
      resultsBox.appendChild(summary);

      var exportBtn = el("button", "usa-button usa-button--outline", "Download results as CSV");
      exportBtn.type = "button";
      exportBtn.addEventListener("click", function () { downloadCsv(rows); });
      resultsBox.appendChild(exportBtn);

      var table = el("table", "usa-table usa-table--borderless usa-table--stacked results width-full");
      var HEADINGS = ["COLA ID", "Result", "Findings", "Likely cause"];
      var thead = el("thead");
      var hrow = el("tr");
      HEADINGS.forEach(function (h) {
        var th = el("th", null, h);
        th.setAttribute("scope", "col");
        hrow.appendChild(th);
      });
      thead.appendChild(hrow);
      table.appendChild(thead);

      /* Referrals sort by triage, most likely genuine first: that is the order an
         agent should work them in. */
      var order = { fail: 0, error: 1, flag: 2, pass: 3 };
      var tbody = el("tbody");
      rows.slice().sort(function (a, b) {
        if (order[a.verdict] !== order[b.verdict]) return order[a.verdict] - order[b.verdict];
        return triageP(b) - triageP(a);
      }).forEach(function (r) {
        var tr = el("tr", r.verdict === "fail" ? "is-fail" : (r.verdict === "flag" ? "is-flag" : ""));
        /* data-label gives each cell its heading when the table stacks on a
           narrow screen (usa-table--stacked). */
        function cell(cls, text, i) {
          var td = el("td", cls, text);
          td.setAttribute("data-label", HEADINGS[i]);
          return td;
        }
        var idCell = el("th", null, r.cola_id);
        idCell.setAttribute("scope", "row");
        idCell.setAttribute("data-label", HEADINGS[0]);
        tr.appendChild(idCell);
        tr.appendChild(cell("results__verdict results__verdict--" + r.verdict,
                            VERDICT_LABEL[r.verdict] || r.verdict, 1));
        tr.appendChild(cell(null, findingsOf(r), 2));
        var cause = cell("results__triage", null, 3);
        if (r.verdict === "flag" && r.triage) {
          cause.appendChild(el("span", "usa-tag tag--" + (r.triage.probability >= 0.6 ? "fail"
            : r.triage.probability <= 0.4 ? "pass" : "flag"),
            r.triage.probability >= 0.6 ? "The label" : r.triage.probability <= 0.4 ? "The image" : "Unclear"));
          cause.title = TRIAGE_TEXT(r.triage.probability) + " (" + r.triage.provider + ", "
            + Math.round(r.triage.probability * 100) + "%)";
        }
        tr.appendChild(cause);
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      resultsBox.appendChild(table);
    }

    function triageP(r) { return r.triage ? r.triage.probability : -1; }

    /* A spreadsheet runs a cell that starts with = + - or @ as a formula, and
       COLA IDs come from whoever wrote the records file. */
    function csvCell(v) {
      var text = String(v);
      if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
      return '"' + text.replace(/"/g, '""') + '"';
    }

    /* The same words as the page: an agent opening this in Excel reads
       "Review", never an internal "flag". */
    function downloadCsv(rows) {
      var head = ["COLA ID", "Result", "Findings", "Seconds", "Chance of a genuine defect",
                  "Triage by"];
      var lines = [head.map(csvCell).join(",")];
      rows.forEach(function (r) {
        var ms = typeof r.elapsed_ms === "number" ? (r.elapsed_ms / 1000).toFixed(1) : "";
        lines.push([r.cola_id, VERDICT_LABEL[r.verdict] || r.verdict, findingsOf(r), ms,
                    r.triage ? Math.round(r.triage.probability * 100) + "%" : "",
                    r.triage ? r.triage.provider : ""]
          .map(csvCell).join(","));
      });
      /* The byte-order mark makes Excel read the file as UTF-8. */
      var blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = "label-review-results.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }

    /* Shared by the upload path and the sample path: parsed records plus a list
       of File objects, in; a rendered table, out. */
    async function runBatch(parsed, files) {
      var matched = matchImages(parsed.records, parsed.images || {}, files);
      var work = parsed.records
        .filter(function (r) { return matched.byId[r.cola_id]; })
        .map(function (r) { return { record: r, file: matched.byId[r.cola_id] }; });

      var problems = [];
      if (parsed.errors && parsed.errors.length) problems = problems.concat(parsed.errors);
      var missing = parsed.records.length - work.length;
      if (missing > 0) problems.push(plural(missing, "record") + " had no matching image file.");
      if (matched.unmatched.length) {
        /* An image can be unmatched because its row had an error above, or
           because its name carries no COLA ID. */
        problems.push(plural(matched.unmatched.length, "image") +
          " had no usable record: " + matched.unmatched.slice(0, 5).join(", ") +
          (matched.unmatched.length > 5 ? "…" : "") + ".");
      }

      if (work.length > MAX_LABELS) {
        note("That is " + plural(work.length, "label") + ". The limit is " + MAX_LABELS
             + " per batch; split the records file and run it in parts.", "error");
        return;
      }

      if (!work.length) {
        note("No images could be matched to a record. Image file names need to contain "
             + "the COLA ID, or the records file needs an image column.", "error");
        return;
      }

      statusBox.innerHTML = "";
      var progressWrap = el("div", "progress");
      var bar = el("div", "progress__bar");
      progressWrap.appendChild(bar);
      var label = el("p", "progress__label", "Checking 0 of " + work.length + "…");
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

      label.textContent = "Finished " + plural(work.length, "label") + " in "
                          + (elapsed / 1000).toFixed(1) + " s.";
      if (problems.length) {
        var text = document.createDocumentFragment();
        text.appendChild(el("strong", null, "Some items were skipped. "));
        text.appendChild(document.createTextNode(problems.join(" ")));
        var warn = slimAlert("warning", text);
        warn.setAttribute("role", "status");
        statusBox.appendChild(warn);
      }

      renderResults(rows, elapsed);
    }

    runButton.addEventListener("click", async function () {
      resultsBox.innerHTML = "";
      if (!recordsInput.files.length) {
        note(refusedFile(recordsInput)
          ? "That records file type is not accepted. From Excel, use File, Save As, and "
            + "choose CSV; or upload a JSON file."
          : "Choose a records file first.", "error");
        return;
      }
      if (!imagesInput.files.length) {
        note(refusedFile(imagesInput)
          ? "One of those files is not an accepted image. Choose JPEG, PNG, WEBP or TIFF "
            + "images of the labels."
          : "Choose the label images to check.", "error");
        return;
      }

      setRunning(true);
      note("Reading application records…");

      var body = new FormData();
      body.append("records", recordsInput.files[0]);

      try {
        var response = await fetch("/api/batch/records", { method: "POST", body: body });
        var parsed = await response.json();
        if (!response.ok) {
          note(parsed.detail || "Could not read that records file.", "error");
          return;
        }
        await runBatch(parsed, imagesInput.files);
      } catch (err) {
        note("Could not reach the server.", "error");
      } finally {
        setRunning(false);
      }
    });

    if (sampleButton) {
      sampleButton.addEventListener("click", async function () {
        resultsBox.innerHTML = "";
        setRunning(true);
        note("Loading the sample batch…");
        try {
          var response = await fetch("/examples/batch");
          var parsed = await response.json();
          if (!response.ok) {
            note(parsed.detail || "The sample batch is not available.", "error");
            return;
          }
          /* Fetch each fixture image and wrap it as a File, so the sample runs
             through exactly the same path as an agent's own upload. */
          var names = Object.keys(parsed.images).map(function (id) { return parsed.images[id]; });
          var files = await Promise.all(names.map(function (name) {
            return fetch("/examples/" + name.replace(/\.(png|jpg)$/i, "") + "/image")
              .then(function (r) { return r.blob(); })
              .then(function (blob) { return new File([blob], name, { type: blob.type }); });
          }));
          await runBatch(parsed, files);
        } catch (err) {
          note("Could not load the sample batch.", "error");
        } finally {
          setRunning(false);
        }
      });
    }
  }
})();
