import { AttributionControl, LngLatBounds, Map as MapaGL, NavigationControl, ScaleControl } from "maplibre-gl"
import "maplibre-gl/dist/maplibre-gl.css"
import { useEffect, useRef, useState } from "react"
import { COR, MAPA } from "../../../compartilhado/cores"
import type { FichaTerraDados, SateliteTerra, VisualTerra } from "../../../compartilhado/prospeccao"
import { fonte } from "../dados"
import { dataTerra, prospeccao } from "../prospeccao"
import { estiloBase, imagemHachura, prepararMapLibre } from "./estilo"
import "./ficha-visual.css"

type Foto = { meta: Extract<SateliteTerra, { disponivel: true }>; url: string }

/** Recebe só o recorte liberado para esta sessão; nunca busca a geometria em arquivos abertos. */
export function MapaFichaTerra({ ficha }: { ficha: FichaTerraDados }) {
  const caixa = useRef<HTMLDivElement>(null)
  const [visual, setVisual] = useState<VisualTerra | null>(null)
  const [base, setBase] = useState<string | null>(null)
  const [foto, setFoto] = useState<Foto | null>(null)
  const [avisoFoto, setAvisoFoto] = useState("Consultando a cena Sentinel-2 do imóvel.")
  const [erro, setErro] = useState<string | null>(null)
  const [mostrarFoto, setMostrarFoto] = useState(true)
  const [hachura, setHachura] = useState(true)
  useEffect(() => {
    const abortar = new AbortController()
    let imagem: string | null = null
    setVisual(null); setFoto(null); setBase(null); setErro(null)
    setAvisoFoto("Consultando a cena Sentinel-2 do imóvel.")
    void fonte.geo.base(String(ficha.cod_ibge ?? "")).then(async (regional) => regional ?? (await fonte.geo.brasil()).base)
      .then((b) => { if (!abortar.signal.aborted) setBase(b) }).catch(() => {})
    void prospeccao.visual(ficha.codigo_car, abortar.signal).then(async (dado) => {
      if (abortar.signal.aborted) return
      setVisual(dado)
      if (!dado.imovel?.features.length) { setAvisoFoto("A imagem depende do limite do imóvel."); return }
      try {
        const meta = await prospeccao.satelite(ficha.codigo_car, abortar.signal)
        if (!meta.disponivel) { if (!abortar.signal.aborted) setAvisoFoto(meta.aviso); return }
        const blob = await prospeccao.imagemSatelite(ficha.codigo_car, abortar.signal)
        if (abortar.signal.aborted) return
        imagem = URL.createObjectURL(blob)
        setFoto({ meta, url: imagem })
        setAvisoFoto("")
      } catch {
        if (!abortar.signal.aborted) setAvisoFoto("Não foi possível carregar o Sentinel-2 agora. O limite e as áreas medidas continuam no mapa.")
      }
    }, () => { if (!abortar.signal.aborted) setErro("Não foi possível carregar o desenho deste imóvel. Reabra a ficha para tentar novamente.") })
    return () => { abortar.abort(); if (imagem) URL.revokeObjectURL(imagem) }
  }, [ficha.codigo_car, ficha.cod_ibge])

  useEffect(() => {
    if (!caixa.current || !visual?.imovel?.features.length) return
    prepararMapLibre()
    const bounds = new LngLatBounds()
    const pontos = (c: unknown): void => {
      if (!Array.isArray(c)) return
      if (typeof c[0] === "number" && typeof c[1] === "number") bounds.extend(c as [number, number])
      else c.forEach(pontos)
    }
    visual.imovel.features.forEach((f) => pontos(f.geometry.coordinates))
    if (bounds.isEmpty()) return
    const satelite = mostrarFoto ? foto : null
    const mapa = new MapaGL({ container: caixa.current, style: estiloBase(base), bounds,
      fitBoundsOptions: { padding: 40, maxZoom: 16 }, attributionControl: false, cooperativeGestures: true,
      locale: { "NavigationControl.ZoomIn": "Aproximar", "NavigationControl.ZoomOut": "Afastar", "AttributionControl.ToggleAttribution": "Mostrar fontes do mapa" },
      dragRotate: false, pitchWithRotate: false, pixelRatio: Math.min(devicePixelRatio || 1, 2) })
    mapa.on("resize", () => mapa.fitBounds(bounds, { padding: 40, maxZoom: 16, duration: 0 }))
    mapa.addControl(new AttributionControl({ compact: false, customAttribution: satelite?.meta.credito }))
    mapa.addControl(new NavigationControl({ showCompass: false }))
    mapa.addControl(new ScaleControl({ unit: "metric" }))
    if (import.meta.env.DEV || import.meta.env.VITE_RAIZ_TESTE_MAPA === "1") Object.assign(caixa.current, { __mapa: mapa })
    mapa.once("load", () => {
      if (satelite) {
        const [oeste, sul, leste, norte] = satelite.meta.caixa
        mapa.addSource("sentinel", { type: "image", url: satelite.url, coordinates: [[oeste, norte], [leste, norte], [leste, sul], [oeste, sul]] })
        mapa.addLayer({ id: "sentinel", type: "raster", source: "sentinel", paint: { "raster-saturation": -0.15, "raster-contrast": 0.05 } })
      }
      mapa.addSource("imovel", { type: "geojson", data: visual.imovel as never })
      mapa.addSource("mascara", { type: "geojson", data: visual.mascara as never })
      mapa.addSource("camadas", { type: "geojson", data: visual.camadas as never })
      mapa.addLayer({ id: "fora-do-imovel", type: "fill", source: "mascara", paint: { "fill-color": satelite ? MAPA.mascaraSatelite : MAPA.mascaraClara, "fill-opacity": satelite ? 0.45 : 0.6 } })
      mapa.addLayer({ id: "mata-em-pe", type: "fill", source: "camadas", filter: ["==", ["get", "camada"], "mata_em_pe"], paint: { "fill-color": MAPA.uso.floresta, "fill-opacity": satelite ? 0.3 : 0.8 } })
      mapa.addImage("hachura-restaurar", imagemHachura(satelite ? MAPA.hachuraSatelite : MAPA.hachuraClara), { pixelRatio: 2 })
      mapa.addLayer({ id: "pode-voltar", type: "fill", source: "camadas", filter: ["==", ["get", "camada"], "pode_voltar"], layout: { visibility: hachura ? "visible" : "none" }, paint: { "fill-pattern": "hachura-restaurar" } })
      mapa.addLayer({ id: "agua-app", type: "line", source: "camadas", filter: ["in", ["get", "camada"], ["literal", ["agua", "app"]]], paint: { "line-color": COR.agua, "line-width": 1.5 } })
      mapa.addLayer({ id: "contorno-branco", type: "line", source: "imovel", paint: { "line-color": MAPA.contornoFora, "line-width": 6, "line-opacity": 0.9 } })
      mapa.addLayer({ id: "contorno-imovel", type: "line", source: "imovel", paint: { "line-color": satelite ? MAPA.contornoSatelite : MAPA.contornoClaro, "line-width": 2.5 } })
    })
    return () => { mapa.remove() }
  }, [visual, base, foto, mostrarFoto, hachura])

  return <section className="visual-terra" aria-labelledby="mapa-terra-titulo">
    <h2 id="mapa-terra-titulo">A fazenda vista de cima</h2>
    <div className="controles-visual">
      <label><input type="checkbox" checked={mostrarFoto} disabled={!foto} onChange={(e) => setMostrarFoto(e.target.checked)} /> Mostrar satélite</label>
      <label><input type="checkbox" checked={hachura} onChange={(e) => setHachura(e.target.checked)} /> Mostrar área que pode virar mata</label>
    </div>
    <figure>
      <div className="mapa-caixa mapa-ficha-terra" ref={caixa} role="region" aria-label="Mapa privado da fazenda, com limite e áreas medidas" />
      <figcaption className="mapa-legenda-fixa">
        {foto && <span>Sentinel-2 em {dataTerra(foto.meta.data_cena)}. {foto.meta.credito}.</span>}
        <span>Em {ficha.municipio}, verde é mata em pé; listras mostram a área medida que pode voltar a ser mata. O entorno fica apagado.</span>
        <span>Limites do CAR são declarados pelo dono e podem ter erro.</span>
      </figcaption>
    </figure>
    {!visual && !erro && <p role="status">Carregando o desenho da fazenda.</p>}
    {erro && <p role="alert">{erro}</p>}
    {avisoFoto && <p role="status">{avisoFoto}</p>}
    {visual?.avisos?.map((aviso) => <p key={aviso} role="note">{aviso}</p>)}
    {visual && <details><summary>Fonte e data das camadas</summary><p>Limite: {visual.fonte_perimetro}. Áreas: {visual.fonte_camadas}.</p><p>{visual.data_referencia ? `Referência: ${dataTerra(visual.data_referencia)}.` : "A data de referência das camadas não foi informada."} Corte da carga: {dataTerra(visual.data_corte)}. A data da carga não substitui a data da fonte.</p></details>}
  </section>
}
