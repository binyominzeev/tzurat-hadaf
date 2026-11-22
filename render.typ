// render.typ – 2. menet: a mért oldalbeosztás (out/pages.json) renderelése.
#import "lib.typ": *
#let pages = json("out/pages.json")

#set text(lang: "he", font: cfg.fonts)
#set block(spacing: 0pt)
#set page(
  width: G.page_w * 1cm, height: G.page_h * 1cm,
  margin: (x: G.margin_x * 1cm, top: G.margin_top * 1cm, bottom: G.margin_bottom * 1cm),
  footer: context align(center, text(size: 9pt, fill: rgb("#666"), counter(page).display())),
)

#let sl(e) = S.at(e.k).atoms.slice(e.f, e.t)
#let cont-of(e) = e.t < S.at(e.k).atoms.len() and not S.at(e.k).atoms.at(e.t).f

#let render-page(p) = {
  let T = p.T * 1pt
  if p.mode == "tablet-main" {
    block(width: 100%, height: T,
      render-main(MAIN.slice(p.a, p.b), p.extra * 1pt, p.b < MAIN.len()))
  } else if p.mode == "tablet-comment" {
    let e = p.top.at(0)
    block(width: 100%, height: Hbody, clip: true,
      col-body(S.at(e.k).label, sl(e), cont-of(e)))
  } else if p.mode == "3" or p.mode == "flow" {
    let col(e) = block(width: 100%, height: T, clip: true, col-body(S.at(e.k).label, sl(e), cont-of(e)))
    block(width: 100%, height: T, grid(
      columns: (w-right, w-main, w-left), column-gutter: gut,
      col(p.top.at(0)),
      block(width: 100%, height: T, render-main(MAIN.slice(p.a, p.b), p.extra * 1pt, p.b < MAIN.len())),
      col(p.top.at(1)),
    ))
  } else if p.mode == "none" {
    block(width: 100%, height: T, align(center, block(width: w-main-solo, render-main(MAIN.slice(p.a, p.b), p.extra * 1pt, p.b < MAIN.len()))))
  }
  if p.rs.len() > 0 {
    let all = ()
    for r in p.rs { all += S.at(r.k).atoms.slice(r.f, r.t) }
    if p.mode != "tail" {
      // a kis maradék rést szétosztjuk; a nagy rés (dokumentum vége) nem nyúlik szét
      let extra = calc.min(p.slack, 2 * G.side_size * (1 + G.side_leading)) * 1pt
      v(gap / 2 + extra / 2)
      line(length: 100%, stroke: 0.5pt)
      v(gap / 2 + extra / 2)
    }
    let cells = ()
    let c = 0
    for n in p.ns {
      let chunk = all.slice(c, c + n)
      let nxt = c + n
      let cont = nxt < all.len() and not all.at(nxt).f
      cells.push(block(width: 100%, height: p.hb * 1pt, clip: true, bottom-body(chunk, cont)))
      c += n
    }
    grid(columns: (wcol-b,) * nb, column-gutter: gut, ..cells)
  }
}

#for (i, p) in pages.enumerate() {
  if i > 0 { pagebreak() }
  render-page(p)
}
