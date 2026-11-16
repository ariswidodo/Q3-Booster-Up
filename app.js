(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

  let rawData = null;
  let lastRows = [];
  let lastMeta = null;
  let activeDetailCode = null;
  let hasLocalApi = false;

  const FIELDS = {
    unit_ink: [
      { key: "low_end", label: "Low End" },
      { key: "mid_high", label: "Mid High" },
      { key: "ink_bottle", label: "Ink Bottle" },
    ],
    consumables: [
      { key: "ink_664_003", label: "664/003" },
      { key: "cons_other", label: "Lainnya" },
    ],
  };

  function getSkuSets() {
    const r = rawData?.meta?.rule || {};
    return {
      ink: new Set((r.ink_bottle_skus || []).map((x) => x.toUpperCase())),
      oth: new Set((r.other_ink_skus || []).map((x) => x.toUpperCase())),
    };
  }

  function classify(it, skuSets) {
    const kat = it.kat || "";
    const eim = it.eim || "";
    const model = (it.model || "").toUpperCase();
    const desc = (it.desc || "").toUpperCase();
    const qty = it.qty || 0;
    if (kat === "Consumables") {
      const is664 = skuSets.ink.has(model);
      const isOth = skuSets.oth.has(model);
      return {
        ink_664_003: is664 ? qty : 0,
        cons_other: isOth ? qty : 0,
        ink_bottle: is664 || isOth ? qty : 0,
        low_end: 0,
        mid_high: 0,
      };
    }
    if (kat === "Consumer") {
      const isMid = eim === "Mid High";
      const isMaint = desc.includes("MAINTENANCE BOX");
      return {
        ink_664_003: 0,
        cons_other: 0,
        ink_bottle: 0,
        mid_high: isMid ? qty : 0,
        low_end: !isMid && !isMaint ? qty : 0,
      };
    }
    return { ink_664_003: 0, cons_other: 0, ink_bottle: 0, low_end: 0, mid_high: 0 };
  }

  function evaluatePkg(bucket, schemeKey, pkgKey, schemes) {
    const pkg = schemes?.[schemeKey]?.packages?.[pkgKey];
    const fields = FIELDS[schemeKey] || [];
    if (!pkg) return null;
    const lines = fields.map((f) => {
      const target = pkg.targets?.[f.key] || 0;
      const actual = bucket?.[f.key] || 0;
      return { label: f.label, actual, target, gap: Math.max(0, target - actual) };
    });
    const totalGap = lines.reduce((s, l) => s + l.gap, 0);
    return {
      reward: pkg.reward || 0,
      totalTarget: pkg.total_qty || lines.reduce((s, l) => s + l.target, 0),
      lines,
      totalGap,
      achieved: totalGap === 0,
    };
  }

  function renderSchemes() {
    const rule = rawData?.meta?.rule || {};
    const schemes = rule.schemes || {};
    const parts = rawData?.participants || [];
    const notes = { SUN: "Sun", STAR: "Star, Earth, Moon", MOON: "Moon, Crescent" };
    const mkRows = (sk, keys) => {
      const pkgs = schemes[sk]?.packages || {};
      return ["SUN", "STAR", "MOON"]
        .filter((k) => pkgs[k])
        .map((k) => {
          const p = pkgs[k];
          const cnt = parts.filter((x) => x.scheme === sk && x.pkg === k).length;
          return `<tr>
            <td><b>${k}</b> <span style="color:var(--text-3)">(${notes[k]})</span></td>
            ${keys.map((fk) => `<td class="num mono">${(p.targets?.[fk] || 0).toLocaleString("id-ID")}</td>`).join("")}
            <td class="num mono"><b>${(p.total_qty || 0).toLocaleString("id-ID")}</b></td>
            <td class="num mono">Rp ${(p.reward || 0).toLocaleString("id-ID")}</td>
            <td class="num mono">${cnt} EPR</td>
          </tr>`;
        })
        .join("");
    };
    const uiCnt = parts.filter((x) => x.scheme === "unit_ink").length;
    const coCnt = parts.filter((x) => x.scheme === "consumables").length;
    $("schemeInfo").innerHTML = `<div class="prog-scheme-grid">
      <div class="prog-scheme-card">
        <h4><span>${esc(schemes.unit_ink?.label || "Consumer")}</span><span class="badge badge-blue">${uiCnt} EPR</span></h4>
        <table class="prog-scheme-table">
          <thead><tr><th>Paket</th><th class="num">Low End</th><th class="num">Mid High</th><th class="num">Ink Bottle</th><th class="num">Total</th><th class="num">Hadiah</th><th class="num">Peserta</th></tr></thead>
          <tbody>${mkRows("unit_ink", ["low_end", "mid_high", "ink_bottle"])}</tbody>
        </table>
      </div>
      <div class="prog-scheme-card">
        <h4><span>${esc(schemes.consumables?.label || "Consumables")}</span><span class="badge badge-blue">${coCnt} EPR</span></h4>
        <table class="prog-scheme-table">
          <thead><tr><th>Paket</th><th class="num">664/003</th><th class="num">Lainnya</th><th class="num">Total</th><th class="num">Hadiah</th><th class="num">Peserta</th></tr></thead>
          <tbody>${mkRows("consumables", ["ink_664_003", "cons_other"])}</tbody>
        </table>
      </div>
    </div>`;
  }

  function populateSlicers() {
    const parts = rawData?.participants || [];
    const curAe = $("aeFilter").value || "ALL";
    const aes = [...new Set(parts.map((p) => p.ae || "ARIS"))].sort();
    $("aeFilter").innerHTML =
      `<option value="ALL">Semua AE/AM (${parts.length})</option>` +
      aes.map((a) => `<option value="${esc(a)}">${esc(a)} (${parts.filter((p) => (p.ae || "ARIS") === a).length})</option>`).join("");
    $("aeFilter").value = aes.includes(curAe) ? curAe : "ALL";

    const packSel = $("packFilter");
    packSel.options[0].textContent = `Semua Paket (${parts.length} EPR)`;
    packSel.options[1].textContent = `Paket Consumer (${parts.filter((p) => p.scheme === "unit_ink").length} EPR)`;
    packSel.options[2].textContent = `Paket Consumables (${parts.filter((p) => p.scheme === "consumables").length} EPR)`;
  }

  function render() {
    if (!rawData) return;
    const rule = rawData.meta?.rule || {};
    const dStart = $("progStart").value || rule.start || "2026-10-01";
    const dEnd = $("progEnd").value || rule.end || "2026-12-31";
    const aeVal = $("aeFilter").value || "ALL";
    const packVal = $("packFilter").value || "ALL";
    const statusVal = $("statusFilter").value || "ALL";
    const q = ($("searchInput").value || "").trim().toLowerCase();
    const skuSets = getSkuSets();

    const byEpr = new Map();
    (rawData.items || []).forEach((it) => {
      if (dStart && it.date < dStart) return;
      if (dEnd && it.date > dEnd) return;
      if (!byEpr.has(it.epr)) {
        byEpr.set(it.epr, {
          net: 0,
          models: new Map(),
          bucket: { ink_664_003: 0, cons_other: 0, ink_bottle: 0, low_end: 0, mid_high: 0 },
        });
      }
      const eo = byEpr.get(it.epr);
      eo.net += it.net || 0;
      const bk = classify(it, skuSets);
      Object.keys(eo.bucket).forEach((k) => (eo.bucket[k] += bk[k]));
      const mKey = it.desc ? `${it.model} (${it.desc})` : it.model;
      eo.models.set(mKey, (eo.models.get(mKey) || 0) + (it.qty || 0));
    });

    const filteredParts = (rawData.participants || []).filter((p) => {
      if (aeVal !== "ALL" && p.ae !== aeVal) return false;
      if (packVal !== "ALL" && p.scheme !== packVal) return false;
      if (q && !`${p.name} ${p.code} ${p.city} ${p.ae}`.toLowerCase().includes(q)) return false;
      return true;
    });

    const allRows = filteredParts.map((p) => {
      const hit = byEpr.get(p.code);
      const bucket = hit ? hit.bucket : { ink_664_003: 0, cons_other: 0, ink_bottle: 0, low_end: 0, mid_high: 0 };
      const qty =
        p.scheme === "consumables"
          ? bucket.ink_664_003 + bucket.cons_other
          : bucket.ink_bottle + bucket.low_end + bucket.mid_high;
      const ev = evaluatePkg(bucket, p.scheme, p.pkg, rule.schemes);
      const models = hit ? [...hit.models.entries()].sort((a, b) => b[1] - a[1]) : [];
      return { p, net: hit?.net || 0, bucket, qty, ev, models, joined: qty > 0 };
    });

    const rows = allRows
      .filter((r) => {
        if (statusVal === "joined") return r.joined;
        if (statusVal === "missing") return !r.joined;
        if (statusVal === "achieved") return !!r.ev?.achieved;
        return true;
      })
      .sort((a, b) => b.qty - a.qty || b.net - a.net || a.p.name.localeCompare(b.p.name));

    const unitTot = { ink_bottle: 0, low_end: 0, mid_high: 0 };
    const consTot = { ink_664_003: 0, cons_other: 0 };
    rows.forEach((r) => {
      if (r.p.scheme === "consumables") {
        consTot.ink_664_003 += r.bucket.ink_664_003;
        consTot.cons_other += r.bucket.cons_other;
      } else {
        unitTot.ink_bottle += r.bucket.ink_bottle;
        unitTot.low_end += r.bucket.low_end;
        unitTot.mid_high += r.bucket.mid_high;
      }
    });

    const joinedCnt = rows.filter((r) => r.joined).length;
    const achRows = rows.filter((r) => r.ev?.achieved);
    const rewardTot = achRows.reduce((s, r) => s + (r.ev?.reward || 0), 0);

    $("kpiPeserta").textContent = `${joinedCnt} / ${rows.length}`;
    $("kpiPesertaSub").textContent = `${rows.length - joinedCnt} EPR belum beli pada periode`;
    $("kpiAchieved").textContent = `${achRows.length} EPR`;
    $("kpiAchievedSub").textContent = `Total Hadiah: Rp ${rewardTot.toLocaleString("id-ID")}`;
    $("kpiConsumer").textContent = `${unitTot.ink_bottle.toLocaleString("id-ID")} pcs`;
    $("kpiConsumerSub").textContent = `Low End: ${unitTot.low_end.toLocaleString("id-ID")} · Mid High: ${unitTot.mid_high.toLocaleString("id-ID")} Unit`;
    $("kpiConsumables").textContent = `${consTot.ink_664_003.toLocaleString("id-ID")} pcs`;
    $("kpiConsumablesSub").textContent = `664/003 · Lainnya: ${consTot.cons_other.toLocaleString("id-ID")} pcs`;
    $("tableCount").textContent = `${rows.length} EPR`;

    const chips = [
      ["Consumer · Ink Bottle", `${unitTot.ink_bottle.toLocaleString("id-ID")} pcs`],
      ["Consumer · Low End", `${unitTot.low_end.toLocaleString("id-ID")} Unit`],
      ["Consumer · Mid High", `${unitTot.mid_high.toLocaleString("id-ID")} Unit`],
      ["Consumables · 664/003", `${consTot.ink_664_003.toLocaleString("id-ID")} pcs`],
      ["Consumables · Lainnya", `${consTot.cons_other.toLocaleString("id-ID")} pcs`],
    ];
    $("summaryChips").innerHTML = chips
      .map(([l, v]) => `<span class="model-chip"><span>${l}:</span><strong class="mono">${v}</strong></span>`)
      .join("");

    lastRows = rows;
    lastMeta = { dStart, dEnd, unitTot, consTot };

    $("resultBody").innerHTML = rows.length
      ? rows
          .map((r, i) => {
            const sumHtml = !r.joined
              ? '<span class="badge badge-neutral">Belum Beli</span>'
              : r.p.scheme === "consumables"
              ? `<div class="model-list-cell"><span class="badge badge-neutral mono">664/003: ${r.bucket.ink_664_003.toLocaleString("id-ID")} pcs</span><span class="badge badge-neutral mono">Lainnya: ${r.bucket.cons_other.toLocaleString("id-ID")} pcs</span></div>`
              : `<div class="model-list-cell"><span class="badge badge-neutral mono">Ink Bottle: ${r.bucket.ink_bottle.toLocaleString("id-ID")} pcs</span><span class="badge badge-neutral mono">Low End: ${r.bucket.low_end.toLocaleString("id-ID")} Unit</span><span class="badge badge-neutral mono">Mid High: ${r.bucket.mid_high.toLocaleString("id-ID")} Unit</span></div>`;

            const tgtHtml = `<div class="booster-lines mono">${r.ev.lines
              .map((l) => `<div class="booster-line"><span>${esc(l.label)}</span><span><b>${l.actual.toLocaleString("id-ID")}</b> / ${l.target.toLocaleString("id-ID")}</span></div>`)
              .join("")}</div>`;

            const gapHtml = r.ev.achieved
              ? `<span class="badge badge-emerald">Achieved · Hadiah Rp ${r.ev.reward.toLocaleString("id-ID")}</span>`
              : `<div class="booster-lines mono">${r.ev.lines
                  .map((l) =>
                    l.gap === 0
                      ? `<div class="booster-line"><span>${esc(l.label)}</span><span class="booster-ok">&#10003; Tercapai</span></div>`
                      : `<div class="booster-line"><span>${esc(l.label)}</span><span class="booster-warn">Kurang ${l.gap.toLocaleString("id-ID")}</span></div>`
                  )
                  .join("")}</div>`;

            return `<tr data-code="${esc(r.p.code)}">
              <td class="mono">${i + 1}</td>
              <td>
                <div class="partner-cell">
                  <span class="partner-name">${esc(r.p.name)}</span>
                  <span class="partner-meta mono">${esc(r.p.code)} · ${esc(r.p.city || "-")} · AE: ${esc(r.p.ae)}</span>
                </div>
              </td>
              <td>
                <div style="display:flex;flex-direction:column;gap:4px">
                  <span class="badge badge-blue" style="width:fit-content">${esc(r.p.pack_name)}</span>
                  <button type="button" class="btn" data-pdf="${esc(r.p.code)}" style="height:22px;padding:0 7px;font-size:10.5px;width:fit-content">PDF</button>
                </div>
              </td>
              <td>${sumHtml}</td>
              <td class="num mono"><strong>${r.qty.toLocaleString("id-ID")}</strong></td>
              <td class="num">${tgtHtml}</td>
              <td class="num">${gapHtml}</td>
            </tr>`;
          })
          .join("")
      : '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-3)">Tidak ada EPR pada filter ini.</td></tr>';

    $("resultBody").querySelectorAll("[data-pdf]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        sharePdf(btn.dataset.pdf);
      });
    });
    $("resultBody").querySelectorAll("tr[data-code]").forEach((tr) => {
      tr.addEventListener("click", () => openDetail(tr.dataset.code));
    });
  }

  function openDetail(code) {
    const r = lastRows.find((x) => x.p.code === code);
    if (!r) return;
    activeDetailCode = code;
    const unitLbl = r.p.scheme === "consumables" ? "pcs" : "unit/pcs";
    $("pmCode").textContent = r.p.code;
    $("pmPack").textContent = r.p.pack_name;
    $("pmName").textContent = r.p.name;
    $("pmMeta").textContent = `${r.p.city || "-"} · AE: ${r.p.ae} · Periode ${lastMeta.dStart} s/d ${lastMeta.dEnd}`;

    const rowsHtml = r.ev.lines
      .map((l) => {
        const pct = l.target > 0 ? Math.min(100, (l.actual / l.target) * 100) : 100;
        const pctReal = l.target > 0 ? ((l.actual / l.target) * 100).toFixed(1) : "100.0";
        const color = l.gap === 0 ? "#10b981" : pct >= 50 ? "#f59e0b" : "#ef4444";
        const gapHtml =
          l.gap === 0
            ? `<span class="booster-ok">&#10003; Tercapai</span>`
            : `<span class="booster-warn">Kurang ${l.gap.toLocaleString("id-ID")}</span>`;
        return `<tr>
          <td><b>${esc(l.label)}</b></td>
          <td class="num mono">${l.target.toLocaleString("id-ID")}</td>
          <td class="num mono"><b>${l.actual.toLocaleString("id-ID")}</b></td>
          <td class="num mono">${gapHtml}</td>
          <td class="num"><div class="ach-cell"><div class="mini-bar"><span style="width:${pct.toFixed(1)}%;background:${color}"></span></div><span class="mono">${pctReal}%</span></div></td>
        </tr>`;
      })
      .join("");

    const skuHtml = r.models.length
      ? r.models.map(([m, q]) => `<tr><td>${esc(m)}</td><td class="num mono"><b>${q.toLocaleString("id-ID")}</b></td></tr>`).join("")
      : '<tr><td colspan="2" style="text-align:center;color:var(--text-3)">Belum ada transaksi pada periode ini.</td></tr>';

    $("pmBody").innerHTML = `
      <div class="pm-kpis">
        <div class="pm-kpi"><span>Sudah Beli</span><strong class="mono">${r.qty.toLocaleString("id-ID")} ${unitLbl}</strong><small>Disti PIN - 4 EPP Local</small></div>
        <div class="pm-kpi"><span>Target Paket</span><strong class="mono">${r.ev.totalTarget.toLocaleString("id-ID")} ${unitLbl}</strong><small>Hadiah: Rp ${r.ev.reward.toLocaleString("id-ID")}</small></div>
        <div class="pm-kpi"><span>Status / Kekurangan</span><strong class="mono">${r.ev.achieved ? "Achieved!" : `Kurang ${r.ev.totalGap.toLocaleString("id-ID")}`}</strong><small>${r.ev.achieved ? "Siap klaim hadiah" : "Perlu tambahan pembelian"}</small></div>
      </div>
      <table class="pm-table">
        <thead><tr><th>Tipe Produk</th><th class="num">Target</th><th class="num">Sudah Beli</th><th class="num">Kurang</th><th class="num">Progress</th></tr></thead>
        <tbody>${rowsHtml}</tbody>
        <tfoot><tr><td>Total Paket</td><td class="num mono">${r.ev.totalTarget.toLocaleString("id-ID")}</td><td class="num mono">${r.qty.toLocaleString("id-ID")}</td><td class="num mono">${r.ev.achieved ? "Tercapai" : `Kurang ${r.ev.totalGap.toLocaleString("id-ID")}`}</td><td class="num mono">${r.ev.totalTarget > 0 ? ((r.qty / r.ev.totalTarget) * 100).toFixed(1) : "0.0"}%</td></tr></tfoot>
      </table>
      <div class="table-scroll" style="max-height:200px;overflow:auto">
        <table class="pm-table">
          <thead><tr><th>SKU / Model yang Dibeli (${r.models.length})</th><th class="num">Qty</th></tr></thead>
          <tbody>${skuHtml}</tbody>
        </table>
      </div>`;
    $("detailBackdrop").hidden = false;
    $("detailModal").hidden = false;
  }

  function closeDetail() {
    activeDetailCode = null;
    $("detailBackdrop").hidden = true;
    $("detailModal").hidden = true;
  }

  function sharePdf(singleCode = null) {
    const printRows = singleCode ? lastRows.filter((r) => r.p.code === singleCode) : lastRows;
    if (!printRows.length) return;
    const single = singleCode ? printRows[0] : null;
    const aeSel = $("aeFilter")?.value || "ALL";
    const aeLabel = single ? single.p.ae : aeSel !== "ALL" ? aeSel : null;
    const title = single
      ? `Result Q3 Booster Up — ${single.p.name}`
      : aeLabel
      ? `Result Q3 Booster Up — AE/AM: ${aeLabel}`
      : "Result Q3 Booster Up — Semua Peserta";
    const periodTxt = `${lastMeta.dStart} s/d ${lastMeta.dEnd}`;
    const aeMetaTxt = aeLabel ? ` · AE/AM: ${aeLabel}` : "";

    const rowsHtml = printRows
      .map((r, i) => {
        const resTxt = !r.joined
          ? "Belum Beli"
          : r.p.scheme === "consumables"
          ? `664/003: <b>${r.bucket.ink_664_003.toLocaleString("id-ID")} pcs</b><br>Lainnya: <b>${r.bucket.cons_other.toLocaleString("id-ID")} pcs</b>`
          : `Ink Bottle: <b>${r.bucket.ink_bottle.toLocaleString("id-ID")} pcs</b><br>Low End: <b>${r.bucket.low_end.toLocaleString("id-ID")} Unit</b><br>Mid High: <b>${r.bucket.mid_high.toLocaleString("id-ID")} Unit</b>`;
        const tgtTxt = r.ev.lines.map((l) => `${esc(l.label)}: <b>${l.actual.toLocaleString("id-ID")}</b> / ${l.target.toLocaleString("id-ID")}`).join("<br>");
        const stHtml = r.ev.achieved
          ? `<span class="pdf-gap-ok">Achieved<br>Hadiah Rp ${r.ev.reward.toLocaleString("id-ID")}</span>`
          : r.ev.lines
              .map((l) => (l.gap === 0 ? `<span class="pdf-gap-ok">${esc(l.label)}: Tercapai</span>` : `<span class="pdf-gap-warn">${esc(l.label)}: Kurang ${l.gap.toLocaleString("id-ID")}</span>`))
              .join("<br>");
        return `<tr>
          <td class="mono">${i + 1}</td>
          <td><b>${esc(r.p.name)}</b><br><small class="mono">${esc(r.p.code)} · ${esc(r.p.city)} · AE: ${esc(r.p.ae)}</small></td>
          <td><b>${esc(r.p.pack_name)}</b></td>
          <td class="mono">${resTxt}</td>
          <td class="num mono"><b>${r.qty.toLocaleString("id-ID")}</b></td>
          <td class="mono">${tgtTxt}</td>
          <td class="mono">${stHtml}</td>
        </tr>`;
      })
      .join("");

    $("pdfReport").innerHTML = `
      <div class="pdf-head">
        <div><h1>${esc(title)}</h1><div class="pdf-meta">Periode: ${esc(periodTxt)}${esc(aeMetaTxt)} · Dihitung hanya Pembelian dari: Disti PIN - 4 EPP Local (Computek, Top Distribusi, Raka Perkasa &amp; Computa)</div></div>
        <div class="pdf-meta" style="text-align:right"><div><b>Q3 Booster Up${aeLabel ? " · " + esc(aeLabel) : ""}</b></div><div>Dicetak: ${new Date().toLocaleString("id-ID")}</div></div>
      </div>
      <div class="pdf-sec">
        <table class="pdf-table">
          <thead><tr><th>#</th><th>Nama EPR</th><th>Paket</th><th>Result Pembelian</th><th class="num">Total Qty</th><th>Target Paket</th><th>Kekurangan / Status</th></tr></thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
      <div class="pdf-foot"><span>Q3 Booster Up · 31 SKU Tinta Resmi</span><span>${printRows.length} EPR</span></div>`;

    const prev = document.title;
    document.title = single
      ? `Q3_Booster_${single.p.code}`
      : aeLabel
      ? `Q3_Booster_Up_${aeLabel}`
      : "Q3_Booster_Up_Result";
    window.print();
    setTimeout(() => (document.title = prev), 500);
  }

  function exportCsv() {
    const hdr = ["EPR Code", "EPR Name", "City", "AE", "Pack Name", "Total Qty", "Status", "Reward"];
    const rows = lastRows.map((r) => [
      r.p.code, r.p.name, r.p.city, r.p.ae, r.p.pack_name, r.qty,
      r.ev.achieved ? "Achieved" : `Kurang ${r.ev.totalGap}`,
      r.ev.achieved ? r.ev.reward : 0,
    ]);
    const csv = [hdr, ...rows].map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" }));
    a.download = "Q3_Booster_Up_Result.csv";
    a.click();
  }

  const EPR_RAW_BASE = "https://raw.githubusercontent.com/ariswidodo/EPR/main/data";

  function parseCsvRows(text) {
    const clean = text.replace(/^\uFEFF/, "");
    const lines = [];
    let row = [], cur = "", inQ = false;
    for (let i = 0; i < clean.length; i++) {
      const c = clean[i];
      if (c === '"') {
        if (inQ && clean[i + 1] === '"') { cur += '"'; i++; }
        else inQ = !inQ;
      } else if (c === "," && !inQ) {
        row.push(cur); cur = "";
      } else if ((c === "\n" || c === "\r") && !inQ) {
        if (c === "\r" && clean[i + 1] === "\n") i++;
        row.push(cur);
        if (row.some((x) => x !== "")) lines.push(row);
        row = []; cur = "";
      } else {
        cur += c;
      }
    }
    if (cur !== "" || row.length) { row.push(cur); lines.push(row); }
    if (!lines.length) return [];
    const hdr = lines[0].map((h) => h.trim());
    return lines.slice(1).map((r) => {
      const o = {};
      hdr.forEach((h, idx) => { o[h] = (r[idx] || "").trim(); });
      return o;
    });
  }

  async function loadFromEprRepo() {
    const ts = Date.now();
    const [eprRes, pesRes, skuRes] = await Promise.all([
      fetch(`${EPR_RAW_BASE}/epr_data.json?t=${ts}`, { cache: "no-store" }),
      fetch(`${EPR_RAW_BASE}/peserta_booster.csv?t=${ts}`, { cache: "no-store" }),
      fetch(`${EPR_RAW_BASE}/booster_consumables_sku.csv?t=${ts}`, { cache: "no-store" }),
    ]);
    if (!eprRes.ok || !pesRes.ok) throw new Error("Gagal mengambil data dari Repo EPR");
    const eprData = await eprRes.json();
    const pesertaRows = parseCsvRows(await pesRes.text());
    const skuRows = skuRes.ok ? parseCsvRows(await skuRes.text()) : [];

    const participants = [];
    const pMap = new Set();
    for (const r of pesertaRows) {
      const code = (r["EPR CODE"] || "").toUpperCase();
      const pack = r["PACK NAME"] || "";
      if (!code || !pack) continue;
      const scheme = pack.toUpperCase().includes("CONSUMABLES") ? "consumables" : "unit_ink";
      participants.push({
        code,
        name: r["EPR NAME"] || "",
        city: r["CITY"] || "",
        area: r["AREA"] || "JATENG",
        fy_cat: r["FY26 TARGET CATEGORY"] || "",
        pack_name: pack,
        pkg: pack.split(/\s+/)[0].toUpperCase(),
        scheme,
        ae: r["AE"] || "ARIS",
      });
      pMap.add(code);
    }

    const ink = new Set(), oth = new Set();
    for (const r of skuRows) {
      const mc = (r["Material Code"] || "").toUpperCase();
      const tp = (r["Type"] || "").toUpperCase();
      if (!mc) continue;
      if (tp === "INK BOTTLE") ink.add(mc);
      else if (tp === "OTHERS INK BOTTLE") oth.add(mc);
    }
    const eprMeta = eprData.meta || {};
    const rule = { ...((eprMeta.program_rules || {})["Q3 Booster Up"] || {}) };
    if (ink.size) rule.ink_bottle_skus = [...ink].sort();
    if (oth.size) rule.other_ink_skus = [...oth].sort();
    const allInk = new Set([...(rule.ink_bottle_skus || []), ...(rule.other_ink_skus || [])].map((x) => x.toUpperCase()));

    const itemMap = new Map();
    let txCount = 0;
    for (const x of eprData.program_items || []) {
      if (x.prog !== "Q3 Booster Up") continue;
      const ec = (x.epr || "").toUpperCase();
      if (!pMap.has(ec)) continue;
      const kat = (x.kat || "").trim();
      const model = (x.model || "").toUpperCase();
      if (kat === "Consumables" && !allInk.has(model)) continue;
      const pk = `${ec}|${x.date || ""}|${model}`;
      let cur = itemMap.get(pk);
      if (!cur) {
        cur = { epr: ec, date: x.date || "", model, desc: x.desc || "", kat, eim: x.eim || "", qty: 0, net: 0, tx: 0 };
        itemMap.set(pk, cur);
      }
      cur.qty += Math.round(x.qty || 0);
      cur.net = Math.round((cur.net + (x.net || 0)) * 100) / 100;
      cur.tx += x.tx || 1;
      txCount += x.tx || 1;
    }

    return {
      meta: {
        title: "Q3 Booster Up — Monitoring Paket",
        generated_at: `${eprMeta.generated_at || "-"} (Live Sync: Repo EPR)`,
        rule,
        verified_rows: txCount,
      },
      participants,
      items: [...itemMap.values()],
    };
  }

  async function reloadData() {
    let loaded = null;
    if (!hasLocalApi) {
      try {
        loaded = await loadFromEprRepo();
      } catch (_) {}
    }
    if (!loaded) {
      const res = await fetch(`./data/booster_data.json?t=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      loaded = await res.json();
    }
    rawData = loaded;
    const m = rawData.meta || {};
    $("progStart").value = m.rule?.start || "2026-10-01";
    $("progEnd").value = m.rule?.end || "2026-12-31";
    $("metaSubtitle").textContent = `${(rawData.participants || []).length} EPR peserta · Diperbarui ${m.generated_at || "-"}`;
    $("footerInfo").textContent = `${m.verified_rows || 0} transaksi Booster tersimpan`;
    populateSlicers();
    renderSchemes();
    render();
  }

  async function checkLocalServer() {
    try {
      const r = await fetch("/api/status", { cache: "no-store" });
      if (r.ok) {
        hasLocalApi = true;
        $("btnSavePeriod").hidden = false;
      }
    } catch (_) {}
  }

  function bindEvents() {
    ["aeFilter", "packFilter", "statusFilter", "progStart", "progEnd"].forEach((id) =>
      $(id).addEventListener("change", render)
    );
    $("searchInput").addEventListener("input", render);
    $("btnResetFilters").addEventListener("click", () => {
      $("aeFilter").value = "ALL";
      $("packFilter").value = "ALL";
      $("statusFilter").value = "ALL";
      $("searchInput").value = "";
      render();
    });
    $("btnShareAllPdf").addEventListener("click", () => sharePdf(null));
    $("btnExportCsv").addEventListener("click", exportCsv);
    $("btnCloseDetail").addEventListener("click", closeDetail);
    $("detailBackdrop").addEventListener("click", closeDetail);
    $("btnPmPdf").addEventListener("click", () => activeDetailCode && sharePdf(activeDetailCode));

    $("btnTheme").addEventListener("click", () => {
      const dark = document.documentElement.getAttribute("data-theme") === "dark";
      const next = dark ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      $("iconSun").style.display = next === "dark" ? "none" : "block";
      $("iconMoon").style.display = next === "dark" ? "block" : "none";
      localStorage.setItem("booster_theme", next);
    });
    if (localStorage.getItem("booster_theme") === "dark") {
      document.documentElement.setAttribute("data-theme", "dark");
      $("iconSun").style.display = "none";
      $("iconMoon").style.display = "block";
    }

    $("btnSavePeriod").addEventListener("click", async () => {
      if (!hasLocalApi) return;
      await fetch("/api/program-rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start: $("progStart").value, end: $("progEnd").value }),
      });
      await reloadData();
    });
  }

  (async () => {
    bindEvents();
    await checkLocalServer();
    await reloadData();
  })();
})();
