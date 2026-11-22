// lib.typ – közös függvények a mérő (measure.typ) és a renderelő (render.typ) számára.
// Minden stílus ITT van, hogy a mérés és a végső renderelés pontosan ugyanazt rakja ki.
#let cfg = json("out/layout.json")
#let G = cfg.geometry
#let S = cfg.streams
#let MAIN = cfg.main

#let Wbody = (G.page_w - 2 * G.margin_x) * 1cm
#let Hbody = (G.page_h - G.margin_top - G.margin_bottom) * 1cm
#let gut = G.gutter * 1pt
#let gap = G.gap * 1pt
#let nb = G.bottom_cols
#let unit-w = (Wbody - 2 * gut) / G.ratio.sum()
#let w-right = unit-w * G.ratio.at(0)
#let w-main = unit-w * G.ratio.at(1)
#let w-left = unit-w * G.ratio.at(2)
#let w-main-solo = Wbody * 0.72
#let wcol-b = (Wbody - (nb - 1) * gut) / nb
#let mark-color = rgb("#a02020")

#let main-style(lead, body) = {
  set text(lang: "he", font: if cfg.main_font == none { cfg.fonts } else { (cfg.main_font,) }, size: G.main_size * 1pt)
  set par(justify: true, leading: lead, spacing: 0pt)
  set block(spacing: 0pt)
  body
}
#let side-style(body) = {
  set text(lang: "he", font: cfg.fonts, size: G.side_size * 1pt)
  set par(justify: true, leading: G.side_leading * 1em, spacing: 0.5em)
  set block(spacing: 0pt)
  body
}

// főszöveg-részlet; extra = pluszsortávolság (a magasság kitöltéséhez)
#let render-main(words, extra, cont) = main-style(G.main_leading * 1em + extra, {
  for (i, w) in words.enumerate() {
    if w.v != "" { text(fill: mark-color, weight: "bold", size: 0.7em)[#w.v ] }
    w.t
    if w.k != "" { super(text(size: 0.55em, fill: mark-color, weight: "bold", w.k)) }
    if not w.glue and i < words.len() - 1 { [ ] }
  }
  if cont { linebreak(justify: true) }
})

// kommentár-atomok bekezdésekké; labels = true: forráscímke a váltásoknál (alsó sáv)
#let render-atoms(atoms, cont, labels) = {
  let items = ()
  let cur = none
  let prev = none
  for at in atoms {
    if cur == none or (labels and at.s != prev) {
      if cur != none { items.push(cur.join([ ])) }
      if labels and at.s != prev {
        items.push(block(sticky: true, below: 0.35em, text(weight: "bold", fill: rgb("#555"), size: 0.95em)[#cfg.labels.at(at.s)]))
        prev = at.s
      }
      cur = ()
    }
    if at.m != "" { cur.push(text(fill: mark-color, weight: "bold")[#at.m]) }
    cur.push(if at.b { strong(at.t) } else { at.t })
  }
  if cur != none { items.push(cur.join([ ])) }
  items.join(parbreak())
  if cont { linebreak(justify: true) }
}

#let col-label(t) = {
  set text(size: 9.5pt, weight: "bold", fill: rgb("#333"))
  align(center, t)
  v(1pt)
  line(length: 100%, stroke: 0.5pt)
  v(4pt)
}
#let col-body(label, atoms, cont) = side-style({
  col-label(label)
  render-atoms(atoms, cont, false)
})
#let bottom-body(atoms, cont) = side-style(render-atoms(atoms, cont, true))

#let hgt(w, body) = measure(block(width: w, body)).height
