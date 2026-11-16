# -*- coding: utf-8 -*-
"""Sinkronisasi otomatis data Q3 Booster Up dari repo lama (ariswidodo/EPR) secara read-only."""
import argparse
import csv
import datetime
import io
import json
import os
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import booster_engine as BE

DEFAULT_LOCAL_EPR = r"D:\Project Hitung Achv\EPR_Dashboard"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/ariswidodo/EPR/main/data"
MASTER_FILES = [
    "peserta_booster.csv",
    "booster_consumables_sku.csv",
    "program_rules.json",
    "epp_master.csv",
]


def _fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Q3-Booster-Up-Sync/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _parse_participants_csv(text):
    participants = []
    for r in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        ec = (r.get("EPR CODE") or "").strip().upper()
        pack = (r.get("PACK NAME") or "").strip()
        if not ec or not pack:
            continue
        scheme = "consumables" if "CONSUMABLES" in pack.upper() else "unit_ink"
        participants.append({
            "code": ec,
            "name": (r.get("EPR NAME") or "").strip(),
            "city": (r.get("CITY") or "").strip(),
            "area": (r.get("AREA") or "JATENG").strip() or "JATENG",
            "fy_cat": (r.get("FY26 TARGET CATEGORY") or "").strip(),
            "pack_name": pack,
            "pkg": pack.split()[0].upper(),
            "scheme": scheme,
            "ae": (r.get("AE") or "ARIS").strip() or "ARIS",
        })
    return participants


def _parse_skus_csv(text):
    ink, oth = [], []
    for r in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        mc = (r.get("Material Code") or "").strip().upper()
        tp = (r.get("Type") or "").strip().upper()
        if not mc:
            continue
        if tp == "INK BOTTLE":
            ink.append(mc)
        elif tp == "OTHERS INK BOTTLE":
            oth.append(mc)
    return sorted(set(ink)), sorted(set(oth))


def sync_from_local(epr_dir=DEFAULT_LOCAL_EPR):
    src_data = os.path.join(epr_dir, "data")
    dst_data = os.path.join(ROOT, "data")
    os.makedirs(dst_data, exist_ok=True)

    for fname in MASTER_FILES + ["sku.xlsx"]:
        s = os.path.join(src_data, fname)
        d = os.path.join(dst_data, fname)
        if os.path.isfile(s):
            if not os.path.isfile(d) or os.path.getmtime(s) > os.path.getmtime(d):
                shutil.copy2(s, d)

    epr_db = os.path.join(src_data, "epr.db")
    if os.path.isfile(epr_db):
        return BE.seed_from_epr_db(epr_db, ROOT)
    raise FileNotFoundError(f"epr.db tidak ditemukan di {src_data}")


def sync_from_github(raw_base=GITHUB_RAW_BASE):
    dst_data = os.path.join(ROOT, "data")
    os.makedirs(dst_data, exist_ok=True)

    downloaded = {}
    for fname in MASTER_FILES:
        try:
            raw = _fetch_bytes(f"{raw_base}/{fname}?t={int(datetime.datetime.now().timestamp())}")
            downloaded[fname] = raw.decode("utf-8-sig")
            with open(os.path.join(dst_data, fname), "wb") as f:
                f.write(raw)
        except Exception as exc:
            print(f"Warn: gagal ambil {fname}: {exc}")

    epr_raw = _fetch_bytes(f"{raw_base}/epr_data.json?t={int(datetime.datetime.now().timestamp())}")
    epr_data = json.loads(epr_raw.decode("utf-8"))

    peserta_text = downloaded.get("peserta_booster.csv")
    if not peserta_text:
        with open(os.path.join(dst_data, "peserta_booster.csv"), encoding="utf-8-sig") as f:
            peserta_text = f.read()
    participants = _parse_participants_csv(peserta_text)
    p_map = {p["code"]: p for p in participants}

    sku_text = downloaded.get("booster_consumables_sku.csv")
    if not sku_text:
        with open(os.path.join(dst_data, "booster_consumables_sku.csv"), encoding="utf-8-sig") as f:
            sku_text = f.read()
    ink_skus, oth_skus = _parse_skus_csv(sku_text)
    all_ink = set(ink_skus) | set(oth_skus)

    epr_meta = epr_data.get("meta") or {}
    q3_rule = (epr_meta.get("program_rules") or {}).get("Q3 Booster Up") or {}
    if not q3_rule:
        with open(os.path.join(dst_data, "program_rules.json"), encoding="utf-8") as f:
            q3_rule = json.load(f).get("Q3 Booster Up") or {}

    if ink_skus:
        q3_rule["ink_bottle_skus"] = ink_skus
    if oth_skus:
        q3_rule["other_ink_skus"] = oth_skus
    q3_rule["participants"] = {
        p["code"]: {
            "scheme": p["scheme"],
            "pkg": p["pkg"],
            "pack_name": p["pack_name"],
            "fy_cat": p["fy_cat"],
            "ae": p["ae"],
        }
        for p in participants
    }

    item_map = {}
    for x in epr_data.get("program_items") or []:
        if x.get("prog") != "Q3 Booster Up":
            continue
        ec = (x.get("epr") or "").strip().upper()
        if ec not in p_map:
            continue
        kat = (x.get("kat") or "").strip()
        model = (x.get("model") or "").strip().upper()
        if kat == "Consumables" and model not in all_ink:
            continue
        pk = (ec, x.get("date") or "", model)
        cur = item_map.get(pk)
        if not cur:
            item_map[pk] = {
                "epr": ec,
                "date": pk[1],
                "model": model,
                "desc": x.get("desc") or "",
                "kat": kat,
                "eim": x.get("eim") or "",
                "qty": 0,
                "net": 0.0,
                "tx": 0,
            }
            cur = item_map[pk]
        cur["qty"] += int(round(x.get("qty") or 0))
        cur["net"] = round(cur["net"] + float(x.get("net") or 0), 2)
        cur["tx"] += int(x.get("tx") or 1)

    items = list(item_map.values())
    payload = {
        "meta": {
            "title": "Q3 Booster Up — Monitoring Paket",
            "generated_at": epr_meta.get("generated_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_repo": "ariswidodo/EPR",
            "rule": q3_rule,
            "verified_rows": sum(x["tx"] for x in items),
        },
        "participants": participants,
        "items": items,
    }

    out_path = os.path.join(dst_data, "booster_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return {"participants": len(participants), "items": len(items), "tx": payload["meta"]["verified_rows"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("auto", "local", "github"), default="auto")
    ap.add_argument("--epr-dir", default=DEFAULT_LOCAL_EPR)
    args = ap.parse_args()

    src = args.source
    if src == "auto":
        src = "local" if os.path.isfile(os.path.join(args.epr_dir, "data", "epr.db")) else "github"

    if src == "local":
        stats = sync_from_local(args.epr_dir)
    else:
        stats = sync_from_github()
    print(f"Sync ({src}) selesai:", stats)


if __name__ == "__main__":
    main()
