#!/usr/bin/env python3
"""NiceGUI editor for the Sefaria daf-style PDF configuration."""

import asyncio
import copy
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlparse

import requests
import yaml
from nicegui import app, run, ui

from pilot import clean, fetch, fetch_data, fetch_verse_commentary, flatten


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.ui.yaml"
BASE_CONFIG_PATH = ROOT / "config.live.yaml"
SAMPLE_CONFIG_PATH = ROOT / "config.yaml"
ROLE_LABELS = {
    "main": "Főszöveg",
    "abudraham": "Jobb oldali kommentár · Abudraham",
    "rashi": "Bal oldali kommentár · Rási",
    "vitry": "Alsó sáv · Máchzor Vitri",
}
ROLE_DEFAULTS = {
    "main": {"version": "hebrew"},
    "abudraham": {"label": "אבודרהם", "version": "hebrew"},
    "rashi": {"label": 'רש"י', "version": "hebrew", "corrections": True},
    "vitry": {"label": "מחזור ויטרי", "version": "hebrew", "cut_before": "אהבת עולם"},
}
MAIN_FONTS = ["Taamey Ashkenaz", "Taamey Frank CLM", "Frank Ruehl CLM", "SBL Hebrew"]
LAYOUT_DEFAULTS = {
    "page": {
        "width_cm": 21.0,
        "height_cm": 29.7,
        "margin_x_cm": 1.4,
        "margin_top_cm": 1.4,
        "margin_bottom_cm": 1.7,
    },
    "ratio": [1.0, 1.5, 1.0],
    "gutter_pt": 9,
    "gap_pt": 8,
    "main_size_pt": 13,
    "side_size_pt": 8,
    "bottom_cols": 3,
    "max_stretch": 0.30,
    "main_leading_em": 0.55,
    "side_leading_em": 0.45,
    "fonts": ["Frank Ruhl Libre", "David Libre", "Noto Serif Hebrew", "Noto Sans Hebrew"],
    "main_font": None,
    "tablet_mode": False,
    "tablet_commentary": None,
    "slots": {"right": "abudraham", "left": "rashi", "bottom": "vitry"},
}
NUMERIC_FIELDS = {
    "page_width": (10.0, 50.0, 0.1, "Oldalszélesség (cm)"),
    "page_height": (10.0, 60.0, 0.1, "Oldalmagasság (cm)"),
    "margin_x": (0.0, 5.0, 0.1, "Oldalsó margó (cm)"),
    "margin_top": (0.0, 5.0, 0.1, "Felső margó (cm)"),
    "margin_bottom": (0.0, 5.0, 0.1, "Alsó margó (cm)"),
}
LAYOUT_FIELDS = {
    "ratio_right": (0.3, 5.0, 0.1, "Jobb hasáb aránya"),
    "ratio_main": (0.3, 5.0, 0.1, "Főszöveg aránya"),
    "ratio_left": (0.3, 5.0, 0.1, "Bal hasáb aránya"),
    "main_size_pt": (6, 32, 1, "Főszöveg mérete (pt)"),
    "side_size_pt": (5, 24, 1, "Kommentár mérete (pt)"),
    "gutter_pt": (0, 40, 1, "Hasábköz (pt)"),
    "gap_pt": (0, 40, 1, "Felső és alsó sáv közti tér (pt)"),
    "bottom_cols": (1, 8, 1, "Alsó hasábok száma"),
    "max_stretch": (0.0, 1.0, 0.05, "Max. sortávolság-nyújtás"),
    "main_leading_em": (0.1, 3.0, 0.05, "Főszöveg sortávja (em)"),
    "side_leading_em": (0.1, 3.0, 0.05, "Kommentár sortávja (em)"),
}
LAYOUT_PRESETS = {
    "print": {
        "page_width": 21.0,
        "page_height": 29.7,
        "main_size_pt": 13,
        "side_size_pt": 8,
        "tablet_mode": False,
    },
    "tablet": {
        "page_width": 29.7,
        "page_height": 21.0,
        "main_size_pt": 30,
        "side_size_pt": 20,
        "tablet_mode": True,
    },
}
SLOT_LABELS = {"right": "Jobb hasáb", "left": "Bal hasáb", "bottom": "Alsó sáv"}
PREFERRED_SLOTS = {"abudraham": "right", "rashi": "left", "vitry": "bottom"}


def load_config() -> dict:
    path = CONFIG_PATH if CONFIG_PATH.exists() else BASE_CONFIG_PATH
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"A konfiguráció gyökéreleme nem objektum: {path}")
    return data


def validate_sefaria_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"sefaria.org", "www.sefaria.org"}
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or not parsed.path.strip("/")
    ):
        raise ValueError("Érvényes https://www.sefaria.org/... hivatkozást adj meg.")
    return url.strip()


def initial_settings(config: dict) -> dict:
    configured = config.get("layout") or {}
    settings = copy.deepcopy(LAYOUT_DEFAULTS)
    for key, value in configured.items():
        if isinstance(value, dict) and isinstance(settings.get(key), dict):
            settings[key].update(value)
        else:
            settings[key] = value
    page = settings["page"]
    ratio = settings["ratio"]
    settings.update(
        {
            "page_width": page["width_cm"],
            "page_height": page["height_cm"],
            "margin_x": page["margin_x_cm"],
            "margin_top": page["margin_top_cm"],
            "margin_bottom": page["margin_bottom_cm"],
            "ratio_right": ratio[0],
            "ratio_main": ratio[1],
            "ratio_left": ratio[2],
        }
    )
    settings["options"] = {
        "threshold": 75,
        "lookahead": 60,
        "lemma_max_words": 6,
        **(config.get("options") or {}),
    }
    return settings


def sample_previews() -> dict:
    previews = {}
    sample_names = {"main": "main", "abudraham": "abudraham", "rashi": "rashi", "vitry": "vitry"}
    for key, sample in sample_names.items():
        path = ROOT / "samples" / f"{sample}.txt"
        if path.exists():
            previews[key] = path.read_text(encoding="utf-8")
    generated = ROOT / "out" / "page.json"
    if generated.exists():
        try:
            page = json.loads(generated.read_text(encoding="utf-8"))
            previews["main"] = " ".join(word["text"] for word in page.get("main", []))
            if page.get("notes"):
                previews["abudraham"] = " ".join(note["text"] for note in page["notes"])
            if page.get("unit_notes"):
                previews["rashi"] = " ".join(note["text"] for note in page["unit_notes"])
            if page.get("variants") or page.get("vitry_tail"):
                variants = page.get("variants", [])
                previews["vitry"] = " ".join(
                    " ".join(variant.get("vitry", [])) for variant in variants
                ) + " " + " ".join(page.get("vitry_tail", []))
        except (json.JSONDecodeError, OSError, KeyError, TypeError) as error:
            print(f"Az előző előnézeti adat nem olvasható: {error}")
    return previews


config = load_config()
sources = {key: copy.deepcopy(config[key]) for key in ROLE_LABELS if key in config}
sources.update(copy.deepcopy(config.get("additional_commentaries") or {}))
sample_config = yaml.safe_load(SAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
sample_sources = {key: sample_config[key] for key in ROLE_LABELS if key in sample_config}
default_sample_mode = all(
    key in sample_sources and source.get("url") == sample_sources[key].get("url")
    for key, source in sources.items()
) and (
    any("file" in source for source in sources.values())
    or not (ROOT / "cache").exists()
    or not any((ROOT / "cache").glob("*.json"))
)
sample_mode = (config.get("ui") or {}).get("sample_mode", default_sample_mode)
settings = initial_settings(config)
settings["tablet_commentary"] = (
    settings["tablet_commentary"]
    or settings["slots"].get("left")
    or settings["slots"].get("right")
    or settings["slots"].get("bottom")
)
previews = sample_previews()
slot_values = copy.deepcopy(settings["slots"])
DEFAULT_STACK = "Szidur"
TORAH_STACK = {
    "sources": {
        "main": {"title": "Genesis", "from": "1:1", "to": "1:5", "version": "hebrew",
                 "url": "https://www.sefaria.org/Genesis.1.1-5", "label": "תורה"},
        "rashi": {"title": "Rashi on Genesis", "from": "1:1", "to": "1:5", "version": "hebrew",
                  "url": "https://www.sefaria.org/Rashi_on_Genesis.1.1-5", "label": 'רש"י',
                  "corrections": True},
    },
    "slots": {"right": "", "left": "rashi", "bottom": ""},
}
stacks = {
    name: copy.deepcopy(stack)
    for name, stack in (config.get("stacks") or {}).items()
    if isinstance(stack, dict)
}
stacks.setdefault(DEFAULT_STACK, {})
if "Tóra" not in stacks:
    stacks["Tóra"] = copy.deepcopy(TORAH_STACK)
active_stack = (config.get("ui") or {}).get("active_stack")
if active_stack not in stacks:
    active_stack = DEFAULT_STACK
stack_tabs = None
sefaria_titles = []
slot_controls = {}
source_assignment_controls = {}
numeric_controls = {}
layout_controls = {}
source_area = None
stack_area = None
preview_area = None
status_label = None
build_log = None
build_button = None
download_button = None
build_progress = None
orientation_switch = None
preset_control = None
tablet_commentary_control = None
sample_switch = None
page_nav_label = None
previous_page_button = None
next_page_button = None
preview_pages = []
preview_layout = {}
preview_page_index = 0
preview_status_label = None
pipeline_lock = asyncio.Lock()
preview_revision = 0
preview_debounce_task = None
preview_worker_tasks = set()
preview_pdf_version = 0


def source_label(key: str) -> str:
    source = sources.get(key, {})
    return source.get("label") or source.get("title") or ROLE_LABELS.get(key, "További kommentár")


def extra_source_key(existing: dict) -> str:
    index = 1
    while f"extra_{index}" in existing:
        index += 1
    return f"extra_{index}"


def build_sefaria_url(title: str, start: str = "", end: str = "") -> str:
    ref = title.strip().replace(" ", "_")
    start = start.strip().replace(":", ".").replace(" ", "")
    end = end.strip().replace(":", ".").replace(" ", "")
    if start:
        ref += "." + start
        head, _, _ = start.rpartition(".")
        if head and end.startswith(head + "."):
            end = end[len(head) + 1:]
        if end:
            ref += "-" + end
    return "https://www.sefaria.org/" + quote(ref, safe="._-")


def load_text_refs(title: str) -> list:
    response = requests.get(
        "https://www.sefaria.org/api/v2/raw/index/" + quote(title, safe=""),
        headers={"User-Agent": "tzurat-hadaf"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("error"):
        raise ValueError(str(data["error"]))
    root = data.get("title")
    schema = data.get("schema")
    if not isinstance(root, str) or not isinstance(schema, dict):
        raise ValueError("A Sefaria indexében nincs érvényes műszerkezet.")
    refs = []

    def walk(node: dict, ref: str) -> None:
        children = node.get("nodes") or []
        if not children:
            if not node.get("depth"):
                raise ValueError(f"A műrész szerkezete nem támogatott: {ref}")
            refs.append(ref)
            return
        for child in children:
            if child.get("default"):
                child_ref = ref
            else:
                primary = next(
                    (entry for entry in child.get("titles", [])
                     if entry.get("lang") == "en" and entry.get("primary")),
                    None,
                )
                name = primary["text"] if primary else child.get("sharedTitle")
                if not name:
                    raise ValueError(f"A mű egyik részének nincs angol neve: {ref}")
                child_ref = name if primary and primary.get("presentation") == "alone" else f"{ref}, {name}"
            walk(child, child_ref)

    walk(schema, root)
    if not refs:
        raise ValueError("A Sefaria indexében nincs választható műrész.")
    return list(dict.fromkeys(refs))


def load_section_shape(title: str, version: str) -> dict:
    response = requests.get(
        "https://www.sefaria.org/api/v3/texts/" + quote(title, safe=""),
        params={"version": version},
        headers={"User-Agent": "tzurat-hadaf"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    versions = data.get("versions") or []
    if data.get("error"):
        raise ValueError(str(data["error"]))
    if not versions:
        raise ValueError("A kiválasztott verzióhoz nincs elérhető szöveg.")
    text = versions[0].get("text")
    names = data.get("sectionNames") or []
    address_types = data.get("addressTypes") or []
    if (
        not isinstance(text, list)
        or not text
        or not names
        or not address_types
        or address_types[0] not in ("Integer", "Perek", "Talmud")
        or (len(names) > 1 and (len(address_types) < 2 or address_types[1] not in ("Integer", "Pasuk")))
    ):
        raise ValueError("Ehhez a műhöz nem áll rendelkezésre támogatott számozott szerkezet.")
    if len(names) > 1 and any(not isinstance(chapter, list) for chapter in text):
        raise ValueError("A mű szakaszainak szerkezete nem támogatott.")
    return {
        "names": names[:2],
        "talmud": address_types[0] == "Talmud",
        "counts": [len(chapter) if isinstance(chapter, list) else 1 for chapter in text],
    }


def section_label(index: int, talmud: bool) -> str:
    if talmud:
        return f"{index // 2 + 1}{'a' if index % 2 == 0 else 'b'}"
    return str(index + 1)


def validate_section_range(start: str, end: str, shape: dict) -> None:
    if end and not start:
        raise ValueError("A szakasz végéhez kezdőpontot is válassz.")
    if not start or not end:
        return

    def position(value: str, is_end: bool) -> tuple:
        parts = value.replace(".", ":").split(":")
        labels = [section_label(i, shape["talmud"]) for i in range(len(shape["counts"]))]
        if len(parts) > 2 or parts[0] not in labels:
            raise ValueError("A szakasz nem szerepel a kiválasztott műben.")
        chapter = labels.index(parts[0])
        if len(parts) == 1:
            return chapter, shape["counts"][chapter] if is_end else 1
        if len(shape["names"]) < 2 or not parts[1].isdigit():
            raise ValueError("Érvénytelen szakaszszám.")
        verse = int(parts[1])
        if not 1 <= verse <= shape["counts"][chapter]:
            raise ValueError("A szakasz nem szerepel a kiválasztott műben.")
        return chapter, verse

    if position(start, False) > position(end, True):
        raise ValueError("A szakasz vége nem lehet a kezdete előtt.")


TORAH_BOOKS = {"Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy"}


def source_ref(source: dict) -> str:
    path = unquote(urlparse(validate_sefaria_url(source["url"])).path).lstrip("/")
    return re.split(r"\.(?=\d)", path, maxsplit=1)[0].replace("_", " ")


def shared_torah_sources(current: dict, start: str, end: str, shape: dict) -> dict:
    if not start or not end:
        raise ValueError("Válaszd ki a kezdő és a záró verset is.")
    if shape["names"] != ["Chapter", "Verse"] or shape["talmud"]:
        raise ValueError("A közös szakaszválasztó csak fejezetekre és versekre bontott Tórához használható.")
    if any(not re.fullmatch(r"\d+:\d+", value) for value in (start, end)):
        raise ValueError("A kezdő és a záró pontot fejezet:vers formában add meg.")
    validate_section_range(start, end, shape)
    if "main" not in current:
        raise ValueError("Először válassz tórai főszöveget.")
    base = source_ref(current["main"])
    if base not in TORAH_BOOKS:
        raise ValueError("A közös szakaszválasztó csak a Tóra öt könyvéhez használható.")
    updated = copy.deepcopy(current)
    for key, source in updated.items():
        ref = source_ref(source)
        if key != "main" and not (ref.endswith(" on " + base) or ref.endswith(", " + base)):
            raise ValueError(f"A(z) {source.get('label', ref)} nem a(z) {base} könyvhöz tartozik.")
        source["url"] = build_sefaria_url(ref, start, end)
        source["from"] = start
        source["to"] = end
        if not source.get("title"):
            source["section_ref"] = ref
    return updated


def fetch_shared_torah_sources(updated: dict) -> tuple:
    data = {}
    missing = []
    for key in ["main"] + [key for key in updated if key != "main"]:
        source = updated[key]
        if key == "main":
            response = fetch_data(source, ROOT / "cache")
            if response.get("primary_category") != "Tanakh" or response.get("book") not in TORAH_BOOKS:
                raise ValueError("A kiválasztott főszöveg nem tórai könyv.")
            base = response["book"]
            main_data = response
        else:
            response, is_missing = fetch_verse_commentary(source, main_data, ROOT / "cache")
            if is_missing:
                missing.append(source.get("label") or source_ref(source))
            book = response.get("book", "")
            if not (book.endswith(" on " + base) or book.endswith(", " + base)):
                raise ValueError(f"A(z) {source.get('label', book)} nem a(z) {base} könyvhöz tartozik.")
            if response.get("sectionNames", [])[:2] != ["Chapter", "Verse"]:
                raise ValueError(f"A(z) {source.get('label', book)} nem versenkénti kommentár.")
        data[key] = clean(flatten(response["versions"][0]["text"]),
                          corrections=source.get("corrections", False),
                          preserve_cantillation=key == "main")
    return data, missing


def open_section_picker(shape: dict, on_select) -> None:
    with ui.dialog() as picker, ui.card().classes("w-[min(90vw,600px)]"):
        heading = ui.label().classes("text-lg font-bold")
        tiles = ui.column().classes("w-full max-h-[60vh] overflow-auto")

        def select_chapter(index: int) -> None:
            chapter = section_label(index, shape["talmud"])
            if len(shape["names"]) == 1:
                on_select(chapter)
                picker.close()
                return
            heading.text = f"{shape['names'][1]} · {chapter}"
            tiles.clear()
            with tiles:
                with ui.row().classes("w-full gap-1"):
                    for number in range(1, shape["counts"][index] + 1):
                        ui.button(str(number), on_click=lambda n=number: select_verse(chapter, n)
                                  ).props("outline dense").classes("min-w-10")
                ui.button("Vissza", on_click=show_chapters).props("flat")

        def select_verse(chapter: str, number: int) -> None:
            on_select(f"{chapter}:{number}")
            picker.close()

        def show_chapters() -> None:
            heading.text = shape["names"][0]
            tiles.clear()
            with tiles, ui.row().classes("w-full gap-1"):
                for index, count in enumerate(shape["counts"]):
                    if count:
                        ui.button(section_label(index, shape["talmud"]),
                                  on_click=lambda i=index: select_chapter(i)
                                  ).props("outline dense").classes("min-w-10")

        show_chapters()
        ui.button("Mégse", on_click=picker.close).props("flat")
    picker.open()


def load_sefaria_titles() -> list:
    path = ROOT / "sefaria_titles.json"
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        response = requests.get(
            "https://www.sefaria.org/api/index",
            headers={"User-Agent": "tzurat-hadaf"},
            timeout=60,
        )
        response.raise_for_status()
        titles = []

        def walk(nodes) -> None:
            for node in nodes:
                if node.get("title"):
                    titles.append(node["title"])
                walk(node.get("contents", []))

        walk(response.json())
        titles = sorted(set(titles))
        path.write_text(json.dumps(titles, ensure_ascii=False), encoding="utf-8")
        return titles
    except (OSError, ValueError, requests.RequestException) as error:
        print(f"A Sefaria-címlista nem érhető el: {error}")
        return []


def snapshot_stack() -> None:
    stacks[active_stack] = {
        "sources": copy.deepcopy(sources),
        "slots": copy.deepcopy(slot_values),
    }


def make_config() -> dict:
    result = copy.deepcopy(config)
    for key in ROLE_LABELS:
        result.pop(key, None)
    result["additional_commentaries"] = {}
    for key, source in sources.items():
        target = result if key in ROLE_LABELS else result["additional_commentaries"]
        target[key] = copy.deepcopy(source)
        target[key].pop("file", None)
        target[key]["url"] = validate_sefaria_url(target[key]["url"])
        target[key].setdefault("version", "hebrew")
        if sample_mode:
            sample = sample_sources.get(key, {})
            if source.get("url") != sample.get("url") or "file" not in sample:
                raise ValueError(f"Nincs minta a(z) {source_label(key)} kiválasztott URL-jéhez.")
            target[key]["file"] = sample["file"]

    layout = copy.deepcopy(settings)
    layout["page"] = {
        "width_cm": settings["page_width"],
        "height_cm": settings["page_height"],
        "margin_x_cm": settings["margin_x"],
        "margin_top_cm": settings["margin_top"],
        "margin_bottom_cm": settings["margin_bottom"],
    }
    layout["ratio"] = [settings["ratio_right"], settings["ratio_main"], settings["ratio_left"]]
    for key in ("page_width", "page_height", "margin_x", "margin_top", "margin_bottom",
                "ratio_right", "ratio_main", "ratio_left", "options"):
        layout.pop(key, None)
    layout["slots"] = copy.deepcopy(slot_values)
    result["layout"] = layout
    result["ui"] = {
        **(config.get("ui") or {}),
        "sample_mode": sample_mode,
        "active_stack": active_stack,
    }
    result["stacks"] = {
        name: {"sources": copy.deepcopy(sources), "slots": copy.deepcopy(slot_values)}
        if name == active_stack
        else copy.deepcopy(stack)
        for name, stack in stacks.items()
    }
    for stack in result["stacks"].values():
        for source in stack.get("sources", {}).values():
            source.pop("file", None)
    result["options"] = {
        key: settings["options"][key]
        for key in ("threshold", "lookahead", "lemma_max_words", "divine_name")
        if key in settings["options"]
    }
    return result


def persist_config() -> None:
    CONFIG_PATH.write_text(
        yaml.safe_dump(make_config(), allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


def refresh_slot_options() -> None:
    options = {"": "— nincs —", **{key: source_label(key) for key in sources
                                      if key != "main" and key in ROLE_LABELS}}
    for slot, control in slot_controls.items():
        control.options = options
        if control.value not in options:
            control.value = ""
            slot_values[slot] = ""
        control.update()


def load_preview_pages() -> None:
    global preview_pages, preview_layout, preview_page_index, preview_pdf_version
    pages_path = ROOT / "out" / "pages.json"
    layout_path = ROOT / "out" / "layout.json"
    try:
        pages = json.loads(pages_path.read_text(encoding="utf-8"))
        layout = json.loads(layout_path.read_text(encoding="utf-8"))
        if not isinstance(pages, list) or not isinstance(layout.get("main"), list):
            raise ValueError("Az előnézeti fájlok szerkezete nem megfelelő.")
        preview_pages = pages
        preview_layout = layout
        preview_page_index = min(preview_page_index, max(len(preview_pages) - 1, 0))
        preview_pdf_version += 1
    except FileNotFoundError:
        preview_pages = []
        preview_layout = {}
        preview_page_index = 0
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
        print(f"Az oldalankénti előnézet nem olvasható: {error}")
        preview_pages = []
        preview_layout = {}
        preview_page_index = 0


def page_preview_content(index: int) -> dict:
    if not preview_pages:
        return {
            "main": previews.get("main", "A főszöveg az API-hivatkozás mentése után jelenik meg."),
            "right": previews.get(slot_values.get("right"), ""),
            "left": previews.get(slot_values.get("left"), ""),
            "bottom": previews.get(slot_values.get("bottom"), ""),
            "right_label": source_label(slot_values.get("right", "")) if slot_values.get("right") else "—",
            "left_label": source_label(slot_values.get("left", "")) if slot_values.get("left") else "—",
            "bottom_label": source_label(slot_values.get("bottom", "")) if slot_values.get("bottom") else "—",
        }

    page = preview_pages[index]
    main_words = preview_layout["main"][page["a"]:page["b"]]
    main = "".join(
        html.escape(word["t"])
        + (f'<sup class="preview-mark">{html.escape(word["k"])}</sup>' if word.get("k") else "")
        + (" " if not word.get("glue") and i < len(main_words) - 1 else "")
        for i, word in enumerate(main_words)
    )
    streams = preview_layout.get("streams", {})

    def stream_text(ranges: list, stream_key: str) -> str:
        atoms = streams.get(stream_key, {}).get("atoms", [])
        return " ".join(
            atom["t"]
            for segment in ranges
            if segment.get("k") == stream_key
            for atom in atoms[segment["f"]:segment["t"]]
        )

    top_ranges = page.get("top", [])
    bottom_ranges = page.get("rs", [])
    labels = {
        "right_label": streams.get("R", {}).get("label", "—"),
        "left_label": streams.get("L", {}).get("label", "—"),
        "bottom_label": " · ".join(
            dict.fromkeys(streams.get(segment.get("k"), {}).get("label", "")
                          for segment in bottom_ranges)
        ) or "—",
    }
    return {
        "main": main,
        "right": stream_text(top_ranges, "R"),
        "left": stream_text(top_ranges, "L"),
        "bottom": " ".join(stream_text(bottom_ranges, key) for key in streams),
        **labels,
    }


def render_preview() -> None:
    if preview_area is None:
        return
    has_pages = bool(preview_pages)
    page_index = min(preview_page_index, len(preview_pages) - 1) if has_pages else 0
    if has_pages and (ROOT / "out" / "page.pdf").is_file():
        preview_area.clear()
        with preview_area:
            ui.html(
                f'<iframe title="PDF-oldal előnézete" '
                f'src="/preview.pdf?v={preview_pdf_version}#page={page_index + 1}&toolbar=0&navpanes=0" '
                'style="width:100%;height:80vh;border:1px solid #d6cec4"></iframe>'
            ).classes("w-full")
        if page_nav_label is not None:
            page_nav_label.text = f"{page_index + 1} / {len(preview_pages)} oldal"
            previous_page_button.set_enabled(page_index > 0)
            next_page_button.set_enabled(page_index < len(preview_pages) - 1)
        return
    page_content = page_preview_content(page_index) if has_pages else page_preview_content(0)
    main = page_content["main"]
    if not has_pages:
        main = html.escape(" ".join(main.split())[:850])
    columns = []
    side_line_height = 1.55 * float(settings["side_leading_em"]) / 0.45
    for slot in ("right", "left"):
        label = page_content[f"{slot}_label"]
        text = page_content[slot]
        columns.append(
            f'<section class="preview-column" style="font-size:clamp('
            f'{7 * float(settings["side_size_pt"]) / 8:g}px, '
            f'{1.1 * float(settings["side_size_pt"]) / 8:g}vw, '
            f'{11 * float(settings["side_size_pt"]) / 8:g}px);'
            f'line-height:{side_line_height:g}"><b>{html.escape(label)}</b>'
            f'<p>{html.escape(" ".join(text.split())[:520]) or "—"}</p></section>'
        )
    main_font = html.escape(f'"{settings["main_font"]}"', quote=True) if settings["main_font"] else "inherit"
    main_column = (
        f'<section class="preview-main" style="font-size:clamp('
        f'{9 * float(settings["main_size_pt"]) / 13:g}px, '
        f'{1.35 * float(settings["main_size_pt"]) / 13:g}vw, '
        f'{14 * float(settings["main_size_pt"]) / 13:g}px);'
        f'font-family:{main_font};'
        f'line-height:{1.8 * float(settings["main_leading_em"]) / 0.55:g}"><b>פנים · '
        f'{html.escape(source_label("main")) if "main" in sources else "ראשי"}</b>'
        f"<p>{main}</p></section>"
    )
    bottom_label = page_content["bottom_label"]
    bottom_text = page_content["bottom"]
    ratio = [max(float(settings[f"ratio_{name}"]), 0.1) for name in ("right", "main", "left")]
    page_w = max(float(settings["page_width"]), 1)
    page_h = max(float(settings["page_height"]), 1)
    padding_x = float(settings["margin_x"]) / page_w * 100
    padding_top = float(settings["margin_top"]) / page_h * 100
    padding_bottom = float(settings["margin_bottom"]) / page_h * 100
    font_family = html.escape(", ".join(f'"{name}"' for name in settings["fonts"]), quote=True)
    page_html = f"""
    <div class="preview-paper" style="aspect-ratio:{page_w:g}/{page_h:g};
      padding-left:{padding_x:g}%;padding-right:{padding_x:g}%;
      padding-top:{padding_top:g}cqh;padding-bottom:{padding_bottom:g}cqh;
      font-family:{font_family},serif">
      <div class="preview-header"><span>צורת הדף · {f'{page_index + 1} / {len(preview_pages)}' if has_pages else 'minta'}</span><span>{page_w:g} × {page_h:g} cm</span></div>
      <div class="preview-columns" style="grid-template-columns:{ratio[0]}fr {ratio[1]}fr {ratio[2]}fr">
        {columns[0]}{main_column}{columns[1]}
      </div>
      <div class="preview-bottom"><b>{html.escape(bottom_label)}</b>
        <p>{html.escape(" ".join(bottom_text.split())[:480]) or "—"}</p>
      </div>
      <div class="preview-footer">Főszöveg {settings['main_size_pt']:g} pt · kommentár
        {settings['side_size_pt']:g} pt · {settings['bottom_cols']} alsó hasáb ·
        {float(settings['max_stretch']) * 100:g}% nyújtási keret</div>
    </div>"""
    preview_area.clear()
    with preview_area:
        ui.html(page_html).classes("w-full")
    if page_nav_label is not None:
        count = len(preview_pages) if preview_pages else 1
        page_nav_label.text = f"{page_index + 1} / {count} oldal"
        previous_page_button.set_enabled(page_index > 0)
        next_page_button.set_enabled(page_index < count - 1)


def change_preview_page(direction: int) -> None:
    global preview_page_index
    if preview_pages:
        preview_page_index = max(
            0, min(preview_page_index + direction, len(preview_pages) - 1)
        )
        render_preview()


def generate_preview_layout() -> subprocess.CompletedProcess:
    output = []
    for script in ("pilot.py", "layout.py"):
        result = subprocess.run(
            [sys.executable, script, CONFIG_PATH.name],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        output.append(result.stdout)
        if result.stderr:
            output.append(result.stderr)
        if result.returncode:
            return subprocess.CompletedProcess(
                result.args, result.returncode, "".join(output), ""
            )
    return subprocess.CompletedProcess([], 0, "".join(output), "")


async def reflow_preview(revision: int) -> None:
    global preview_page_index
    async with pipeline_lock:
        if revision != preview_revision:
            return
        try:
            persist_config()
            result = await run.io_bound(generate_preview_layout)
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
            if revision == preview_revision:
                preview_status_label.text = f"Az előnézet újratördelése sikertelen: {error}"
                with preview_area:
                    ui.notify("Az új oldalbeosztás nem készült el.", type="negative", timeout=7000)
            return
        if revision != preview_revision:
            return
        if result.returncode:
            preview_status_label.text = "Az oldalbeosztás nem frissült; ellenőrizd a generálási naplót."
            build_log.text = result.stdout[-6000:]
            with preview_area:
                ui.notify("Az oldalbeosztás újraszámítása hibával leállt.", type="negative", timeout=7000)
            return
        build_log.text = result.stdout[-6000:]
        load_preview_pages()
        preview_page_index = 0
        render_preview()
        preview_status_label.text = (
            f"Előnézet frissült ({len(preview_pages)} oldal); PDF-hez indítsd el a generálást."
        )


async def debounce_preview_reflow(revision: int) -> None:
    try:
        await asyncio.sleep(0.8)
    except asyncio.CancelledError:
        return
    if revision != preview_revision:
        return
    task = asyncio.create_task(reflow_preview(revision))
    preview_worker_tasks.add(task)
    task.add_done_callback(preview_worker_tasks.discard)


def schedule_preview_reflow() -> None:
    global preview_revision, preview_debounce_task
    preview_revision += 1
    if preview_debounce_task and not preview_debounce_task.done():
        preview_debounce_task.cancel()
    preview_status_label.text = "Az oldalbeosztás újraszámítása folyamatban…"
    previous_page_button.set_enabled(False)
    next_page_button.set_enabled(False)
    if download_button is not None:
        download_button.set_visibility(False)
    preview_debounce_task = asyncio.create_task(debounce_preview_reflow(preview_revision))


def refresh_tablet_commentary_options() -> None:
    if tablet_commentary_control is None:
        return
    options = {
        key: source_label(key)
        for key in sources
        if key != "main"
    }
    selected = settings.get("tablet_commentary")
    if selected not in options:
        selected = next(
            (slot_values.get(slot) for slot in ("left", "right", "bottom")
             if slot_values.get(slot) in options),
            next(iter(options), None),
        )
        settings["tablet_commentary"] = selected
    tablet_commentary_control.options = options
    tablet_commentary_control.value = selected
    tablet_commentary_control.update()


def refresh_sources() -> None:
    source_area.clear()
    source_assignment_controls.clear()
    with source_area:
        for key, source in sources.items():
            with ui.card().classes("w-full bg-white"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-0"):
                        ui.label(ROLE_LABELS.get(key, "További kommentár · alsó sáv")).classes("text-xs text-gray-500")
                        ui.label(source_label(key)).classes("text-lg font-semibold")
                        if source.get("title") or source.get("section_ref"):
                            span = f"{source.get('from', '')}–{source.get('to', '')}" if source.get("from") else "teljes"
                            ui.label(f"{source.get('section_ref') or source['title']} · {span}").classes("text-sm")
                        ui.label(source.get("url", "")).classes("text-xs text-gray-500 break-all")
                        if key != "main":
                            assignment_label = ui.label().classes("text-xs text-amber-800")
                    with ui.row():
                        ui.button("Módosítás", icon="edit", on_click=lambda k=key: edit_source(k)).props(
                            "flat dense"
                        )
                        if key != "main":
                            place_button = ui.button(
                                "Elhelyezés szabad helyre", icon="add_location",
                                on_click=lambda k=key: place_source(k),
                            ).props("flat dense")
                            ui.button("Törlés", icon="delete", on_click=lambda k=key: delete_source(k)).props(
                                "flat dense color=negative"
                            )
                            source_assignment_controls[key] = (assignment_label, place_button)
    refresh_slot_options()
    refresh_source_assignments()
    refresh_tablet_commentary_options()
    render_preview()


def available_slot(key: str, slots: dict) -> Optional[str]:
    if key == "main" or key in slots.values():
        return None
    preferred = PREFERRED_SLOTS.get(key)
    if preferred and not slots.get(preferred):
        return preferred
    return next((slot for slot in SLOT_LABELS if not slots.get(slot)), None)


def refresh_source_assignments() -> None:
    for key, (label, button) in source_assignment_controls.items():
        if key not in ROLE_LABELS:
            label.text = "Elhelyezve: Alsó sáv"
            button.set_visibility(False)
            continue
        assigned = [SLOT_LABELS[slot] for slot, selected in slot_values.items()
                    if selected == key and slot in SLOT_LABELS]
        if assigned:
            label.text = "Elhelyezve: " + ", ".join(assigned)
        else:
            label.text = "Nincs elhelyezve – nem jelenik meg a PDF-ben."
        button.set_visibility(not assigned and available_slot(key, slot_values) is not None)


def place_source(key: str) -> Optional[str]:
    slot = available_slot(key, slot_values)
    if slot is None:
        ui.notify("Nincs szabad hasáb vagy alsó sáv; válassz helyet az oldalbeállításoknál.", type="warning")
        return None
    slot_controls[slot].value = key
    ui.notify(f"{source_label(key)} elhelyezve: {SLOT_LABELS[slot]}.", type="positive")
    return slot


def stack_matches_samples(stack_sources: dict) -> bool:
    return bool(stack_sources) and all(
        key in sample_sources and source.get("url") == sample_sources[key].get("url")
        for key, source in stack_sources.items()
    )


def render_stack_tabs() -> None:
    stack_area.clear()
    with stack_area:
        with ui.row().classes("w-full items-center gap-1"):
            with ui.tabs(value=active_stack, on_change=lambda e: switch_stack(e.value)).props(
                "dense"
            ):
                for name in stacks:
                    ui.tab(name)
            ui.button(icon="add", on_click=add_stack).props("flat dense round").tooltip(
                "Új forráskészlet"
            )
            if len(stacks) > 1:
                ui.button(icon="delete", on_click=delete_stack).props(
                    "flat dense round color=negative"
                ).tooltip("Aktuális készlet törlése")


def switch_stack(name: Optional[str]) -> None:
    if not name or name == active_stack or name not in stacks:
        return
    snapshot_stack()
    load_stack(name)


def load_stack(name: str) -> None:
    global sources, slot_values, previews, active_stack
    active_stack = name
    sources = copy.deepcopy(stacks[name].get("sources", {}))
    slot_values = {**{slot: "" for slot in SLOT_LABELS}, **copy.deepcopy(stacks[name].get("slots", {}))}
    previews = {}
    for slot, control in slot_controls.items():
        control.value = slot_values.get(slot, "")
    if sample_mode and not stack_matches_samples(sources):
        sample_switch.value = False
    refresh_sources()
    schedule_preview_reflow()


def add_stack() -> None:
    with ui.dialog() as dialog, ui.card():
        ui.label("Új forráskészlet").classes("text-xl font-bold")
        name_input = ui.input("Név (pl. Tóra, Talmud)").classes("w-full")

        def create() -> None:
            name = (name_input.value or "").strip()
            if not name or name in stacks:
                ui.notify("Adj meg egy új, egyedi nevet.", type="warning")
                return
            snapshot_stack()
            stacks[name] = {"sources": {}, "slots": {slot: "" for slot in SLOT_LABELS}}
            dialog.close()
            load_stack(name)
            render_stack_tabs()

        with ui.row().classes("w-full justify-end"):
            ui.button("Mégse", on_click=dialog.close).props("flat")
            ui.button("Létrehozás", on_click=create).props("color=primary")
    dialog.open()


def delete_stack() -> None:
    if len(stacks) < 2:
        return
    stacks.pop(active_stack, None)
    load_stack(next(iter(stacks)))
    render_stack_tabs()
    ui.notify("A készlet törölve. A véglegesítéshez mentsd a konfigurációt.", type="warning")


def delete_source(key: str) -> None:
    label = source_label(key)
    sources.pop(key, None)
    previews.pop(key, None)
    for slot, selected in list(slot_values.items()):
        if selected == key:
            slot_values[slot] = ""
    refresh_sources()
    ui.notify(f"{label} törölve. A véglegesítéshez mentsd a konfigurációt.", type="warning")
    schedule_preview_reflow()


def edit_shared_torah_range() -> None:
    snapshot = copy.deepcopy(sources)
    stack = active_stack
    try:
        main = snapshot["main"]
        ref = source_ref(main)
        if ref not in TORAH_BOOKS:
            raise ValueError("A közös szakaszválasztó csak a Tóra öt könyvéhez használható.")
    except (KeyError, ValueError) as error:
        ui.notify(f"Nem nyitható meg a közös szakaszválasztó: {error}", type="negative", timeout=7000)
        return

    shape_state = {"shape": None}
    start = main.get("from", "")
    end = main.get("to") or start
    with ui.dialog().props("persistent") as dialog, ui.card().classes("w-[min(90vw,600px)]"):
        ui.label("Közös tórai szakasz").classes("text-xl font-bold")
        ui.label(f"{ref}: a főszöveg és az összes kommentár ugyanazt a szakaszt kapja.")
        status = ui.label("A fejezetek és versek betöltése…").classes("text-xs text-gray-500")
        with ui.row().classes("w-full"):
            from_button = ui.button(f"Kezdet: {start or 'nincs'}").props("outline")
            to_button = ui.button(f"Vég: {end or 'nincs'}").props("outline")
        values = {"start": start, "end": end}

        def choose(which: str) -> None:
            def select(value: str) -> None:
                values[which] = value
                button = from_button if which == "start" else to_button
                button.text = f"{'Kezdet' if which == 'start' else 'Vég'}: {value}"
            open_section_picker(shape_state["shape"], select)

        from_button.on_click(lambda: choose("start"))
        to_button.on_click(lambda: choose("end"))
        from_button.disable()
        to_button.disable()

        async def apply_range() -> None:
            apply_button.disable()
            cancel_button.disable()
            status.text = "A kiválasztott szakaszok lekérése…"
            try:
                updated = shared_torah_sources(snapshot, values["start"], values["end"], shape_state["shape"])
                new_previews, missing = await run.io_bound(fetch_shared_torah_sources, updated)
                if active_stack != stack or sources != snapshot:
                    raise ValueError("A források időközben megváltoztak; nyisd meg újra a szakaszválasztót.")
                sources.clear()
                sources.update(updated)
                previews.clear()
                previews.update(new_previews)
                if sample_mode:
                    sample_switch.value = False
                refresh_sources()
                dialog.close()
                schedule_preview_reflow()
                if missing:
                    ui.notify("A közös szakasz frissült. Nincs kommentár ezekhez a versekhez: "
                              + ", ".join(missing), type="warning", timeout=10000)
                else:
                    ui.notify("A közös szakasz minden forráson frissült.", type="positive")
            except (requests.RequestException, OSError, ValueError, KeyError, TypeError, SystemExit) as error:
                status.text = f"A szakaszok nem módosultak: {error}"
                ui.notify("A közös szakasz nem alkalmazható; a részletek fent olvashatók.",
                          type="negative", timeout=7000)
            finally:
                apply_button.enable()
                cancel_button.enable()

        with ui.row().classes("w-full justify-end"):
            cancel_button = ui.button("Mégse", on_click=dialog.close).props("flat")
            apply_button = ui.button("Alkalmazás minden forrásra", on_click=apply_range)
            apply_button.disable()

        async def load_shape() -> None:
            try:
                shape = await run.io_bound(load_section_shape, ref, main.get("version", "hebrew"))
                if shape["names"] != ["Chapter", "Verse"] or shape["talmud"]:
                    raise ValueError("A főszöveg nem fejezetekre és versekre bontott Tóra.")
                shape_state["shape"] = shape
                status.text = "Válaszd ki a kezdő és a záró verset."
                from_button.enable()
                to_button.enable()
                apply_button.enable()
            except (requests.RequestException, OSError, ValueError, KeyError, TypeError) as error:
                status.text = f"A szakaszválasztó nem tölthető be: {error}"

        ui.timer(0.1, load_shape, once=True)
    dialog.open()


def edit_source(key: Optional[str] = None) -> None:
    existing = copy.deepcopy(sources.get(key, {})) if key else {}
    available = [role for role in ROLE_LABELS if role not in sources]
    with ui.dialog() as dialog, ui.card().classes("w-[min(92vw,640px)]"):
        ui.label("Forrás módosítása" if key else "Sefaria-szöveg hozzáadása").classes(
            "text-xl font-bold"
        )
        role = key
        if role is None:
            role_select = ui.select(
                {**{item: ROLE_LABELS[item] for item in available},
                 "additional": "További kommentár · alsó sáv"},
                label="Szerep",
                value=available[0] if available else "additional",
            ).classes("w-full")
        label_input = ui.input(
            "Megjelenített név",
            value=existing.get("label", ROLE_DEFAULTS.get(role or "main", {}).get("label", "")),
        ).classes("w-full")
        title_input = ui.select(
            list(dict.fromkeys([*filter(None, [existing.get("title")]), *sefaria_titles])),
            label="Mű címe (kezdj gépelni, pl. Genesis)",
            value=existing.get("title") or None,
            with_input=True,
            new_value_mode="add-unique",
            clearable=True,
        ).classes("w-full")
        shape_state = {"shape": None, "revision": 0, "index_revision": 0, "refs": None, "updating": False}
        section_select = ui.select(
            [], label="Műrész / könyv", clearable=True, with_input=True
        ).classes("w-full")
        section_select.set_visibility(False)
        with ui.row().classes("w-full items-center"):
            from_button = ui.button("Kezdet: teljes mű", icon="grid_view").props("outline")
            to_button = ui.button("Vég: nincs", icon="grid_view").props("outline")
            ui.button("Szakasz törlése", icon="clear", on_click=lambda: clear_range()).props("flat dense")
            ui.button("Szerkezet újratöltése", icon="refresh", on_click=lambda: refresh_index()).props("flat dense")
        shape_status = ui.label("Válassz művet a szakaszok betöltéséhez.").classes("text-xs text-gray-500")
        with ui.row().classes("w-full no-wrap"):
            from_input = ui.input("Szakasz kezdete", value=existing.get("from", "")).classes("flex-1")
            to_input = ui.input("Szakasz vége", value=existing.get("to", "")).classes("flex-1")
        from_input.set_visibility(False)
        to_input.set_visibility(False)

        def update_range_buttons() -> None:
            from_button.text = f"Kezdet: {from_input.value or 'teljes mű'}"
            to_button.text = f"Vég: {to_input.value or 'nincs'}"

        def clear_range() -> None:
            from_input.value = ""
            to_input.value = ""
            update_range_buttons()

        from_input.on_value_change(update_range_buttons)
        to_input.on_value_change(update_range_buttons)

        def choose_section(target) -> None:
            shape = shape_state["shape"]
            if not shape:
                ui.notify("A szakaszlista még nem érhető el.", type="warning")
                return
            def select(value: str) -> None:
                target.value = value
                update_range_buttons()
            open_section_picker(shape, select)

        from_button.on_click(lambda: choose_section(from_input))
        to_button.on_click(lambda: choose_section(to_input))
        url_input = ui.input(
            "Sefaria URL (ha nincs cím kiválasztva)", value=existing.get("url", "")
        ).classes("w-full")
        version_input = ui.input("Verzió", value=existing.get("version", "hebrew")).classes("w-full")

        async def refresh_shape(clear: bool = False) -> None:
            shape_state["revision"] += 1
            revision = shape_state["revision"]
            shape_state["shape"] = None
            if clear:
                clear_range()
            ref = section_select.value
            from_button.disable()
            to_button.disable()
            from_input.set_visibility(False)
            to_input.set_visibility(False)
            if not ref:
                shape_status.text = "Válaszd ki a mű megfelelő részét."
                return
            shape_status.text = "Szakaszok betöltése a Sefariáról…"
            try:
                shape = await asyncio.to_thread(
                    load_section_shape, ref, (version_input.value or "hebrew").strip()
                )
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                if revision != shape_state["revision"]:
                    return
                shape_status.text = f"A csempés választó nem érhető el: {error}. Kézi megadás:"
                from_input.set_visibility(True)
                to_input.set_visibility(True)
                return
            if revision != shape_state["revision"]:
                return
            shape_state["shape"] = shape
            deeper_range = any(
                len((value or "").replace(".", ":").split(":")) > 2
                for value in (from_input.value, to_input.value)
            )
            if deeper_range:
                shape_status.text = "A meglévő részletesebb hivatkozás kézzel szerkeszthető, vagy válassz csempét."
                from_input.set_visibility(True)
                to_input.set_visibility(True)
            else:
                shape_status.text = "Válaszd ki a szakasz elejét és végét; üresen a teljes mű marad."
            from_button.enable()
            to_button.enable()

        async def refresh_index(clear: bool = False) -> None:
            shape_state["index_revision"] += 1
            revision = shape_state["index_revision"]
            previous = (section_select.value or existing.get("section_ref")) if not clear else None
            shape_state["revision"] += 1
            shape_state["shape"] = None
            shape_state["refs"] = None
            from_button.disable()
            to_button.disable()
            from_input.set_visibility(False)
            to_input.set_visibility(False)
            section_select.set_visibility(False)
            shape_state["updating"] = True
            section_select.value = None
            shape_state["updating"] = False
            if clear:
                clear_range()
            title = (title_input.value or "").strip()
            if not title:
                shape_status.text = "Válassz művet a szakaszok betöltéséhez."
                return
            shape_status.text = "A mű szerkezetének betöltése a Sefariáról…"
            try:
                refs = await asyncio.to_thread(load_text_refs, title)
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                if revision == shape_state["index_revision"]:
                    shape_status.text = f"A mű szerkezete nem érhető el: {error}. Próbáld újra, vagy használj URL-t."
                return
            if revision != shape_state["index_revision"]:
                return
            shape_state["refs"] = refs
            selected = previous if previous in refs else next(
                (ref for ref in refs if ref.casefold() == title.casefold()), None
            )
            if selected is None and len(refs) == 1:
                selected = refs[0]
            shape_state["updating"] = True
            section_select.options = refs
            section_select.value = selected
            section_select.update()
            shape_state["updating"] = False
            section_select.set_visibility(len(refs) > 1)
            if selected:
                await refresh_shape()
            else:
                shape_status.text = "Válaszd ki a mű megfelelő részét."

        def section_changed() -> None:
            if not shape_state["updating"]:
                asyncio.create_task(refresh_shape(clear=True))

        title_input.on_value_change(lambda: refresh_index(clear=True))
        section_select.on_value_change(section_changed)
        version_input.on_value_change(lambda: refresh_shape())
        update_range_buttons()
        from_button.disable()
        to_button.disable()
        if title_input.value:
            ui.timer(0.1, refresh_index, once=True)
        corrections = None
        if role in (None, "rashi"):
            corrections = ui.checkbox(
                "Rási javított zárójelpárjainak használata",
                value=existing.get("corrections", True),
            )
        cut_input = None
        if role in (None, "vitry"):
            cut_input = ui.input(
                "Vitri vágási pont (elhagyható)", value=existing.get("cut_before", "")
            )
        with ui.row().classes("w-full justify-end"):
            ui.button("Mégse", on_click=dialog.close).props("flat")

            async def save_source() -> None:
                nonlocal role
                role = role or role_select.value
                if role == "additional":
                    role = extra_source_key(sources)
                try:
                    title = (title_input.value or "").strip()
                    if title:
                        ref = section_select.value
                        if not shape_state["refs"]:
                            raise ValueError("A mű indexe még nem érhető el; próbáld újra, vagy adj meg URL-t.")
                        if ref not in shape_state["refs"]:
                            raise ValueError("Válaszd ki a mű megfelelő részét.")
                        start = (from_input.value or "").strip()
                        end = (to_input.value or "").strip()
                        if end and not start:
                            raise ValueError("A szakasz végéhez kezdőpontot is válassz.")
                        if shape_state["shape"] and all(
                            len(value.replace(".", ":").split(":")) <= 2 for value in (start, end)
                        ):
                            validate_section_range(start, end, shape_state["shape"])
                        url = build_sefaria_url(ref, from_input.value or "", to_input.value or "")
                    else:
                        url = url_input.value or ""
                    url = validate_sefaria_url(url)
                    source = {
                        **ROLE_DEFAULTS.get(role, {}),
                        **existing,
                        "url": url,
                        "version": (version_input.value or "hebrew").strip(),
                    }
                    source.pop("file", None)
                    for field in ("title", "section_ref", "from", "to"):
                        source.pop(field, None)
                    if title:
                        source["title"] = title
                        if ref != title:
                            source["section_ref"] = ref
                        if (from_input.value or "").strip():
                            source["from"] = from_input.value.strip()
                            if (to_input.value or "").strip():
                                source["to"] = to_input.value.strip()
                    if label_input.value and label_input.value.strip():
                        source["label"] = label_input.value.strip()
                    elif role not in ROLE_LABELS:
                        source["label"] = title or unquote(urlparse(url).path.strip("/")).replace("_", " ")
                    else:
                        source.pop("label", None)
                    if role == "rashi":
                        source["corrections"] = corrections.value if corrections else True
                    if role == "vitry":
                        if cut_input and cut_input.value and cut_input.value.strip():
                            source["cut_before"] = cut_input.value.strip()
                        else:
                            source.pop("cut_before", None)
                    try:
                        text = await run.io_bound(fetch, source, ROOT / "cache")
                    except requests.HTTPError as error:
                        main_source = sources.get("main")
                        if role == "main" or not main_source or "file" in main_source:
                            raise
                        main_data = await run.io_bound(fetch_data, main_source, ROOT / "cache")
                        if main_data.get("primary_category") != "Tanakh":
                            raise error
                        data, missing = await run.io_bound(fetch_verse_commentary, source, main_data,
                                                           ROOT / "cache")
                        text = flatten(data["versions"][0]["text"])
                        if missing:
                            ui.notify("A kommentár nem tartalmaz szöveget a kiválasztott versekhez.",
                                      type="warning", timeout=7000)
                    sources[role] = source
                    previews[role] = clean(
                        text,
                        corrections=source.get("corrections", False),
                        preserve_cantillation=role == "main",
                    )
                    if sample_mode:
                        sample_switch.value = False
                    refresh_sources()
                    if key is None and role != "main" and role in ROLE_LABELS:
                        place_source(role)
                    dialog.close()
                    ui.notify("A Sefaria-szöveg lekérve; az oldalbeosztás újraszámolódik.", type="positive")
                    schedule_preview_reflow()
                except (
                    ValueError,
                    OSError,
                    KeyError,
                    requests.RequestException,
                    json.JSONDecodeError,
                    SystemExit,
                ) as error:
                    ui.notify(f"A forrás nem menthető: {error}", type="negative", timeout=7000)

            ui.button("Lekérés és hozzáadás", icon="download", on_click=save_source).props(
                "color=primary"
            )
    dialog.open()


def set_numeric(key: str, value) -> None:
    if value is not None:
        if key == "bottom_cols":
            value = int(value)
        settings[key] = value
        if key in {"page_width", "page_height"} and orientation_switch is not None:
            orientation_switch.value = settings["page_width"] > settings["page_height"]
            orientation_switch.update()
        render_preview()
        schedule_preview_reflow()


def set_orientation(is_landscape: bool) -> None:
    current_is_landscape = settings["page_width"] > settings["page_height"]
    if bool(is_landscape) != current_is_landscape:
        settings["page_width"], settings["page_height"] = (
            settings["page_height"],
            settings["page_width"],
        )
        for key in ("page_width", "page_height"):
            numeric_controls[key].value = settings[key]
            numeric_controls[key].update()
    render_preview()
    schedule_preview_reflow()


def set_layout_preset(preset: str | None) -> None:
    if preset is None:
        return
    for key, value in LAYOUT_PRESETS[preset].items():
        settings[key] = value
        control = numeric_controls.get(key)
        if control is None:
            control = layout_controls.get(key)
        if control is not None:
            control.value = value
            control.update()
    orientation_switch.value = settings["page_width"] > settings["page_height"]
    orientation_switch.update()
    render_preview()
    schedule_preview_reflow()
    preset_control.value = None
    preset_control.update()


def set_tablet_commentary(key: str | None) -> None:
    settings["tablet_commentary"] = key
    schedule_preview_reflow()


def set_option(key: str, value) -> None:
    if value is not None:
        settings["options"][key] = int(value)
        schedule_preview_reflow()


def set_fonts(value) -> None:
    if value:
        settings["fonts"] = list(value)
    render_preview()
    schedule_preview_reflow()


def set_main_font(value) -> None:
    settings["main_font"] = value
    render_preview()
    schedule_preview_reflow()


def set_slot(slot: str, value) -> None:
    slot_values[slot] = value or ""
    refresh_source_assignments()
    render_preview()
    schedule_preview_reflow()


def set_sample_mode(value: bool) -> None:
    global sample_mode
    sample_mode = value
    schedule_preview_reflow()


async def run_build_process() -> int:
    process = await asyncio.create_subprocess_exec(
        "bash",
        "build.sh",
        CONFIG_PATH.name,
        cwd=ROOT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    page_count = None

    async def show_output() -> int:
        nonlocal page_count
        async for raw_line in process.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            build_log.text = (build_log.text + line + "\n")[-6000:]
            build_log.update()
            if line.startswith("==> 1/2"):
                status_label.text = "1/2 · Adatok letöltése és illesztése…"
                status_label.update()
            elif line.startswith("==> 2/2"):
                status_label.text = "2/2 · Tördelés és PDF készítése…"
                status_label.update()
            elif line.startswith("==> Mérés és oldalbeosztás"):
                status_label.text = "Oldalméretezés és tördelés folyamatban…"
                status_label.update()
            elif line.startswith("==> PDF renderelése"):
                if page_count is None:
                    status_label.text = "Oldalbeosztás kész; a PDF renderelése folyamatban…"
                else:
                    status_label.text = (
                        f"Oldalbeosztás kész ({page_count} oldal); "
                        "a PDF renderelése folyamatban…"
                    )
                status_label.update()
            elif re.match(r"\s+\d+ oldal,", line):
                page_count = line.strip().split(maxsplit=1)[0]
                status_label.text = (
                    f"Oldalbeosztás kész ({page_count} oldal); a PDF renderelése folyamatban…"
                )
                status_label.update()
        return await process.wait()

    try:
        return await asyncio.wait_for(show_output(), timeout=3600)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise


async def save_and_build() -> None:
    global preview_page_index
    status_label.text = "PDF-generálás indítása…"
    status_label.update()
    build_log.text = ""
    build_log.update()
    build_progress.set_visibility(True)
    build_button.disable()
    try:
        async with pipeline_lock:
            try:
                persist_config()
            except (OSError, ValueError, TypeError) as error:
                ui.notify(f"A konfiguráció nem menthető: {error}", type="negative", timeout=7000)
                return
            build_revision = preview_revision
            returncode = await run_build_process()
            if returncode:
                status_label.text = "A PDF-generálás hibával leállt."
                status_label.update()
                ui.notify("A PDF nem készült el; a részletek a naplóban olvashatók.", type="negative")
            else:
                load_preview_pages()
                preview_page_index = 0
                render_preview()
                if build_revision == preview_revision:
                    status_label.text = f"Elkészült: out/page.pdf · konfiguráció: {CONFIG_PATH.name}"
                    preview_status_label.text = "Az előnézet és a PDF naprakész."
                    download_button.set_visibility(True)
                    ui.notify("A PDF elkészült.", type="positive")
                else:
                    status_label.text = "Azóta változtak a beállítások; az előnézet újratördelése folyamatban."
                    download_button.set_visibility(False)
    except asyncio.TimeoutError:
        status_label.text = "A PDF-generálás túllépte az 1 órás időkorlátot."
        status_label.update()
        ui.notify("A PDF-generálás időkorlátja lejárt.", type="negative")
    except OSError as error:
        status_label.text = f"A generálás nem indítható el: {error}"
        status_label.update()
        ui.notify("A PDF-generálás nem indítható el.", type="negative")
    finally:
        build_progress.set_visibility(False)
        build_button.enable()


app.add_static_file(local_file=ROOT / "out" / "page.pdf", url_path="/preview.pdf", strict=False, max_cache_age=0)
ui.colors(primary="#6d4c41", secondary="#8d6e63", accent="#c49a6c")
ui.add_head_html(
    """
    <style>
      body { background: #f4f1ed; }
      .preview-paper { background: #fffdf8; color: #25211e; border: 1px solid #d6cec4;
        box-shadow: 0 12px 30px #4433221a; display:flex; flex-direction:column;
        width:100%; max-width:640px; box-sizing:border-box; container-type:size;
        overflow:hidden; font-family:serif; }
      .preview-header, .preview-footer { display:flex; justify-content:space-between; color:#766c62;
        font: 11px sans-serif; border-bottom:1px solid #ded8d0; padding-bottom:7px; }
      .preview-columns { direction:rtl; display:grid; gap:3%; flex:1; padding:5% 0; overflow:hidden; }
      .preview-column, .preview-main { min-width:0; overflow:hidden; line-height:1.55; }
      .preview-main { line-height:1.8; text-align:justify; }
      .preview-column b, .preview-main b, .preview-bottom b { display:block; text-align:center;
        border-bottom:1px solid #ddd4c9; margin-bottom:5px; padding-bottom:3px; }
      .preview-column p, .preview-main p, .preview-bottom p { margin:0; }
      .preview-bottom { border-top:1px solid #c9bdae; padding:3% 0; max-height:24%; overflow:hidden;
        font-size:clamp(7px, 1vw, 10px); line-height:1.45; }
      .preview-footer { border:0; border-top:1px solid #ded8d0; padding:6px 0 0; }
      .break-all { overflow-wrap:anywhere; }
      .preview-panel .preview-restore { display: none; }
      .preview-panel.preview-maximized {
        position: fixed; inset: 0; z-index: 2000; width: 100vw; height: 100dvh;
        max-width: none; overflow: auto; display: flex; flex-direction: column;
      }
      .preview-panel.preview-maximized .preview-expand { display: none; }
      .preview-panel.preview-maximized .preview-restore { display: inline-flex; }
      .preview-panel.preview-maximized .preview-area { flex: 1; min-height: 120px; align-items: stretch; }
      .preview-panel.preview-maximized .preview-area > div { height: 100%; }
      .preview-panel.preview-maximized .preview-area iframe { height: 100% !important; }
      .preview-panel.preview-maximized .preview-paper { max-width: none; }
    </style>
    """
)

with ui.column().classes("w-full max-w-[1500px] mx-auto p-4 md:p-8 gap-5"):
    with ui.row().classes("w-full items-center justify-between"):
        with ui.column().classes("gap-0"):
            ui.label("צורת הדף · Tzurat HaDaf").classes("text-3xl font-bold text-stone-800")
            ui.label("Sefaria-alapú PDF · élő elrendezés-előnézet").classes("text-stone-600")
        ui.label("HE").classes("rounded-full bg-stone-200 px-3 py-1 text-sm font-bold")

    with ui.row().classes("w-full items-start"):
        with ui.column().classes("w-full lg:w-[430px] gap-4"):
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Szövegforrások").classes("text-xl font-bold")
                    ui.button("Új szöveg", icon="add", on_click=lambda: edit_source()).props("color=primary")
                ui.label("Egy főszöveg és több kommentár adható meg; a továbbiak az alsó sávba kerülnek.")
                stack_area = ui.column().classes("w-full")
                ui.button("Közös tórai szakasz", icon="format_list_numbered",
                          on_click=edit_shared_torah_range).props("outline")
                sample_switch = ui.switch(
                    "Helyi mintaszövegek használata (API nélkül)",
                    value=sample_mode,
                    on_change=lambda event: set_sample_mode(event.value),
                )
                source_area = ui.column().classes("w-full gap-2")

            with ui.card().classes("w-full"):
                ui.label("Oldal és tipográfia").classes("text-xl font-bold")
                preset_control = ui.select(
                    {
                        "print": "Nyomtatási nézet",
                        "tablet": "Tablet · fekvő, nagy betűk",
                    },
                    label="Előbeállítás alkalmazása",
                    value=None,
                ).classes("w-full").on_value_change(
                    lambda event: set_layout_preset(event.value)
                )
                orientation_switch = ui.switch(
                    "Fekvő oldalnézet",
                    value=settings["page_width"] > settings["page_height"],
                    on_change=lambda event: set_orientation(event.value),
                )
                with ui.grid(columns=2).classes("w-full"):
                    for key, (minimum, maximum, step, label) in NUMERIC_FIELDS.items():
                        value = settings[key]
                        control = ui.number(
                            label, value=value, min=minimum, max=maximum, step=step
                        ).classes("w-full").on_value_change(
                            lambda event, k=key: set_numeric(k, event.value)
                        )
                        numeric_controls[key] = control
                    for key, (minimum, maximum, step, label) in LAYOUT_FIELDS.items():
                        value = settings[key]
                        control = ui.number(
                            label, value=value, min=minimum, max=maximum, step=step
                        ).classes("w-full").on_value_change(
                            lambda event, k=key: set_numeric(k, event.value)
                        )
                        layout_controls[key] = control
                with ui.row().classes("w-full"):
                    for slot, label in SLOT_LABELS.items():
                        control = ui.select(
                            {"": "— nincs —", **{key: source_label(key) for key in sources
                                                  if key != "main" and key in ROLE_LABELS}},
                            label=label,
                            value=slot_values.get(slot, ""),
                        ).classes("flex-1").on_value_change(
                            lambda event, s=slot: set_slot(s, event.value)
                        )
                        slot_controls[slot] = control
                tablet_commentary_control = ui.select(
                    {
                        key: source_label(key)
                        for key in sources
                        if key != "main"
                    },
                    label="Tablet nézet kommentárja",
                    value=settings["tablet_commentary"],
                ).classes("w-full").on_value_change(
                    lambda event: set_tablet_commentary(event.value)
                )
                ui.label(
                    "Tablet nézetben csak ez a kommentár jelenik meg; külön oldalakon folytatódhat."
                ).classes("text-xs text-stone-500")
                ui.select(
                    MAIN_FONTS,
                    label="Főszöveg betűtípusa",
                    value=settings["main_font"],
                ).classes("w-full").props("clearable").on_value_change(
                    lambda event: set_main_font(event.value)
                )
                ui.label(
                    "A kiválasztott betűtípust telepíteni kell; üresen a közös betűcsaládok érvényesek."
                ).classes("text-xs text-stone-500")
                ui.select(
                    list(dict.fromkeys(LAYOUT_DEFAULTS["fonts"] + settings["fonts"])),
                    label="Kommentárok és alapértelmezett betűcsaládok",
                    value=settings["fonts"],
                    multiple=True,
                ).classes("w-full").on_value_change(
                    lambda event: set_fonts(event.value)
                )
                with ui.expansion("Illesztési paraméterek", icon="tune").classes("w-full"):
                    with ui.grid(columns=3).classes("w-full"):
                        for key, label, minimum, maximum, step in (
                            ("threshold", "Küszöb", 0, 100, 1),
                            ("lookahead", "Előrekeresés", 1, 500, 1),
                            ("lemma_max_words", "Lemma max. szavak", 1, 30, 1),
                        ):
                            ui.number(
                                label,
                                value=settings["options"].get(key),
                                min=minimum,
                                max=maximum,
                                step=step,
                            ).classes("w-full").on_value_change(
                                lambda event, k=key: set_option(k, event.value)
                            )
                with ui.row().classes("w-full"):
                    ui.button("Konfiguráció mentése", icon="save", on_click=lambda: save_config_action()).props(
                        "outline"
                    )

            with ui.card().classes("w-full"):
                ui.label("PDF-generálás").classes("text-xl font-bold")
                status_label = ui.label(f"Mentés: {CONFIG_PATH.name} · forrás: config.live.yaml")
                build_progress = ui.linear_progress(show_value=False).props(
                    "indeterminate"
                ).classes("w-full")
                build_progress.set_visibility(False)
                build_log = ui.label("").classes(
                    "w-full whitespace-pre-wrap break-all font-mono text-xs text-stone-700"
                )
                with ui.row():
                    build_button = ui.button("Mentés és PDF készítése", icon="picture_as_pdf", on_click=save_and_build)
                    download_button = ui.button(
                        "PDF letöltése",
                        icon="download",
                        on_click=lambda: ui.download.file(str(ROOT / "out" / "page.pdf")),
                    )
                    download_button.set_visibility((ROOT / "out" / "page.pdf").exists())

        with ui.column().classes("w-full flex-1 gap-3"):
            with ui.card().classes("w-full preview-panel"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Élő előnézet").classes("text-xl font-bold")
                    with ui.row().classes("items-center"):
                        ui.label("A beállítások módosításával azonnal frissül").classes("text-sm text-stone-500")
                        ui.button("Teljes ablak", icon="open_in_full").props("outline").classes(
                            "preview-expand"
                        ).on("click", js_handler="""(event) => {
                            const panel = event.currentTarget.closest('.preview-panel');
                            panel.classList.add('preview-maximized');
                            panel.querySelector('.preview-restore').focus();
                        }""")
                        ui.button("Visszaállítás", icon="close_fullscreen").props("outline").classes(
                            "preview-restore"
                        ).on("click", js_handler="""(event) => {
                            const panel = event.currentTarget.closest('.preview-panel');
                            panel.classList.remove('preview-maximized');
                            panel.querySelector('.preview-expand').focus();
                        }""")
                with ui.row().classes("w-full items-center justify-center"):
                    previous_page_button = ui.button(
                        "Előző oldal", icon="chevron_right", on_click=lambda: change_preview_page(-1)
                    ).props("outline")
                    page_nav_label = ui.label("1 / 1 oldal").classes("font-semibold")
                    next_page_button = ui.button(
                        "Következő oldal",
                        icon="chevron_left",
                        on_click=lambda: change_preview_page(1),
                    ).props("outline")
                preview_status_label = ui.label(
                    "Az oldalbeosztás a legutóbbi tördelésből származik."
                ).classes("text-xs text-stone-500")
                preview_area = ui.column().classes("w-full items-center preview-area")
                ui.label(
                    "A tördelést befolyásoló módosítások után az oldalbeosztás automatikusan újraszámolódik. "
                    "A PDF letöltéséhez indítsd el a teljes generálást."
                ).classes("text-xs text-stone-500")


async def _init_titles() -> None:
    sefaria_titles[:] = await asyncio.to_thread(load_sefaria_titles)


def save_config_action() -> None:
    try:
        persist_config()
    except (OSError, ValueError, TypeError) as error:
        ui.notify(f"A konfiguráció nem menthető: {error}", type="negative", timeout=7000)
        return
    status_label.text = f"Konfiguráció elmentve: {CONFIG_PATH.name}"
    ui.notify("A konfiguráció elmentve.", type="positive")


load_preview_pages()
render_stack_tabs()
refresh_sources()
app.on_startup(lambda: asyncio.create_task(_init_titles()))

if __name__ == "__main__":
    ui.run(title="Tzurat HaDaf", host="127.0.0.1", port=8080, reload=False, show=False)
