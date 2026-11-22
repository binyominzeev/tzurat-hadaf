# Cúrat HáDáf – automatikus daf-elrendezésű PDF héber forrásszövegekből

Héber szövegből (pl. szidur) és a hozzá tartozó kommentárokból **curát hádáf** (Vilna-daf jellegű) elrendezésű, többoldalas PDF-et generál: középen a főszöveg, körülötte a kommentárok, az oldalak pedig hézagmentesen kitöltöttek.

A jelenlegi **pilot**: *Siddur Ashkenaz – Birkot Kriát Smá, első brácha (Yotzer Or)* főszöveggel, három kommentárral:

| Hely az oldalon | Mű | Horgonyzás |
|---|---|---|
| Jobb oszlop | Abudraham | szó/kifejezés szintű (dibur hámatchil-szerű) |
| Bal oszlop | Siddur Rashi | egység szintű, a főszöveg haladásával arányosan folyik |
| Alsó sáv | Máchzor Vitri | szó szintű nusach-variánsok (diff) |

> **Állapot:** a pipeline végig működik a mintaszövegeken (`samples/`). Az **éles Sefaria-letöltés** (`config.live.yaml`) még nem lett kipróbálva. Az első éles futásnál az API-válasz szerkezetén lehet, hogy igazítani kell (lásd: *Hibaelhárítás*).

---

## Gyors kezdés

```bash
pip install -r requirements.txt              # Python 3.9+
# Typst >= 0.12 CLI: https://github.com/typst/typst  (vagy: pip install typst – ez a fallback)

./build.sh config.yaml        # mintaadatokból (samples/), hálózat nélkül
./build.sh                    # éles: Sefaria API (config.live.yaml)
python app.py                 # webes kezelőfelület: http://127.0.0.1:8080
```

Kimenet: `out/page.pdf`, valamint `out/matches.csv` (az illesztések ellenőrző listája).

### Webes kezelőfelület

A NiceGUI felület a főszöveg és a kommentárok Sefaria URL-jének felvételét,
módosítását és törlését, az álló/fekvő tájolás váltását, a lapméret és hasábok,
margók, betűméretek, térközök, alsó hasábok, valamint az illesztési küszöb
beállítását támogatja. A tájolásváltó felcseréli az oldal szélességét és magasságát.
A „Helyi mintaszövegek használata” kapcsolóval a `samples/` tartalma használható
az alapértelmezett forrásokhoz API-hozzáférés nélkül; a kapcsoló kikapcsolásával
a Sefaria URL-ek lépnek érvénybe. A kiválasztás a PDF-generálásra is vonatkozik.
A Sefaria hivatkozás mentésekor a felület lekéri a szöveget. A tördelést
befolyásoló változtatások után a felület automatikusan újraszámolja az
oldalhatárokat, és a tényleges PDF-oldalak között az „Előző oldal” és
„Következő oldal” gombokkal lehet lapozni. A hosszabb szövegek tördelése időigényes.
A frissített tördelési beállításokat az automatikus újraszámolás a
`config.ui.yaml` fájlba menti. A „Konfiguráció mentése” külön is használható.
A „Mentés és PDF készítése” ezt a konfigurációt
használja, és az elkészült PDF letölthető a felületről. Az előnézet tájékoztató
jellege miatt az újratördelés alatt még az előző PDF-oldalt mutatja.

Tanach-főszöveg és versenként szervezett kommentárok esetén a főszöveg és a
kommentárok az eredeti versszámokat mutatják. A kommentárokban a Sefaria által
félkövérrel jelölt kezdőszavak maradnak félkövérek, a kommentárok pedig
bekezdésenkénti sortörés nélkül folynak. A főszövegtartományon kívüli
kommentárversek kimaradnak, erről a generálás figyelmeztet.
Figyelmeztetést ad akkor is, ha a forrás egy kommentárban nem jelöl
félkövér kezdőszót; ilyen esetben azt nem találgatja.

Az új kommentár automatikusan szabad hasábba vagy az alsó sávba kerül, ha van
szabad hely. Az elhelyezetlen forrás nem szerepel a PDF-ben; ezt a felület jelzi,
és szabad hely esetén az „Elhelyezés szabad helyre” gombbal helyezhető el.
A hely az oldalbeállításoknál bármikor módosítható.
A három eredeti szerep mellett az „Új szöveg” ablakban további kommentárok is
felvehetők a „További kommentár · alsó sáv” szereppel. Ezek az alsó sávban,
külön folyamként jelennek meg, és szükség esetén következő oldalon folytatódnak.
Versenként szervezett Tanach-forrásoknál a megfelelő vershez igazodnak; más
főszövegeknél a szövegük a főszöveg haladásával arányosan oszlik el.

A forrásszerkesztőben a mű kiválasztása után a Sefaria szakaszszerkezete alapján
csempéken választható ki a kezdő és a záró fejezet és vers, külön a főszöveghez
és minden kommentárhoz. Összetett mű esetén előbb a műrész vagy könyv is
kiválasztandó a Sefaria indexe alapján (például Chizkuni → Genesis).
Üres szakasz esetén a teljes kiválasztott műrész kerül lekérésre.
Ha a szerkezet nem érhető el vagy nem támogatott, kézi szakaszmegadás használható;
ha az index sem tölthető be, a műválasztást törölve közvetlen Sefaria URL is megadható.

A „Közös tórai szakasz” gombbal a főszöveg és az aktuális készlet összes
kommentárja egyszerre állítható ugyanarra a kezdő és záró versre. A választó
a már kiválasztott tórai könyvön belül működik. Alkalmazás előtt ellenőrzi és
lekéri az összes forrást; hiba esetén egyiket sem módosítja. Ha valamelyik
kommentárhoz nincs szöveg a kiválasztott versekben, ezt külön jelzi.

Betűtípusok: a főszöveghez külön választható a Taamey Ashkenaz, Taamey Frank
CLM, Frank Ruehl CLM vagy SBL Hebrew. A választás nem változtatja meg a
kommentárok betűtípusát. Üres választásnál a korábbi közös betűcsaládlista
érvényes. A kiválasztott fontnak telepítve kell lennie, vagy a projekt `fonts/`
mappájába kell kerülnie. A Typst CLI ellenőrzi az elérhetőségét; a csak Python
Typst-csomagot használó futtatásnál ez nem ellenőrizhető, ezért figyelmeztetés
jelenik meg a naplóban. **A mérés és a renderelés ugyanazt a betűkészletet látja,
ezért az oldalbeosztás betűfüggő.**

A főszöveg megőrzi a forrásszövegben található táámimot. A tényleges jelek a
kiválasztott Sefaria-verziótól függenek; nem minden szöveg vagy verzió tartalmazza
őket. Megjelenítésükhöz megfelelő font is szükséges.

---

## Architektúra

```
Sefaria API / samples/*.txt
        │
        ▼
  pilot.py          letöltés, tisztítás, normalizálás, illesztés
        │           ├─ out/page.json      (főszöveg + illesztett kommentárok)
        │           └─ out/matches.csv    (Abudraham-illesztések, kézi javításhoz)
        ▼
  layout.py         page.json → out/layout.json (kommentár-atomok, geometria)
        │
        ├─► measure.typ   1. Typst-menet: oldalbeosztás kiszámítása
        │                 (measure + bisection) → <pages> metaadat
        │                 → out/pages.json
        ▼
  render.typ        2. Typst-menet: a pages.json kirajzolása → out/page.pdf
```

`lib.typ` a mérő és a renderelő **közös** kódja (méretek, stílusok, renderelő függvények). Minden, ami befolyásolja a szöveg magasságát, kizárólag itt lehet.

### Fájltérkép

| Fájl | Szerep |
|---|---|
| `build.sh` | egy parancs: `pilot.py` → `layout.py` |
| `config.yaml` | minta-konfig (a `file:` mezők miatt a `samples/` mappából dolgozik) |
| `config.live.yaml` | éles konfig (ugyanaz `file:` nélkül → Sefaria API) |
| `config.test.yaml`, `config.test2.yaml` | stressz-tesztek (hosszú Rási, nagyobb betű, kisebb oldal → több oldal) |
| `pilot.py` | letöltés, tisztítás, illesztés |
| `layout.py` | layout.json építése, Typst-menetek futtatása |
| `lib.typ`, `measure.typ`, `render.typ` | tördelőmotor és renderelő |
| `samples/` | kézzel bemásolt Sefaria-szövegek a hálózat nélküli teszthez |
| `out/`, `cache/` | generált (a `cache/` a nyers API-válaszokat őrzi; forrásváltáskor töröld) |

---

## Adatfolyam és sémák

### 1. `pilot.py` – forrás → `out/page.json`

Tisztítás (`clean`): HTML-címkék és lábjegyzetek törlése, a kommentárokban a ta'amim és a hozzájuk tartozó extra jelek (U+0591–U+05AF) eltávolítása; a főszövegben ezek és a nikud megmaradnak, a `|` jel törlődik. A Rashi-szövegnél a szerkesztői `(eredeti) [javított]` párokból a **javított** alak marad, a zárójeles hivatkozások (`(דברים ו' ז')`) érintetlenek. A nikudos Tetragrammaton cserélhető (`options.divine_name`).

Versenként strukturált Tanach-főszövegnél a program megőrzi a Sefaria
fejezet- és vershatárait, illetve a kommentárok `<b>`/`<strong>` jelöléseit.
Ilyenkor mindhárom kommentárhely ugyanígy működik: a szövegek a megfelelő
versekhez horgonyzódnak, nem az alábbi szidur-specifikus algoritmusokhoz.
Más könyvhöz tartozó vagy nem versenként strukturált kommentár esetén a
generálás hibát jelez.

Normalizálás (`key`): nikud le, írásjelek ki, szó végi betűk egységesítése, `י"י`/`ה'`/`יהוה` → `ה`, `אלק…` → `אלה…`, és a **váz-kulcs** (yod/vav nélkül), hogy a teljes/hiányos írásmód ne zavarjon.

**Abudraham-illesztés** (`align_abudraham`): a szöveg mondatokra (`.`/`:`) esik szét. Minden mondat *lemmája* az első szavak az első `על שם` / `עם שם` / `פסוק` / `כלומר` / `ר"ל` / `שנאמר` jelzésig (max. `lemma_max_words`). A lemmát a főszövegben **sorrendtartóan** keressük (az előző találattól előre, `lookahead` szóig), `rapidfuzz.fuzz.ratio` alapján. Küszöb (`threshold`, alap 75) alatt a mondat az előző jegyzethez fűződik („örökölt”). A `matches.csv` minden szegmensről ír: `ok` / `inherited`, pontszám, horgony.

Kézi javítás: `config.yaml` → `overrides: {abudraham: {<szegmens_index>: <főszöveg_szó_index>}}`, majd újrafuttatás.

**Máchzor Vitri** (`vitry_variants`): nem kommentár, hanem a mű saját imaszövege eltérő nusachsal. A főszöveggel `difflib.SequenceMatcher` készít szó szintű diffet (váz-kulcson). A rövidítések (`מ"ה`, `בא"י`) feloldódnak. A főszöveg végén túllógó rész a `vitry_tail`-be kerül. A `cut_before` az egységnél vág (alap: `"אהבת עולם"`).

`page.json` szerkezete:

```jsonc
{
  "unit": "yotzer_or",
  "main": [{"text": "בָּרוּךְ", "norm": "ברך", "glue": false}],   // glue: maqaf után nincs szóköz
  "notes": [{"src": "abudraham", "anchor_w": [0, 5], "lemma": "…", "text": "…", "quality": 0.97}],
  "unit_notes": [{"src": "siddur_rashi", "anchor_w": 0, "text": "…"}],
  "variants": [{"src": "machzor_vitry", "op": "replace|insert|delete",
                "anchor_w": 52, "main": ["…"], "vitry": ["…"]}],
  "vitry_tail": ["…"],
  "labels": {"abudraham": "אבודרהם", "rashi": "רש\"י", "vitry": "מחזור ויטרי"}
}
```

### 2. `layout.py` – `out/layout.json`

A kommentárok **atomokra** (szavakra) bontva folyamokba (stream) rendeződnek:
`R` (jobb oszlop), `L` (bal oszlop), `B` (alsó sáv), a további alsó
kommentárok pedig `B1`, `B2`, … jelű külön folyamokba.

```jsonc
{
  "geometry": {"page_w": 21, "page_h": 29.7, "margin_x": 1.4, "...": "..."},   // cm / pt
  "fonts": ["Frank Ruhl Libre", "..."],
  "labels": {"abudraham": "…"},
  "main":   [{"t": "szó", "glue": false, "k": "3,4"}],      // k: jegyzetszám-jelek a szónál
  "streams": {"R": {"label": "…", "atoms": [ATOM, "..."]}, "L": {...}, "B": {...}}
}
// ATOM: {"t": szó, "a": horgony (főszöveg-szóindex), "f": bekezdés első szava?,
//        "m": jegyzetszám (csak a bekezdés elején), "b": félkövér (lemma)?, "s": forrás-azonosító}
```

Az atomok horgony (`a`) szerint rendezettek. Az egységszintű Rashi-szöveg horgonyait `layout.py` **egyenletesen szétteríti** a főszöveg szavai közé, különben az egész az 1. oldalra kényszerülne.

### 3. `measure.typ` – `out/pages.json`

Oldalanként egy elem:

```jsonc
{ "a": 0, "b": 48,                 // a főszöveg [a, b) szavai kerülnek az oldalra
  "mode": "3|flow|none|tail",
  "T": 215.0,                      // a felső zóna magassága (pt)
  "extra": 1.8,                    // pluszsortávolság a főszövegben (pt), hogy T-t kitöltse
  "top": [{"k":"R","f":0,"t":58}, {"k":"L","f":0,"t":33}],   // oldalsó hasábok: atomtartományok
  "rs":  [{"k":"R","f":58,"t":97}],  // alsó sáv: atomtartományok (összefűzve)
  "ns":  [40, 38, 39],             // az alsó sáv hasábonkénti atomszáma
  "hb":  111.0, "slack": 0.2,      // alsó sáv magassága, maradék rés (pt)
  "cur": {"R": 97, "L": 33, "B": 1} }   // a folyamok kurzorai az oldal után
```

---

## A tördelőalgoritmus (oldalanként)

**Módok:** `3` = jobb oszlop | főszöveg | bal oszlop. `flow` = az egyik oldalsó folyam elfogyott, a másik folytatódik mindkét oldalsó hasábon (jobb → bal). `none` = mindkettő elfogyott, a főszöveg középre kerül. `tail` = a főszöveg elfogyott, a maradék kommentár teljes szélességű hasábokban folytatódik.

1. **Legtöbb főszöveg-szó**: bisection a `b` végindexen. Adott `b`-re: `M` = a főszöveg-részlet mért magassága. Az oldalsó hasábok `M` magasságig töltődnek szó szintű bisectionnel (`fill-col`, a hasábcímke magassága beleszámít). Az alsó sávba kerül, ami a `b`-ig horgonyzott, de még el nem helyezett kommentár. Ezt `bottom-split` osztja el kiegyensúlyozottan `bottom_cols` hasábra. Megfelel, ha `M + gap + hb ≤ Hplan`.
2. **Kitöltés**: a felső zóna magassága `T ∈ [M, M·(1+max_stretch)]` közt nő, amíg az oldal tele nem lesz (bisection).
3. **Főszöveg-sortávolság**: bisection `extra`-ra, hogy a főszöveg magassága `T` legyen.
4. **Túlcsordulás** (ha `b = a+1` sem fér el): az alsó sávba csak annyi kerül, amennyi elfér, a többi a következő oldalra csúszik.
5. Dokumentum vége: az utolsó oldal természetes módon nincs tele, és a maradék rés nem nyúlik szét a vonal körül (legfeljebb 2 sornyi).

### Fontos tervezési döntések és buktatók

- **A Typst `columns` nem balanszíroz** (auto magasságú blokkban a teljes régiót kitölti), ezért a hasábokat a motor kézzel tölti és osztja szét.
- A Typst blokkok között alapból 1,2 em távolság van. Ezt `set block(spacing: 0pt)` nullázza (`lib.typ` stílusfüggvényei és `render.typ`), különben a mérés és a renderelés eltér, és az alsó sáv kicsúszik.
- `Hplan = Hbody − 3pt` biztonsági tartalék a kerekítési eltérések ellen.
- A bisectionök felső korlátja 400 atom (hasábonként). Hosszabb oszlopoknál emelni kell.
- A megszakadó szöveg utolsó sora `linebreak(justify: true)`-val sorkizárt; a folytatás nem kap külön jelölést a hasábban.
- A mérés hosszabb szövegnél lassú (oldalszámmal és szöveghosszal nő): 3 oldal ≈ 1–3 mp, több tucat oldalnál percek lehetnek.

---

## Konfiguráció

`config.yaml` (részletek a fájlban kommentezve):

```yaml
unit: yotzer_or
options:   {threshold: 75, lookahead: 60, lemma_max_words: 6, divine_name: null}
main:      {url: <Sefaria-link>, version: hebrew, file: samples/main.txt}   # a `file` elsőbbséget élvez
abudraham: {url: …, label: 'אבודרהם', file: …}
rashi:     {url: …, label: 'רש"י', corrections: true, file: …}
vitry:     {url: …, label: 'מחזור ויטרי', cut_before: "אהבת עולם", file: …}
overrides: {abudraham: {}}
layout:                                    # minden mező elhagyható
  slots: {right: abudraham, left: rashi, bottom: vitry}
  page: {width_cm: 21.0, height_cm: 29.7, margin_x_cm: 1.4, margin_top_cm: 1.4, margin_bottom_cm: 1.7}
  ratio: [1.0, 1.5, 1.0]
  main_size_pt: 13
  side_size_pt: 8
  bottom_cols: 3
  max_stretch: 0.30
  # fonts: ["Frank Ruhl Libre", …]
  # main_font: "Taamey Frank CLM"  # csak a főszöveghez; elhagyva a fonts lista érvényes
```

A `url` mezőből a script a Sefaria-hivatkozást nyeri ki (URL-dekódolt útvonal), és a `https://www.sefaria.org/api/v3/texts/<ref>?version=<version>` végpontot hívja. A válaszok a `cache/` mappába kerülnek.

---

## Ellenőrzés (regressziós teszt)

```bash
python pilot.py config.yaml    # elvárt: main: 99 szó | abudraham: 33 szegmens, 7 örökölt | variáns: 2 | vitry-farok: 12 szó
python layout.py config.yaml   # elvárt: 1 oldal (az illesztési számok betűfüggetlenek)

python pilot.py config.test2.yaml && python layout.py config.test2.yaml
# elvárt: 3 oldal; az 1–2. oldal tele (maradék rés < 1 pt), a 3. a dokumentum vége
```

Az illesztési számok determinisztikusak. **Az oldalhatárok betűfüggők**: tartalék betűvel a hosszú teszt a főszöveget 0–48, 48–91, 91–99 szavakra osztotta, más betűvel ettől eltérhet.

## Hibaelhárítás

- **Üres vagy hibás letöltés**: a `cache/` mappában megvan a nyers API-válasz. A `fetch()` a `versions[0].text` mezőt használja (a Sefaria v3 szerkezete); ha a válasz más, ott kell igazítani. A `version` mező értéke lehet `hebrew` vagy `hebrew|<verziócím>`.
- **Sok „örökölt” Abudraham-szegmens**: nézd a `out/matches.csv`-t, szükség esetén `threshold` csökkentése vagy `overrides`.
- **A Typst `unknown font family` figyelmeztetése**: csak a betű hiányát jelzi, lásd *Gyors kezdés*.
- **Üres oldalak vagy az alsó sáv kicsúszik**: a mérés és a renderelés eltér. Ellenőrizd, hogy minden stílus a `lib.typ`-ben van-e, és hogy nincs-e kiegészítő blokk-távolság.

---

## Ismert korlátok és ötletek a folytatáshoz

- Az éles Sefaria-letöltés kipróbálatlan (lásd fent).
- Egyetlen **egységet** (egy imát) tördel. Több egység (az egész szidur vagy egy Mikráot Gedolot) láncolása, fejezetcímek, oldalfejlécek még hiányoznak.
- A jegyzetszámok a főszöveg szavain csak az Abudraham-pontokat jelölik. A Rási és a Vitri nem kap horgony-jelet a főszövegben.
- A Vitri-variánsok ritkák, ezért csak az alsó sávba illenek. Ha több dús kommentár lesz, a `slots` átrendezhető.
- A `none` mód (a főszöveg középre kerül) nincs tesztelve.
- A lemma-félkövérítés csak a megtalált ד"ה-szavakra vonatkozik.
- Nincs nikud-/ta'amim-kapcsoló: a nikud marad, a ta'amim ki.
- **Nem megoldott:** Báruch Seámár (nincs a Sefarián, OCR kellene), automatikus OCR-javítás, felhasználói felület a kézi korrekciókhoz.
- Teljesítmény: a bisectionök cache-elése, a mért magasságok memoizálása.

## Licenc és forrásjelzés

A Sefaria-szövegek licence **szövegenként eltér** (CC0, CC-BY, CC-BY-SA, vagy csak megjelenítésre). PDF-ben való közlés előtt a használt művek licencét tételesen ellenőrizd, és a forrást tüntesd fel. A kód licence még nincs megválasztva (javaslat: MIT).

## Megjegyzések gépi (AI-ügynök) használathoz

- A szent szöveg **tartalmát soha nem módosítjuk**, az automatikus lépések csak szűrnek, normalizálnak és illesztenek. Szövegjavítás csak emberi ellenőrzéssel.
- A magasságot befolyásoló kód kizárólag a `lib.typ`-ben lehet (lásd a buktatókat). A `measure.typ` és a `render.typ` ezt importálja.
- A mérő menet kimenete a `<pages>` című metaadat. A Python a `typst query measure.typ "<pages>" --field value --one` parancsot (vagy a `typst` Python-csomag `query` függvényét) használja.
- A `pilot.py` és a `layout.py` is a munkakönyvtárból dolgozik (`out/`, `cache/`, `fonts/`), ezért a repó gyökeréből kell őket futtatni.
