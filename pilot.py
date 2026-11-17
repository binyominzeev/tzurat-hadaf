#!/usr/bin/env python3
"""Pilot: Sefaria -> page.json + matches.csv (daf-szerű oldal adatai).
Használat:  python pilot.py config.yaml
"""
import argparse, csv, hashlib, html, json, re, sys
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import unquote, urlparse, quote

import yaml
from rapidfuzz import fuzz

CANT = re.compile("[\u0591-\u05AF]")          # ta'amim + az extra jelek (nikud marad)
NIKUD = re.compile("[\u0591-\u05C7]")
FINALS = str.maketrans("ךםןףץ", "כמנפצ")
DIVINE = {'י"י', "יי", "ה'", "יהוה"}
ABBR = {'מ"ה': 'מלך העולם', 'בא"י': 'ברוך אתה י"י'}   # Máchzor Vitry rövidítések
STOP_UNI = {w.translate(FINALS) for w in ("פסוק", "כלומר", "רל", "שנאמר")}
STOP_BI = {(a.translate(FINALS), b.translate(FINALS)) for a, b in (("על", "שם"), ("עם", "שם"))}
API = "https://www.sefaria.org/api/v3/texts/{ref}"


# ---------- letöltés / beolvasás ----------
def flatten(t):
    if isinstance(t, str):
        return t
    if isinstance(t, list):
        return " ".join(flatten(x) for x in t if x)
    return ""

def fetch(cfg, cache=Path("cache")):
    if "file" in cfg:                                  # kézzel bemásolt szöveg
        return Path(cfg["file"]).read_text(encoding="utf-8")
    import requests
    ref = unquote(urlparse(cfg["url"]).path).lstrip("/")
    version = cfg.get("version", "hebrew")
    cache.mkdir(exist_ok=True)
    cf = cache / (hashlib.sha1(f"{ref}|{version}".encode()).hexdigest() + ".json")
    if cf.exists():
        data = json.loads(cf.read_text(encoding="utf-8"))
    else:
        r = requests.get(API.format(ref=quote(ref, safe="")), params={"version": version}, timeout=30)
        r.raise_for_status()
        data = r.json()
        cf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    vs = data.get("versions") or []
    if not vs:
        sys.exit(f"Nincs verzió a válaszban: {ref} ({version}). Nyers válasz: {cf}")
    return flatten(vs[0]["text"])


# ---------- tisztítás / normalizálás ----------
def clean(s, corrections=False, divine=None):
    s = re.sub(r"<sup[^>]*>.*?</sup>|<i class=\"footnote\">.*?</i>", "", s, flags=re.S)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    s = CANT.sub("", s).replace("|", " ").replace("״", '"').replace("׳", "'")
    if corrections:                                    # (eredeti) [javított] -> javított
        s = re.sub(r"\([^()]*\)\s*(?=\[)", "", s)
        s = s.replace("[", "").replace("]", "")
    if divine:
        s = re.sub("יְהֹוָה", divine, s)
    return re.sub(r"[ \t\r\n]+", " ", s).strip()

def key(w, skeleton=True):
    w = NIKUD.sub("", w).replace("־", "")
    if w.strip(".,:;") in DIVINE:
        return "ה"
    w = re.sub(r"[^\u05D0-\u05EA]", "", w).translate(FINALS).replace("אלק", "אלה")
    if skeleton:
        sk = w.replace("ו", "").replace("י", "")
        w = sk or w
    return w

def tokens(text):
    out = []
    for raw in text.replace("־", "־ ").split():
        k = key(raw)
        if not k:
            continue
        out.append({"text": raw, "norm": k, "glue": raw.endswith("־")})
    return out


# ---------- Abudraham: sorrendtartó fuzzy illesztés ----------
def lemma_of(seg_toks, maxw):
    ks = [t["norm"] for t in seg_toks]
    plain = [key(t["text"], False) for t in seg_toks]
    n = 0
    while n < min(len(ks), maxw):
        if plain[n] in STOP_UNI or (n + 1 < len(plain) and (plain[n], plain[n + 1]) in STOP_BI):
            break
        n += 1
    return seg_toks[:max(n, 0)]

def align_abudraham(main, text, o, overrides):
    segs = [s for s in re.split(r"(?<=[.:])\s+", text) if s.strip()]
    mk = [t["norm"] for t in main]
    notes, rows, cursor = [], [], 0
    for i, seg in enumerate(segs):
        toks = tokens(seg)
        lem = lemma_of(toks, o["lemma_max_words"])
        best = (-1, None)
        if i in overrides:
            best = (100, overrides[i])
        elif lem:
            w = len(lem)
            lk = " ".join(t["norm"] for t in lem)
            lo, hi = max(0, cursor - 3), min(len(mk) - w + 1, cursor + o["lookahead"])
            for p in range(lo, max(hi, lo)):
                sc = fuzz.ratio(lk, " ".join(mk[p:p + w]))
                if sc > best[0]:
                    best = (sc, p)
        score, p = best
        ok = p is not None and score >= o["threshold"]
        lemtxt = " ".join(t["text"] for t in lem)
        if ok:
            w = max(len(lem), 1)
            cursor = p + 1
            notes.append({"src": "abudraham", "anchor_w": [p, min(p + w - 1, len(main) - 1)],
                          "lemma": lemtxt, "text": seg, "quality": round(score / 100, 2)})
        elif notes:
            notes[-1]["text"] += " " + seg
        else:
            notes.append({"src": "abudraham", "anchor_w": [0, 0], "lemma": "", "text": seg, "quality": 0})
        rows.append([i, "ok" if ok else "inherited", round(score, 1), p if ok else "", lemtxt, seg[:60]])
    return notes, rows


# ---------- Máchzor Vitry: nusach-variánsok ----------
def vitry_variants(main, text):
    for a, b in ABBR.items():
        text = text.replace(a, b)
    vt = tokens(text)
    a = [t["norm"] for t in main]
    b = [t["norm"] for t in vt]
    var, tail = [], []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert" and i1 == len(main):
            tail = [t["text"] for t in vt[j1:j2]]
            continue
        var.append({"src": "machzor_vitry", "op": tag, "anchor_w": i1,
                    "main": [t["text"] for t in main[i1:i2]],
                    "vitry": [t["text"] for t in vt[j1:j2]]})
    return var, tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    o = {"threshold": 75, "lookahead": 60, "lemma_max_words": 6, "divine_name": None}
    o.update(cfg.get("options") or {})
    out = Path(args.out); out.mkdir(exist_ok=True)

    main_txt = clean(fetch(cfg["main"]), divine=o["divine_name"])
    main_toks = tokens(main_txt)
    page = {"unit": cfg.get("unit", "unit"), "main": main_toks,
            "notes": [], "unit_notes": [], "variants": [], "vitry_tail": [],
            "labels": {k: cfg[k].get("label", k) for k in ("abudraham", "rashi", "vitry") if k in cfg}}
    rows = []

    if "abudraham" in cfg:
        ov = {int(k): int(v) for k, v in (cfg.get("overrides", {}).get("abudraham") or {}).items()}
        page["notes"], rows = align_abudraham(main_toks, clean(fetch(cfg["abudraham"])), o, ov)

    if "rashi" in cfg:
        t = clean(fetch(cfg["rashi"]), corrections=cfg["rashi"].get("corrections", True))
        page["unit_notes"].append({"src": "siddur_rashi", "anchor_w": cfg["rashi"].get("anchor_w", 0), "text": t})

    if "vitry" in cfg:
        t = clean(fetch(cfg["vitry"]))
        cut = cfg["vitry"].get("cut_before")
        if cut and cut in t:
            t = t[:t.index(cut)]
        page["variants"], page["vitry_tail"] = vitry_variants(main_toks, t)

    (out / "page.json").write_text(json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "matches.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["seg", "status", "score", "anchor_w", "lemma", "text_start"])
        w.writerows(rows)
    bad = sum(1 for r in rows if r[1] != "ok")
    print(f"main: {len(main_toks)} szó | abudraham: {len(rows)} szegmens, {bad} örökölt | "
          f"variáns: {len(page['variants'])} | vitry-farok: {len(page['vitry_tail'])} szó")

if __name__ == "__main__":
    main()
