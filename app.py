#!/usr/bin/env python3
"""NiceGUI editor for the Sefaria daf-style PDF configuration."""

import asyncio
import copy
import html
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests
import yaml
from nicegui import app, run, ui

from pilot import clean, fetch


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
SLOT_LABELS = {"right": "Jobb hasáb", "left": "Bal hasáb", "bottom": "Alsó sáv"}


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
previews = sample_previews()
slot_values = copy.deepcopy(settings["slots"])
slot_controls = {}
numeric_controls = {}
source_area = None
preview_area = None
status_label = None
build_log = None
build_button = None
download_button = None
orientation_switch = None
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
    return sources.get(key, {}).get("label", ROLE_LABELS.get(key, key))


def make_config() -> dict:
    result = copy.deepcopy(config)
    for key in ROLE_LABELS:
        result.pop(key, None)
    for key, source in sources.items():
        result[key] = copy.deepcopy(source)
        result[key].pop("file", None)
        result[key]["url"] = validate_sefaria_url(result[key]["url"])
        result[key].setdefault("version", "hebrew")
        if sample_mode:
            sample = sample_sources.get(key, {})
            if source.get("url") != sample.get("url") or "file" not in sample:
                raise ValueError(f"Nincs minta a(z) {ROLE_LABELS[key]} kiválasztott URL-jéhez.")
            result[key]["file"] = sample["file"]

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
    result["ui"] = {**(config.get("ui") or {}), "sample_mode": sample_mode}
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
    options = {"": "— nincs —", **{key: source_label(key) for key in sources}}
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
        "bottom": stream_text(bottom_ranges, "R") + " " + stream_text(bottom_ranges, "L")
                  + " " + stream_text(bottom_ranges, "B"),
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
            f'<section class="preview-column" style="font-size:clamp(7px, '
            f'{1.1 * float(settings["side_size_pt"]) / 8:g}vw, 11px);'
            f'line-height:{side_line_height:g}"><b>{html.escape(label)}</b>'
            f'<p>{html.escape(" ".join(text.split())[:520]) or "—"}</p></section>'
        )
    main_column = (
        f'<section class="preview-main" style="font-size:clamp(9px, '
        f'{1.35 * float(settings["main_size_pt"]) / 13:g}vw, 14px);'
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


def refresh_sources() -> None:
    source_area.clear()
    with source_area:
        for key, source in sources.items():
            with ui.card().classes("w-full bg-white"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-0"):
                        ui.label(ROLE_LABELS[key]).classes("text-xs text-gray-500")
                        ui.label(source.get("label", ROLE_LABELS[key])).classes("text-lg font-semibold")
                        ui.label(source.get("url", "")).classes("text-xs text-gray-500 break-all")
                    with ui.row():
                        ui.button("Módosítás", icon="edit", on_click=lambda k=key: edit_source(k)).props(
                            "flat dense"
                        )
                        if key != "main":
                            ui.button("Törlés", icon="delete", on_click=lambda k=key: delete_source(k)).props(
                                "flat dense color=negative"
                            )
    refresh_slot_options()
    render_preview()


def delete_source(key: str) -> None:
    sources.pop(key, None)
    previews.pop(key, None)
    for slot, selected in list(slot_values.items()):
        if selected == key:
            slot_values[slot] = ""
    refresh_sources()
    ui.notify(f"{ROLE_LABELS[key]} törölve. A véglegesítéshez mentsd a konfigurációt.", type="warning")
    schedule_preview_reflow()


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
                {item: ROLE_LABELS[item] for item in available},
                label="Szerep",
                value=available[0] if available else None,
            ).classes("w-full")
        label_input = ui.input(
            "Megjelenített név",
            value=existing.get("label", ROLE_DEFAULTS.get(role or "main", {}).get("label", "")),
        ).classes("w-full")
        url_input = ui.input("Sefaria URL", value=existing.get("url", "")).classes("w-full")
        version_input = ui.input("Verzió", value=existing.get("version", "hebrew")).classes("w-full")
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
                try:
                    url = validate_sefaria_url(url_input.value or "")
                    source = {
                        **ROLE_DEFAULTS.get(role, {}),
                        **existing,
                        "url": url,
                        "version": (version_input.value or "hebrew").strip(),
                    }
                    source.pop("file", None)
                    if label_input.value and label_input.value.strip():
                        source["label"] = label_input.value.strip()
                    else:
                        source.pop("label", None)
                    if role == "rashi":
                        source["corrections"] = corrections.value if corrections else True
                    if role == "vitry":
                        if cut_input and cut_input.value and cut_input.value.strip():
                            source["cut_before"] = cut_input.value.strip()
                        else:
                            source.pop("cut_before", None)
                    text = await run.io_bound(fetch, source, ROOT / "cache")
                    sources[role] = source
                    previews[role] = clean(
                        text,
                        corrections=source.get("corrections", False),
                    )
                    if sample_mode:
                        sample_switch.value = False
                    refresh_sources()
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
    if not key and not available:
        ui.notify("Minden támogatott forrásszerep használatban van.", type="warning")
        return
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


def set_option(key: str, value) -> None:
    if value is not None:
        settings["options"][key] = int(value)
        schedule_preview_reflow()


def set_fonts(value) -> None:
    if value:
        settings["fonts"] = list(value)
    render_preview()
    schedule_preview_reflow()


def set_slot(slot: str, value) -> None:
    slot_values[slot] = value or ""
    render_preview()
    schedule_preview_reflow()


def set_sample_mode(value: bool) -> None:
    global sample_mode
    sample_mode = value
    schedule_preview_reflow()


async def save_and_build() -> None:
    global preview_page_index
    status_label.text = "PDF készül… a hosszú szövegeknél a tördelés eltarthat."
    build_log.text = ""
    build_button.disable()

    def build():
        return subprocess.run(
            ["bash", "build.sh", CONFIG_PATH.name],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )

    try:
        async with pipeline_lock:
            try:
                persist_config()
            except (OSError, ValueError, TypeError) as error:
                ui.notify(f"A konfiguráció nem menthető: {error}", type="negative", timeout=7000)
                return
            build_revision = preview_revision
            result = await run.io_bound(build)
            build_log.text = (result.stdout + ("\n" + result.stderr if result.stderr else ""))[-6000:]
            if result.returncode:
                status_label.text = "A PDF-generálás hibával leállt."
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
    except (subprocess.TimeoutExpired, OSError) as error:
        status_label.text = f"A generálás nem fejeződött be: {error}"
        ui.notify("A PDF-generálás hibával leállt.", type="negative")
    finally:
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
                ui.label("Szerepként egy-egy főszöveg és három kommentár adható meg.")
                sample_switch = ui.switch(
                    "Helyi mintaszövegek használata (API nélkül)",
                    value=sample_mode,
                    on_change=lambda event: set_sample_mode(event.value),
                )
                source_area = ui.column().classes("w-full gap-2")

            with ui.card().classes("w-full"):
                ui.label("Oldal és tipográfia").classes("text-xl font-bold")
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
                        ui.number(label, value=value, min=minimum, max=maximum, step=step).classes(
                            "w-full"
                        ).on_value_change(lambda event, k=key: set_numeric(k, event.value))
                with ui.row().classes("w-full"):
                    for slot, label in SLOT_LABELS.items():
                        control = ui.select(
                            {"": "— nincs —", **{key: source_label(key) for key in sources}},
                            label=label,
                            value=slot_values.get(slot, ""),
                        ).classes("flex-1").on_value_change(
                            lambda event, s=slot: set_slot(s, event.value)
                        )
                        slot_controls[slot] = control
                ui.select(
                    list(dict.fromkeys(LAYOUT_DEFAULTS["fonts"] + settings["fonts"])),
                    label="Betűcsaládok (elsőként megadott az elsődleges)",
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
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("Élő előnézet").classes("text-xl font-bold")
                    ui.label("A beállítások módosításával azonnal frissül").classes("text-sm text-stone-500")
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
                preview_area = ui.column().classes("w-full items-center")
                ui.label(
                    "A tördelést befolyásoló módosítások után az oldalbeosztás automatikusan újraszámolódik. "
                    "A PDF letöltéséhez indítsd el a teljes generálást."
                ).classes("text-xs text-stone-500")


def save_config_action() -> None:
    try:
        persist_config()
    except (OSError, ValueError, TypeError) as error:
        ui.notify(f"A konfiguráció nem menthető: {error}", type="negative", timeout=7000)
        return
    status_label.text = f"Konfiguráció elmentve: {CONFIG_PATH.name}"
    ui.notify("A konfiguráció elmentve.", type="positive")


load_preview_pages()
refresh_sources()

if __name__ == "__main__":
    ui.run(title="Tzurat HaDaf", host="127.0.0.1", port=8080, reload=False, show=False)
