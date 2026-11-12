//! Área da interseção de pares de (multi)polígonos pelo iOverlay (MIT/Apache-2.0), em paralelo.
//!
//! Entrada no formato do shapely.to_ragged_array para MultiPolygon: coordenadas (n x 2) e três vetores de
//! deslocamento (anéis -> coordenadas, polígonos -> anéis, geometrias -> polígonos). Cada geometria vira a lista
//! de todos os seus anéis com a regra EvenOdd (buracos se resolvem sozinhos), como no teste motor/iovbench.
//! A área de cada forma do resultado é o contorno externo menos os buracos (fórmula do laço de Gauss).

use i_overlay::core::fill_rule::FillRule;
use i_overlay::core::overlay_rule::OverlayRule;
use i_overlay::float::single::SingleFloatOverlay;
use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1, PyReadonlyArray2};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;

type Contornos = Vec<Vec<[f64; 2]>>;

struct Geometrias<'a> {
    coords: ndarray::ArrayView2<'a, f64>,
    aneis: &'a [i64],
    poligonos: &'a [i64],
    geoms: &'a [i64],
}

impl Geometrias<'_> {
    fn contornos(&self, g: usize) -> Contornos {
        let mut out = Vec::new();
        for p in self.geoms[g] as usize..self.geoms[g + 1] as usize {
            for r in self.poligonos[p] as usize..self.poligonos[p + 1] as usize {
                let (i0, i1) = (self.aneis[r] as usize, self.aneis[r + 1] as usize);
                if i1 <= i0 + 1 {
                    continue;
                }
                // o anel vem fechado (último ponto = primeiro); o iOverlay quer aberto
                let anel: Vec<[f64; 2]> = (i0..i1 - 1).map(|k| [self.coords[[k, 0]], self.coords[[k, 1]]]).collect();
                if anel.len() >= 3 {
                    out.push(anel);
                }
            }
        }
        out
    }

    fn n(&self) -> usize {
        self.geoms.len().saturating_sub(1)
    }
}

fn area_anel(r: &[[f64; 2]]) -> f64 {
    let n = r.len();
    let mut s = 0.0;
    for i in 0..n {
        let (a, b) = (r[i], r[(i + 1) % n]);
        s += a[0] * b[1] - b[0] * a[1];
    }
    (s / 2.0).abs()
}

fn area_intersecao(a: &Contornos, b: &Contornos) -> f64 {
    if a.is_empty() || b.is_empty() {
        return 0.0;
    }
    let res = a.overlay(b, OverlayRule::Intersect, FillRule::EvenOdd);
    let mut area = 0.0;
    for forma in &res {
        for (i, c) in forma.iter().enumerate() {
            let x = area_anel(c);
            if i == 0 { area += x } else { area -= x }
        }
    }
    area
}

/// Área (unidade das coordenadas ao quadrado) de cada par (ia[k], ib[k]).
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn area_pares<'py>(
    py: Python<'py>,
    coords_a: PyReadonlyArray2<'py, f64>,
    aneis_a: PyReadonlyArray1<'py, i64>,
    poligonos_a: PyReadonlyArray1<'py, i64>,
    geoms_a: PyReadonlyArray1<'py, i64>,
    coords_b: PyReadonlyArray2<'py, f64>,
    aneis_b: PyReadonlyArray1<'py, i64>,
    poligonos_b: PyReadonlyArray1<'py, i64>,
    geoms_b: PyReadonlyArray1<'py, i64>,
    ia: PyReadonlyArray1<'py, i64>,
    ib: PyReadonlyArray1<'py, i64>,
) -> PyResult<Bound<'py, PyArray1<f64>>> {
    let ga = Geometrias {
        coords: coords_a.as_array(),
        aneis: aneis_a.as_slice()?,
        poligonos: poligonos_a.as_slice()?,
        geoms: geoms_a.as_slice()?,
    };
    let gb = Geometrias {
        coords: coords_b.as_array(),
        aneis: aneis_b.as_slice()?,
        poligonos: poligonos_b.as_slice()?,
        geoms: geoms_b.as_slice()?,
    };
    let (ia, ib) = (ia.as_slice()?, ib.as_slice()?);
    if ia.len() != ib.len() {
        return Err(PyValueError::new_err("ia e ib com tamanhos diferentes"));
    }
    if ia.iter().any(|&i| i < 0 || i as usize >= ga.n()) || ib.iter().any(|&i| i < 0 || i as usize >= gb.n()) {
        return Err(PyValueError::new_err("índice de par fora das geometrias"));
    }
    // cada geometria é convertida uma vez só (um imóvel aparece em muitos pares)
    let ca: Vec<Contornos> = (0..ga.n()).into_par_iter().map(|g| ga.contornos(g)).collect();
    let cb: Vec<Contornos> = (0..gb.n()).into_par_iter().map(|g| gb.contornos(g)).collect();
    let areas: Vec<f64> = py.detach(|| {
        ia.par_iter().zip(ib.par_iter()).map(|(&i, &j)| area_intersecao(&ca[i as usize], &cb[j as usize])).collect()
    });
    Ok(areas.into_pyarray(py))
}

#[pymodule]
fn raiz_iov(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(area_pares, m)?)?;
    Ok(())
}
