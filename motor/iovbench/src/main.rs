use i_overlay::core::fill_rule::FillRule;
use i_overlay::core::overlay_rule::OverlayRule;
use i_overlay::float::single::SingleFloatOverlay;
use std::time::Instant;

fn ring_area(r: &Vec<[f64; 2]>) -> f64 {
    let n = r.len(); let mut s = 0.0;
    for i in 0..n { let a = r[i]; let b = r[(i + 1) % n]; s += a[0] * b[1] - b[0] * a[1]; }
    s / 2.0
}

fn main() {
    // entrada: [[contornos_a, contornos_b], ...]; contornos = lista de anéis [[x,y],...] (EvenOdd)
    let txt = std::fs::read_to_string(std::env::args().nth(1).unwrap()).unwrap();
    let pares: Vec<(Vec<Vec<[f64; 2]>>, Vec<Vec<[f64; 2]>>)> = serde_json::from_str(&txt).unwrap();
    let t0 = Instant::now();
    let mut out = Vec::with_capacity(pares.len());
    for (a, b) in &pares {
        let res = a.overlay(b, OverlayRule::Intersect, FillRule::EvenOdd);
        let mut area = 0.0;
        for shape in &res { for (i, c) in shape.iter().enumerate() {
            let x = ring_area(c).abs(); if i == 0 { area += x } else { area -= x } } }
        out.push(area);
    }
    let dt = t0.elapsed().as_secs_f64();
    eprintln!("iOverlay: {} pares em {:.3} s", pares.len(), dt);
    println!("{}", serde_json::to_string(&out).unwrap());
}
