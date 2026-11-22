// measure.typ – 1. menet: kiszámolja az oldalbeosztást és <pages> metaadatként kiírja.
#import "lib.typ": *

#let Hplan = Hbody - 3pt     // kis biztonsági tartalék
#let lineh = G.side_size * 1pt * (1 + G.side_leading)
#let atoms-of(k) = S.at(k).atoms
#let nstream(k) = S.at(k).atoms.len()
#let lmin(a, b) = if a < b { a } else { b }
#let stream-keys = ("R", "L") + cfg.bottom_streams

#let elig(k, b) = {
  let p = atoms-of(k).position(at => at.a >= b)
  if p == none { nstream(k) } else { p }
}

// legtöbb atom, ami még belefér egy cap magas, w széles oszlopba
#let fill-col(k, c, cap, w, end) = {
  let atoms = atoms-of(k)
  let lo = 0
  let hi = calc.min(400, calc.max(0, end - c))
  while lo < hi {
    let mid = calc.quo(lo + hi + 1, 2)
    if hgt(w, col-body(S.at(k).label, atoms.slice(c, c + mid), false)) <= cap { lo = mid } else { hi = mid - 1 }
  }
  lo
}

#let top-fill(mode, cur, T, b) = {
  if mode == "3" {
    let nr = fill-col("R", cur.R, T, w-right, elig("R", b))
    let nl = fill-col("L", cur.L, T, w-left, elig("L", b))
    ((k: "R", f: cur.R, t: cur.R + nr), (k: "L", f: cur.L, t: cur.L + nl))
  } else if mode == "flow" {
    let k = if cur.R < nstream("R") { "R" } else { "L" }
    let c = cur.at(k)
    let n1 = fill-col(k, c, T, w-right, elig(k, b))
    let n2 = fill-col(k, c + n1, T, w-left, elig(k, b))
    ((k: k, f: c, t: c + n1), (k: k, f: c + n1, t: c + n1 + n2))
  } else { () }
}

#let ranges-atoms(rs) = {
  let out = ()
  for r in rs { out += atoms-of(r.k).slice(r.f, r.t) }
  out
}

#let bottom-ranges(top, cur, b) = {
  let ends = cur
  for e in top { ends.insert(e.k, e.t) }
  let rs = ()
  for k in stream-keys {
    let s = ends.at(k)
    let e = elig(k, b)
    if e > s { rs.push((k: k, f: s, t: e)) }
  }
  rs
}

#let fill-b(atoms, c, cap) = {
  let lo = 0
  let hi = calc.min(400, atoms.len() - c)
  while lo < hi {
    let mid = calc.quo(lo + hi + 1, 2)
    if hgt(wcol-b, bottom-body(atoms.slice(c, c + mid), false)) <= cap { lo = mid } else { hi = mid - 1 }
  }
  lo
}

// az alsó sáv kiegyensúlyozott szétosztása nb hasábra: (ns: atomszámok, hb: magasság)
#let bottom-split(atoms) = {
  if atoms.len() == 0 { return (ns: (), hb: 0pt) }
  let h1 = hgt(wcol-b, bottom-body(atoms, false))
  let cap = h1 / nb + lineh
  let ns = ()
  for attempt in range(8) {
    ns = ()
    let c = 0
    for j in range(nb) {
      let n = fill-b(atoms, c, cap)
      ns.push(n)
      c += n
    }
    if c >= atoms.len() { break }
    cap += lineh * 0.6
  }
  let placed = ns.sum()
  if placed < atoms.len() { ns.at(nb - 1) = ns.at(nb - 1) + (atoms.len() - placed) }
  let hb = 0pt
  let c = 0
  for n in ns {
    let h = hgt(wcol-b, bottom-body(atoms.slice(c, c + n), false))
    if h > hb { hb = h }
    c += n
  }
  (ns: ns, hb: hb)
}

#let evaluate(mode, cur, b, T) = {
  let top = top-fill(mode, cur, T, b)
  let rs = bottom-ranges(top, cur, b)
  let bs = bottom-split(ranges-atoms(rs))
  let extra = if rs.len() > 0 { gap + bs.hb } else { 0pt }
  (top: top, rs: rs, bs: bs, total: T + extra)
}

#let wm-of(mode) = if mode == "none" { w-main-solo } else { w-main }
#let main-h(mode, a, b, extra) = hgt(wm-of(mode), render-main(MAIN.slice(a, b), extra, false))

#let advance(cur, top, rs) = {
  let c = cur
  for e in top { c.insert(e.k, e.t) }
  for r in rs { c.insert(r.k, r.t) }
  c
}

#let take-ranges(rs, n) = {
  let out = ()
  let left = n
  for r in rs {
    if left <= 0 { break }
    let tk = calc.min(r.t - r.f, left)
    out.push((k: r.k, f: r.f, t: r.f + tk))
    left -= tk
  }
  out
}

// legtöbb atom, ami cap magasságú alsó sávba fér
#let fit-bottom(atoms, cap) = {
  let lo = 0
  let hi = calc.min(300, atoms.len())
  while lo < hi {
    let mid = calc.quo(lo + hi + 1, 2)
    if bottom-split(atoms.slice(0, mid)).hb <= cap { lo = mid } else { hi = mid - 1 }
  }
  calc.max(lo, 1)
}

#let spec(a, b, mode, T, extra, top, rs, bs, slack, cur) = (
  a: a, b: b, mode: mode, T: T / 1pt, extra: extra / 1pt, top: top, rs: rs,
  ns: bs.ns, hb: bs.hb / 1pt, slack: slack / 1pt, cur: advance(cur, top, rs),
)

#let plan-tail(cur) = {
  let rs = ()
  for k in stream-keys { if cur.at(k) < nstream(k) { rs.push((k: k, f: cur.at(k), t: nstream(k))) } }
  let n = fit-bottom(ranges-atoms(rs), Hplan)
  let rs2 = take-ranges(rs, n)
  let bs = bottom-split(ranges-atoms(rs2))
  spec(MAIN.len(), MAIN.len(), "tail", 0pt, 0pt, (), rs2, bs, 0pt, cur)
}

#let plan-page(a, cur) = {
  let N = MAIN.len()
  if a >= N { return plan-tail(cur) }
  let mode = if cur.R < nstream("R") and cur.L < nstream("L") { "3" } else if cur.R < nstream("R") or cur.L < nstream("L") { "flow" } else { "none" }
  let feasible(b) = {
    let M = main-h(mode, a, b, 0pt)
    evaluate(mode, cur, b, M).total <= Hplan
  }
  // 1) legtöbb főszöveg-szó, ami még elfér az oldalon
  let lo = a
  let hi = N
  while lo < hi {
    let mid = calc.quo(lo + hi + 1, 2)
    if feasible(mid) { lo = mid } else { hi = mid - 1 }
  }
  let b = if lo == a { a + 1 } else { lo }
  let M = main-h(mode, a, b, 0pt)
  let ev = evaluate(mode, cur, b, M)

  if lo == a {
    // túlcsordulás: az alsó sávba csak annyi megy, amennyi elfér, a többi a következő oldalra
    let cap = Hplan - M - gap
    let n = fit-bottom(ranges-atoms(ev.rs), cap)
    let rs2 = take-ranges(ev.rs, n)
    return spec(a, b, mode, M, 0pt, ev.top, rs2, bottom-split(ranges-atoms(rs2)), 0pt, cur)
  }

  // 2) a főszöveg és az oldalsó hasábok magasságának kinyújtása, amíg az oldal pont tele nincs
  let slack0 = Hplan - ev.total
  let cap = G.max_stretch * M
  let tlo = M + lmin(slack0, cap)
  if evaluate(mode, cur, b, tlo).total > Hplan { tlo = M }
  let thi = M + cap
  if thi > tlo {
    for _ in range(7) {
      let mid = (tlo + thi) / 2
      if evaluate(mode, cur, b, mid).total <= Hplan { tlo = mid } else { thi = mid }
    }
  }
  let T = tlo
  let ev2 = evaluate(mode, cur, b, T)

  // 3) a főszöveg sortávolságának növelése úgy, hogy a magassága T legyen
  let e_lo = 0pt
  let e_hi = T - M
  if e_hi > 0.1pt {
    for _ in range(8) {
      let mid = (e_lo + e_hi) / 2
      if main-h(mode, a, b, mid) <= T { e_lo = mid } else { e_hi = mid }
    }
  }
  spec(a, b, mode, T, e_lo, ev2.top, ev2.rs, ev2.bs, calc.max(0pt, Hplan - ev2.total), cur)
}

#let rem(cur) = {
  let r = 0
  for k in stream-keys { r += nstream(k) - cur.at(k) }
  r
}

#context {
  let pages = ()
  let a = 0
  let cur = (R: 0, L: 0)
  for k in cfg.bottom_streams { cur.insert(k, 0) }
  while a < MAIN.len() or rem(cur) > 0 {
    let sp = plan-page(a, cur)
    assert(sp.b > a or sp.cur != cur, message: "A tördelés nem tud továbbhaladni.")
    pages.push(sp)
    a = sp.b
    cur = sp.cur
  }
  [#metadata(pages) <pages>]
}
