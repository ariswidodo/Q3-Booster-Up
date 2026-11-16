# -*- coding: utf-8 -*-
"""Standalone engine for Q3 Booster Up Dashboard.
Zero external dependencies (Python stdlib only).
"""
import csv
import datetime
import json
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

LOCAL_BOOSTER_EPPS = {"EPP-0050", "EPP-0055", "EPP-0056", "EPP-0245"}


def _col_idx(ref):
    m = re.match(r"([A-Z]+)", (ref or "").upper())
    if not m:
        return 0
    idx = 0
    for ch in m.group(1):
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _norm_name(s):
    return re.sub(r"[^A-Z0-9]+", " ", (s or "").upper()).strip()


def _is_local_epp(epp_code, epp_name):
    if (epp_code or "").strip().upper() in LOCAL_BOOSTER_EPPS:
        return True
    en = (epp_name or "").upper()
    return any(k in en for k in ("COMPUTEK", "RAKA PERKASA", "CV COMPUTA", "TOP DISTRIBUSI"))


def _read_xlsx_sheet_map(path):
    """Return {sheet_name: list_of_dense_rows} from an .xlsx/.xlsm file."""
    with zipfile.ZipFile(path) as z:
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        ss = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            ss = ["".join(si.itertext()) for si in root.findall("a:si", ns)]

        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid2target = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
        result = {}
        for sh in wb.findall(".//a:sheet", ns):
            name = sh.attrib.get("name", "Sheet1")
            rid = None
            for k, v in sh.attrib.items():
                if k.endswith("id"):
                    rid = v
                    break
            target = rid2target.get(rid, "")
            if not target:
                continue
            part = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
            if part not in z.namelist():
                continue
            ws = ET.fromstring(z.read(part))
            rows = []
            for row in ws.findall(".//a:row", ns):
                cells = {}
                max_col = -1
                for c in row.findall("a:c", ns):
                    ci = _col_idx(c.attrib.get("r", ""))
                    max_col = max(max_col, ci)
                    t = c.attrib.get("t")
                    v = c.find("a:v", ns)
                    is_el = c.find("a:is", ns)
                    if is_el is not None:
                        val = "".join(is_el.itertext())
                    elif v is None:
                        val = ""
                    elif t == "s":
                        val = ss[int(v.text)]
                    else:
                        val = v.text or ""
                    cells[ci] = str(val).strip()
                if max_col >= 0:
                    arr = [cells.get(i, "") for i in range(max_col + 1)]
                    if any(x != "" for x in arr):
                        rows.append(arr)
            result[name] = rows
        return result


def _parse_date(val):
    s = str(val or "").strip()
    if not s:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    try:
        n = float(s)
        if 35000 < n < 60000:
            dt = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(n))
            return dt.isoformat()
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d %b %Y"):
        try:
            return datetime.datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _ensure_db(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute(
        """CREATE TABLE IF NOT EXISTS booster_tx (
            kunci TEXT PRIMARY KEY,
            epr TEXT NOT NULL,
            epr_name TEXT,
            epp TEXT,
            epp_name TEXT,
            invoice_date TEXT NOT NULL,
            invoice_no TEXT,
            material TEXT NOT NULL,
            description TEXT,
            qty REAL NOT NULL,
            net REAL NOT NULL,
            kat TEXT,
            eim TEXT,
            remarks TEXT,
            sumber_file TEXT,
            diproses_pada TEXT
        )"""
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_booster_epr ON booster_tx(epr)")
    con.commit()
    return con


def load_masters(tool_dir):
    data_dir = os.path.join(tool_dir, "data")
    rules_path = os.path.join(data_dir, "program_rules.json")
    rules = {}
    if os.path.exists(rules_path):
        with open(rules_path, encoding="utf-8") as rf:
            rules = json.load(rf)
    q3 = rules.get("Q3 Booster Up") or {}

    participants = {}
    by_name = {}
    peserta_csv = os.path.join(data_dir, "peserta_booster.csv")
    if os.path.exists(peserta_csv):
        with open(peserta_csv, encoding="utf-8-sig") as pf:
            for r in csv.DictReader(pf):
                ec = (r.get("EPR CODE") or "").strip().upper()
                en = (r.get("EPR NAME") or "").strip()
                pack = (r.get("PACK NAME") or "").strip()
                if not ec or not pack:
                    continue
                scheme = "consumables" if "CONSUMABLES" in pack.upper() else "unit_ink"
                info = {
                    "code": ec,
                    "name": en,
                    "city": (r.get("CITY") or "").strip(),
                    "area": (r.get("AREA") or "JATENG").strip() or "JATENG",
                    "fy_cat": (r.get("FY26 TARGET CATEGORY") or "").strip(),
                    "pack_name": pack,
                    "pkg": pack.split()[0].upper(),
                    "scheme": scheme,
                    "ae": (r.get("AE") or "ARIS").strip() or "ARIS",
                }
                participants[ec] = info
                if en:
                    by_name[_norm_name(en)] = ec

    ink_set = set()
    oth_set = set()
    sku_csv = os.path.join(data_dir, "booster_consumables_sku.csv")
    if os.path.exists(sku_csv):
        with open(sku_csv, encoding="utf-8-sig") as sf:
            for sr in csv.DictReader(sf):
                mc = (sr.get("Material Code") or "").strip().upper()
                tp = (sr.get("Type") or "").strip().upper()
                if not mc:
                    continue
                if tp == "INK BOTTLE":
                    ink_set.add(mc)
                elif tp == "OTHERS INK BOTTLE":
                    oth_set.add(mc)

    epp_by_name = {}
    epp_csv = os.path.join(data_dir, "epp_master.csv")
    if os.path.exists(epp_csv):
        with open(epp_csv, encoding="utf-8-sig") as ef:
            for er in csv.DictReader(ef):
                ec = (er.get("EPP CODE") or "").strip().upper()
                for col in ("COMPANY NAME", "NAMA TOKO"):
                    nm = _norm_name(er.get(col) or "")
                    if ec and nm:
                        epp_by_name[nm] = ec

    eim_map = {}
    sku_xlsx = os.path.join(data_dir, "sku.xlsx")
    if os.path.exists(sku_xlsx):
        try:
            smap = _read_xlsx_sheet_map(sku_xlsx)
            first_rows = next(iter(smap.values()), [])
            if first_rows:
                hdr = [x.upper() for x in first_rows[0]]
                cm = next((i for i, h in enumerate(hdr) if "MODEL" in h or "MATERIAL" in h), 0)
                ce = next((i for i, h in enumerate(hdr) if "CAT" in h or "EIM" in h or "INDIVIDUAL" in h), None)
                for r in first_rows[1:]:
                    if cm < len(r) and r[cm]:
                        val = r[ce] if (ce is not None and ce < len(r)) else ""
                        eim_map[r[cm].strip().upper()] = val.strip()
        except Exception:
            pass

    return {
        "rules": rules,
        "q3_rule": q3,
        "participants": participants,
        "by_name": by_name,
        "ink_set": ink_set,
        "oth_set": oth_set,
        "all_ink": ink_set | oth_set,
        "epp_by_name": epp_by_name,
        "eim_map": eim_map,
    }


def _extract_ad_remarks(rem_text):
    parts = [x.strip() for x in (rem_text or "").split("|")]
    if len(parts) >= 4 and parts[-1].lower().startswith("src "):
        ad = " | ".join(parts[2:-1]).strip()
    else:
        ad = (rem_text or "").strip()
    return ad.strip().strip('"\'\u201c\u201d\u2018\u2019').strip()


def _map_kat(raw_kat, model, desc):
    k = (raw_kat or "").strip().lower()
    if "consumable" in k or "ink" in k or "ribbon" in k or model.startswith("C13"):
        return "Consumables"
    if "scanner" in k or model.startswith("B11"):
        return "Scanner"
    if "dotmatrix" in k or "sidm" in k:
        return "Dotmatrix"
    if "consumer" in k or "ciss" in k or "soho" in k or "bvi" in k or model.startswith("C11"):
        return "Consumer"
    if "MAINTENANCE" in (desc or "").upper():
        return "Consumer"
    return "Consumer" if model.startswith("C11") else "Consumables"


def seed_from_epr_db(epr_db_path, tool_dir):
    if not os.path.exists(epr_db_path):
        return 0
    m = load_masters(tool_dir)
    participants = m["participants"]
    by_name = m["by_name"]
    all_ink = m["all_ink"]

    src = sqlite3.connect(epr_db_path)
    src.row_factory = sqlite3.Row
    rows = src.execute(
        "SELECT kunci, epr, epr_name, epp, epp_name, invoice_date, invoice_no, material, description, qty, price, total, kat, eim, remarks, flag, sumber_file, diproses_pada "
        "FROM data_per_q "
        "WHERE invoice_date >= '2026-10-01' AND invoice_date <= '2026-12-31' "
        "AND LOWER(remarks) LIKE '%booster%' "
        "AND (is_verified = 1 OR keterangan = 'LUAR DATABASE EPR')"
    ).fetchall()
    src.close()

    dst_path = os.path.join(tool_dir, "data", "booster.db")
    con = _ensure_db(dst_path)
    inserted = 0
    for r in rows:
        ad = _extract_ad_remarks(r["remarks"])
        if not re.match(r"^q3\s+booster(\s+up)?$", ad, re.I):
            continue
        if not _is_local_epp(r["epp"], r["epp_name"]):
            continue
        ec = (r["epr"] or "").strip().upper()
        if ec not in participants:
            ec = by_name.get(_norm_name(r["epr_name"]), "")
        if not ec or ec not in participants:
            continue
        pinfo = participants[ec]
        kat = (r["kat"] or "").strip()
        mat = (r["material"] or "").strip().upper()
        if kat == "Consumables" and mat not in all_ink:
            continue
        if pinfo["scheme"] == "consumables" and kat != "Consumables":
            continue
        if pinfo["scheme"] == "unit_ink" and kat not in ("Consumer", "Consumables"):
            continue

        gross = r["total"] if (r["total"] is not None and r["total"] > 0) else ((r["price"] or 0.0) * (r["qty"] or 0.0))
        net = gross if (r["flag"] or "").strip() == "Valid (V3)" else (gross / 1.11)
        cur = con.execute(
            "INSERT OR IGNORE INTO booster_tx VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r["kunci"], ec, pinfo["name"], r["epp"], r["epp_name"],
                r["invoice_date"], r["invoice_no"], mat, r["description"],
                r["qty"] or 0.0, round(net, 2), kat, (r["eim"] or "").strip(),
                r["remarks"], r["sumber_file"], r["diproses_pada"],
            ),
        )
        inserted += cur.rowcount
    con.commit()
    con.close()
    export_booster_json(tool_dir)
    return inserted


def process_sellout_xlsx(xlsx_path, tool_dir, emit=None):
    def log(msg):
        if emit:
            emit(msg)

    m = load_masters(tool_dir)
    participants = m["participants"]
    by_name = m["by_name"]
    all_ink = m["all_ink"]
    epp_by_name = m["epp_by_name"]
    eim_map = m["eim_map"]
    q3 = m["q3_rule"]
    d_start = q3.get("start") or "2026-10-01"
    d_end = q3.get("end") or "2026-12-31"

    smap = _read_xlsx_sheet_map(xlsx_path)
    target_sheets = []
    if "Sheet1" in smap:
        target_sheets = [("Sheet1", "V1")]
    elif "Partner Hub" in smap:
        target_sheets = [("Partner Hub", "V2")]
    else:
        v3 = [n for n in smap if n.startswith("Report Retail Q")]
        if v3:
            target_sheets = [(n, "V3") for n in v3]
        elif smap:
            first_n = next(iter(smap))
            target_sheets = [(first_n, "V1")]

    if not target_sheets:
        raise ValueError("Sheet data tidak ditemukan di file Excel.")

    con = _ensure_db(os.path.join(tool_dir, "data", "booster.db"))
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fname = os.path.basename(xlsx_path)
    total_rows = 0
    matched_booster = 0
    inserted = 0
    skipped_dup = 0

    for sh_name, ver in target_sheets:
        rows = smap[sh_name]
        hdr_idx = None
        for i, r in enumerate(rows[:15]):
            vals = {x.strip() for x in r}
            if "Material Code" in vals and "Invoice Date" in vals:
                hdr_idx = i
                break
        if hdr_idx is None:
            continue

        hdr = rows[hdr_idx]
        idx_map = {h.strip().lower(): i for i, h in enumerate(hdr)}

        def _get(r, *cands):
            for c in cands:
                ci = idx_map.get(c.lower())
                if ci is not None and ci < len(r) and r[ci] != "":
                    return r[ci]
            return ""

        log(f"Membaca {fname} ({sh_name} · Format {ver})...")
        for rn_offset, r in enumerate(rows[hdr_idx + 1:], start=hdr_idx + 2):
            total_rows += 1
            ad = _get(r, "Remarks", "AD").strip().strip('"\'\u201c\u201d\u2018\u2019').strip()
            if not re.match(r"^q3\s+booster(\s+up)?$", ad, re.I):
                continue
            inv_date = _parse_date(_get(r, "Invoice Date"))
            if not inv_date or inv_date < d_start or inv_date > d_end:
                continue

            epp_code = _get(r, "T2 Partner code", "EPP Code").strip().upper()
            epp_name = _get(r, "Dealer Name", "EPP Name").strip()
            if not epp_code and epp_name:
                epp_code = epp_by_name.get(_norm_name(epp_name), "")
            if not _is_local_epp(epp_code, epp_name):
                continue

            epr_code = _get(r, "T3 Partner code", "EPR Code").strip().upper()
            epr_name = _get(r, "Reseller Name", "EPR Name").strip()
            if epr_code not in participants:
                epr_code = by_name.get(_norm_name(epr_name), "")
            if not epr_code or epr_code not in participants:
                continue

            pinfo = participants[epr_code]
            mat = _get(r, "Material Code").strip().upper()
            desc = _get(r, "Product", "Description").strip()
            raw_kat = _get(r, "Product Rebate", "Rebate product category", "Category")
            kat = _map_kat(raw_kat, mat, desc)
            if kat == "Consumables" and mat not in all_ink:
                continue
            if pinfo["scheme"] == "consumables" and kat != "Consumables":
                continue
            if pinfo["scheme"] == "unit_ink" and kat not in ("Consumer", "Consumables"):
                continue

            matched_booster += 1
            try:
                qty = float(_get(r, "Quantity", "Qty") or 0)
            except ValueError:
                qty = 0.0
            try:
                price = float(_get(r, "Actual Unit Price", "New Price (IDR)", "Reseller Price (IDR)") or 0)
            except ValueError:
                price = 0.0
            try:
                tot = float(_get(r, "Actual Total Amount", "Total Price") or 0)
            except ValueError:
                tot = 0.0
            gross = tot if tot > 0 else (qty * price)
            net = gross if ver == "V3" else (gross / 1.11)

            inv_no = _get(r, "Invoice No").strip()
            uid = _get(r, "UID").strip()
            kunci = uid or f"{epr_code}|{inv_no}|{inv_date}|{mat}|{int(qty)}|{rn_offset}"
            eim = eim_map.get(mat, "")
            cur = con.execute(
                "INSERT OR IGNORE INTO booster_tx VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    kunci, epr_code, pinfo["name"], epp_code, epp_name,
                    inv_date, inv_no, mat, desc, qty, round(net, 2),
                    kat, eim, ad, fname, now,
                ),
            )
            if cur.rowcount > 0:
                inserted += 1
            else:
                skipped_dup += 1

    con.commit()
    con.close()
    export_booster_json(tool_dir)
    log(f"Selesai: {total_rows} baris dibaca, {matched_booster} cocok Q3 Booster Up, +{inserted} baru ({skipped_dup} double dilewati).")
    return {"input": total_rows, "matched": matched_booster, "inserted": inserted, "doubles": skipped_dup}


def sync_participants(xlsx_path, tool_dir):
    smap = _read_xlsx_sheet_map(xlsx_path)
    rows = next(iter(smap.values()), [])
    hdr_idx = None
    for i, r in enumerate(rows[:10]):
        up = [x.upper() for x in r]
        if "EPR CODE" in up and "PACK NAME" in up:
            hdr_idx = i
            break
    if hdr_idx is None:
        raise ValueError("Header 'EPR CODE' dan 'PACK NAME' tidak ditemukan.")

    hdr = [x.upper() for x in rows[hdr_idx]]
    def _find(*names):
        for nm in names:
            if nm in hdr:
                return hdr.index(nm)
        return None

    c_code = _find("EPR CODE")
    c_name = _find("EPR NAME")
    c_area = _find("AREA")
    c_city = _find("CITY")
    c_cat = _find("FY26 TARGET CATOGORY", "FY26 TARGET CATEGORY", "CATEGORY")
    c_pack = _find("PACK NAME")
    c_ae = _find("AE", "AM")

    peserta_path = os.path.join(tool_dir, "data", "peserta_booster.csv")
    merged = {}
    order = []
    if os.path.exists(peserta_path):
        with open(peserta_path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                ec = (r.get("EPR CODE") or "").strip().upper()
                if ec:
                    merged[ec] = {
                        "EPR CODE": ec,
                        "EPR NAME": (r.get("EPR NAME") or "").strip(),
                        "AREA": (r.get("AREA") or "JATENG").strip() or "JATENG",
                        "CITY": (r.get("CITY") or "").strip(),
                        "FY26 TARGET CATEGORY": (r.get("FY26 TARGET CATEGORY") or "").strip(),
                        "PACK NAME": (r.get("PACK NAME") or "").strip(),
                        "AE": (r.get("AE") or "ARIS").strip() or "ARIS",
                    }
                    order.append(ec)

    upserted = 0
    for r in rows[hdr_idx + 1:]:
        ec = (r[c_code] if c_code is not None and c_code < len(r) else "").strip().upper()
        pack = (r[c_pack] if c_pack is not None and c_pack < len(r) else "").strip()
        if not ec or not pack:
            continue
        prev = merged.get(ec, {})
        ae_val = (r[c_ae] if c_ae is not None and c_ae < len(r) else "").strip()
        merged[ec] = {
            "EPR CODE": ec,
            "EPR NAME": (r[c_name] if c_name is not None and c_name < len(r) else prev.get("EPR NAME", "")).strip(),
            "AREA": (r[c_area] if c_area is not None and c_area < len(r) else prev.get("AREA", "JATENG")).strip() or "JATENG",
            "CITY": (r[c_city] if c_city is not None and c_city < len(r) else prev.get("CITY", "")).strip(),
            "FY26 TARGET CATEGORY": (r[c_cat] if c_cat is not None and c_cat < len(r) else prev.get("FY26 TARGET CATEGORY", "")).strip(),
            "PACK NAME": pack,
            "AE": ae_val or prev.get("AE", "ARIS") or "ARIS",
        }
        if ec not in order:
            order.append(ec)
        upserted += 1

    if upserted == 0:
        raise ValueError("Tidak ada baris peserta valid ditemukan.")

    fieldnames = ["EPR CODE", "EPR NAME", "AREA", "CITY", "FY26 TARGET CATEGORY", "PACK NAME", "AE"]
    rows_out = [merged[ec] for ec in order]
    with open(peserta_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)

    export_booster_json(tool_dir)
    return {"message": f"Peserta Booster diperbarui: {upserted} baris diproses (total {len(rows_out)} EPR)."}


def sync_skus(xlsx_path, tool_dir):
    smap = _read_xlsx_sheet_map(xlsx_path)
    rows = next(iter(smap.values()), [])
    hdr_idx = None
    for i, r in enumerate(rows[:10]):
        up = [x.upper() for x in r]
        if "MATERIAL CODE" in up and "TYPE" in up:
            hdr_idx = i
            break
    if hdr_idx is None:
        raise ValueError("Header 'Material Code' dan 'Type' tidak ditemukan.")

    hdr = [x.upper() for x in rows[hdr_idx]]
    c_mat = hdr.index("MATERIAL CODE")
    c_desc = hdr.index("DESCRIPTION") if "DESCRIPTION" in hdr else None
    c_type = hdr.index("TYPE")

    rows_out = []
    for r in rows[hdr_idx + 1:]:
        mc = (r[c_mat] if c_mat < len(r) else "").strip().upper()
        tp = (r[c_type] if c_type < len(r) else "").strip().upper()
        if not mc or not tp:
            continue
        desc = (r[c_desc] if c_desc is not None and c_desc < len(r) else "").strip()
        rows_out.append({"Material Code": mc, "Description": desc, "Type": tp})

    if not rows_out:
        raise ValueError("Tidak ada baris SKU tinta valid ditemukan.")

    sku_path = os.path.join(tool_dir, "data", "booster_consumables_sku.csv")
    with open(sku_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Material Code", "Description", "Type"])
        w.writeheader()
        w.writerows(rows_out)

    export_booster_json(tool_dir)
    return {"message": f"SKU Tinta Booster diperbarui: {len(rows_out)} SKU."}


def export_booster_json(tool_dir):
    m = load_masters(tool_dir)
    rules = m["rules"]
    q3 = m["q3_rule"]
    participants = m["participants"]
    ink_skus = sorted(m["ink_set"])
    oth_skus = sorted(m["oth_set"])
    all_ink = m["all_ink"]

    q3["participants"] = {
        ec: {
            "scheme": v["scheme"],
            "pkg": v["pkg"],
            "pack_name": v["pack_name"],
            "fy_cat": v["fy_cat"],
            "ae": v["ae"],
        }
        for ec, v in participants.items()
    }
    q3["ink_bottle_skus"] = ink_skus
    q3["other_ink_skus"] = oth_skus
    rules["Q3 Booster Up"] = q3

    rules_path = os.path.join(tool_dir, "data", "program_rules.json")
    with open(rules_path, "w", encoding="utf-8") as rf:
        json.dump(rules, rf, ensure_ascii=False, indent=2)

    db_path = os.path.join(tool_dir, "data", "booster.db")
    con = _ensure_db(db_path)
    con.row_factory = sqlite3.Row
    tx_rows = con.execute("SELECT * FROM booster_tx").fetchall()
    con.close()

    item_map = defaultdict(lambda: {"qty": 0.0, "net": 0.0, "tx": 0, "desc": "", "kat": "", "eim": ""})
    for r in tx_rows:
        ec = (r["epr"] or "").strip().upper()
        if ec not in participants:
            continue
        kat = (r["kat"] or "").strip()
        mat = (r["material"] or "").strip().upper()
        if kat == "Consumables" and mat not in all_ink:
            continue
        pk = (ec, r["invoice_date"], mat)
        pi = item_map[pk]
        pi["qty"] += r["qty"] or 0.0
        pi["net"] += r["net"] or 0.0
        pi["tx"] += 1
        if r["description"] and not pi["desc"]:
            pi["desc"] = r["description"]
        if kat and not pi["kat"]:
            pi["kat"] = kat
        if r["eim"] and not pi["eim"]:
            pi["eim"] = r["eim"]

    items = [
        {
            "epr": k[0],
            "date": k[1],
            "model": k[2],
            "desc": v["desc"],
            "kat": v["kat"],
            "eim": v["eim"],
            "qty": round(v["qty"]),
            "net": round(v["net"], 2),
            "tx": v["tx"],
        }
        for k, v in item_map.items()
    ]

    payload = {
        "meta": {
            "title": "Q3 Booster Up — Monitoring Paket",
            "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rule": q3,
            "verified_rows": len(tx_rows),
        },
        "participants": list(participants.values()),
        "items": items,
    }
    out_path = os.path.join(tool_dir, "data", "booster_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {"participants": len(participants), "items": len(items), "tx": len(tx_rows)}
