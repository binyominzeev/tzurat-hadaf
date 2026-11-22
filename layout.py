#!/usr/bin/env python3
"""Többoldalas daf-tördelés.
page.json (pilot.py) -> out/layout.json -> [Typst mérés] -> out/pages.json -> [Typst render] -> out/page.pdf
Használat:  python layout.py config.yaml
"""
import json, shutil, subprocess, sys, time
from pathlib import Path
import yaml

DEFAULTS = {
    "slots": {"right": "abudraham", "left": "rashi", "bottom": "vitry"},
    "page": {"width_cm": 21.0, "height_cm": 29.7, "margin_x_cm": 1.4, "margin_top_cm": 1.4, "margin_bottom_cm": 1.7},
    "ratio": [1.0, 1.5, 1.0],        # jobb oszlop : főszöveg : bal oszlop
    "gutter_pt": 9, "gap_pt": 8,
    "main_size_pt": 13, "main_leading_em": 0.55,
    "side_size_pt": 8, "side_leading_em": 0.45,
    "bottom_cols": 3,
    "max_stretch": 0.30,             # a főszöveg legfeljebb ennyivel nyúlhat (a magasság arányában)
    "fonts": ["Frank Ruhl Libre", "David Libre", "Noto Serif Hebrew", "Noto Sans Hebrew"],
    "main_font": None,
}


def atom(t, a, f, m="", b=False, s=""):
    return {"t": t, "a": a, "f": f, "m": m, "b": b, "s": s}


def atoms_abudraham(notes):
    out = []
    for n, note in enumerate(notes, 1):
        words = note["text"].split()
        nb = len(note.get("lemma", "").split())
        for i, w in enumerate(words):
            out.append(atom(w, note["anchor_w"][0], i == 0, str(n) if i == 0 else "", i < nb, "abudraham"))
    return out


def atoms_rashi(unit_notes, n_main):
    """Egységszintű kommentár: a horgonyok egyenletesen oszlanak el a főszöveg szavai között,
    így a hosszú szöveg a főszöveg haladásával arányosan folyik, nem kényszerül az 1. oldalra."""
    out = []
    for un in unit_notes:
        words = un["text"].split()
        a0 = un.get("anchor_w", 0)
        span = max(n_main - a0, 1)
        for i, w in enumerate(words):
            out.append(atom(w, a0 + int(i * span / max(len(words), 1)), i == 0, "", False, "rashi"))
    return out


def atoms_vitry(variants):
    out = []
    for v in sorted(variants, key=lambda v: v["anchor_w"]):
        seq = []  # (szó, félkövér?)
        if v["op"] == "insert":
            seq = [("+", True)] + [(w, False) for w in v["vitry"]]
        elif v["op"] == "delete":
            seq = [(w, True) for w in v["main"]] + [("←", False), ("—", False)]
        else:
            seq = [(w, True) for w in v["main"]] + [("←", False)] + [(w, False) for w in v["vitry"]]
        for i, (w, b) in enumerate(seq):
            out.append(atom(w, v["anchor_w"], i == 0, "", b, "vitry"))
    return out


def atoms_commentary(entries, role):
    out = []
    for entry in entries:
        for i, (word, bold) in enumerate(entry["words"]):
            out.append(atom(word, entry["anchor_w"], i == 0,
                            entry["number"] if i == 0 else "", bold, role))
    return out


def atoms_additional(words, role, n_main):
    return [atom(word, int(i * max(n_main, 1) / max(len(words), 1)),
                 i == 0, "", bold, role)
            for i, (word, bold) in enumerate(words)]


def build_layout(page, cfg, out):
    L = json.loads(json.dumps(DEFAULTS))
    for k, v in (cfg.get("layout") or {}).items():
        if isinstance(v, dict):
            L[k].update(v)
        else:
            L[k] = v
    labels = {k: cfg[k].get("label", k) for k in ("abudraham", "rashi", "vitry") if k in cfg}
    additional = cfg.get("additional_commentaries") or {}
    labels.update({k: source.get("label", k) for k, source in additional.items()})
    if "commentary" in page:
        src = {role: atoms_commentary(entries, role)
               for role, entries in page["commentary"].items()}
    else:
        src = {"abudraham": atoms_abudraham(page["notes"]),
               "rashi": atoms_rashi(page["unit_notes"], len(page["main"])),
               "vitry": atoms_vitry(page["variants"])}
        src.update({role: atoms_additional(words, role, len(page["main"]))
                    for role, words in page.get("additional_commentaries", {}).items()})
    slotkey = {"right": "R", "left": "L", "bottom": "B"}
    streams = {}
    for slot, key in slotkey.items():
        sid = L["slots"].get(slot)
        atoms = sorted(src.get(sid, []), key=lambda x: x["a"])      # stabil: eredeti sorrend marad
        streams[key] = {"label": labels.get(sid, ""), "atoms": atoms}
    bottom_streams = ["B"]
    for i, role in enumerate(additional, 1):
        if role not in src:
            raise ValueError(f"A további kommentár hiányzik a feldolgozott szövegből: {role}")
        key = f"B{i}"
        bottom_streams.append(key)
        streams[key] = {"label": labels[role], "atoms": src[role]}
    # főszöveg + jegyzetszám-jelek (az Abudraham-pontok horgonyán)
    marks = {}
    for n, note in enumerate(page["notes"], 1):
        marks.setdefault(note["anchor_w"][0], []).append(str(n))
    main = [{"t": w["text"], "glue": w["glue"], "k": ",".join(marks.get(i, [])),
             "v": w.get("verse", "")}
            for i, w in enumerate(page["main"])]
    P = L["page"]
    geometry = {
        "page_w": P["width_cm"], "page_h": P["height_cm"], "margin_x": P["margin_x_cm"],
        "margin_top": P["margin_top_cm"], "margin_bottom": P["margin_bottom_cm"],
        "ratio": L["ratio"], "gutter": L["gutter_pt"], "gap": L["gap_pt"],
        "main_size": L["main_size_pt"], "main_leading": L["main_leading_em"],
        "side_size": L["side_size_pt"], "side_leading": L["side_leading_em"],
        "bottom_cols": L["bottom_cols"], "max_stretch": L["max_stretch"],
    }
    data = {"geometry": geometry, "fonts": L["fonts"], "main_font": L["main_font"],
            "bottom_streams": bottom_streams,
            "labels": labels, "main": main, "streams": streams}
    (out / "layout.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


# ---------- Typst futtatás: CLI, ennek hiányában a Python-csomag ----------
def font_args():
    return ["--font-path", "fonts"] if Path("fonts").is_dir() else []

def check_main_font(font):
    if not font:
        return
    if not shutil.which("typst"):
        print(f"Figyelem: a(z) {font} betűcsalád elérhetősége Typst CLI nélkül nem ellenőrizhető.",
              file=sys.stderr)
        return
    result = subprocess.run(["typst", "fonts"] + font_args(), capture_output=True, text=True, check=True)
    if font not in result.stdout.splitlines():
        raise ValueError(f"A főszöveg betűcsaládja nincs telepítve vagy a Typst nem látja: {font}")

def typst_query(inp, selector):
    if shutil.which("typst"):
        r = subprocess.run(["typst", "query", inp, selector, "--field", "value", "--one"] + font_args(),
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stderr)
        return json.loads(r.stdout)
    import typst
    res = typst.query(inp, selector, field="value", one=True, format="json",
                      font_paths=["fonts"] if Path("fonts").is_dir() else [])
    return json.loads(res)

def typst_compile(inp, outp):
    if shutil.which("typst"):
        r = subprocess.run(["typst", "compile", inp, outp] + font_args(), capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stderr)
        return
    import typst
    typst.compile(inp, output=outp, font_paths=["fonts"] if Path("fonts").is_dir() else [])


def main():
    cfgfile = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    cfg = yaml.safe_load(Path(cfgfile).read_text(encoding="utf-8"))
    out = Path("out")
    page = json.loads((out / "page.json").read_text(encoding="utf-8"))
    check_main_font((cfg.get("layout") or {}).get("main_font"))
    build_layout(page, cfg, out)

    t0 = time.time()
    print("==> Mérés és oldalbeosztás (ez eltarthat egy ideig)…")
    pages = typst_query("measure.typ", "<pages>")
    (out / "pages.json").write_text(json.dumps(pages, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"    {len(pages)} oldal, {time.time() - t0:.0f} mp")
    for i, p in enumerate(pages, 1):
        print(f"    {i}. oldal: mód={p['mode']:<5} főszöveg {p['a']}–{p['b']}  "
              f"hasáb-magasság {p['T']:.0f}pt  alsó sáv {p['hb']:.0f}pt  maradék rés {p['slack']:.1f}pt")
    print("==> PDF renderelése")
    typst_compile("render.typ", "out/page.pdf")


if __name__ == "__main__":
    main()
