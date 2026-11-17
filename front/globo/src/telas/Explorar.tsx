import type { SituacaoBasica } from "../../../compartilhado/dados/basico"
import { lazy, Suspense, useEffect, useMemo, useRef, useState, type CSSProperties } from "react"
import { codigosEmLeilao } from "../../../compartilhado/calendario"
import { calendario } from "../calendario"
import { fmtDataHoraBrasilia, fmtInt, UFS, ufDoCodigo } from "../../../compartilhado/formato"
import type { Foco } from "../../../compartilhado/funil-etapas"
import { fonte, useCarga } from "../dados"
import type { CamadaAssunto, GeoMunicipio } from "../mapa/MapaBrasil"
import { cederProcessamento } from "../../../compartilhado/ceder-processamento"
import { Cabecalho } from "../partes/Cabecalho"
import { useProcessamentoEstados } from "../processamento-estados"
import { destinoTerritorialMapa, type FocoTerritorialMapa } from "../rota"
import type { Geo } from "../../../compartilhado/dados"
import { contarCobertura } from "../../../compartilhado/dados/cobertura-mapa"
import { X } from "lucide-react"
import type { LegendaHexagonos } from "../mapa/hexagonos"
import { prepararContextoMapa } from "../mapa/preparar-contexto"
import { CartaoTerritorioV2 } from "../partes/CartaoTerritorioV2"
import { RotuloMono } from "../partes/RotuloMono"
import type { SelecaoPedidoMapaV2 } from "../partes/pedido/PainelPedidoMapaV2"
import type { Pedido } from "../../../compartilhado/pedidos/tipos"
import { sessaoPedidos, useSessao } from "../sessao"
import { PainelFiltrosMapa, ROTULO_OFERTA, type Bioma, type Oferta, type TipoArea } from "../partes/PainelFiltrosMapa"
import { SATELITE_PUBLICO } from "../mapa/satelite-publico"
import "./explorar-v2.css"

const PainelBrasil = lazy(() => import("../partes/PainelBrasil").then(m => ({ default: m.PainelBrasil })))
const PainelProcessamentoEstados = lazy(() => import("../partes/PainelProcessamentoEstados").then(m => ({ default: m.PainelProcessamentoEstados })))
const PainelPedidoMapaV2 = lazy(() => import("../partes/pedido/PainelPedidoMapaV2").then(m => ({ default: m.PainelPedidoMapaV2 })))
const MapaBrasil = lazy(async () => {
  // Avaliar a biblioteca gráfica e montar o componente na mesma tarefa bloqueia a entrada.
  // A dependência fica em cache; a continuação entrega a thread antes de avaliar o mapa.
  await import("../mapa/estilo")
  await cederProcessamento()
  const m = await import("../mapa/MapaBrasil")
  return { default: m.MapaBrasil }
})
const PainelMunicipio = lazy(() => import("../partes/PainelMunicipio").then((m) => ({ default: m.PainelMunicipio })))
const PainelMunicipioBasico = lazy(() => import("../partes/PainelMunicipioBasico").then((m) => ({ default: m.PainelMunicipioBasico })))

/** Ponto dentro de Polygon ou MultiPolygon (par-ímpar, anéis internos incluídos). */
function dentroDe([x, y]: [number, number], g: Geo["features"][number]["geometry"]): boolean {
  const poligonos = (g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : []) as number[][][][]
  let dentro = false
  for (const aneis of poligonos) for (const anel of aneis)
    for (let i = 0, j = anel.length - 1; i < anel.length; j = i++) {
      const [xi, yi] = anel[i], [xj, yj] = anel[j]
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) dentro = !dentro
    }
  return dentro
}

function useMedia(consulta: string) {
  const [ativa, setAtiva] = useState(() => matchMedia(consulta).matches)
  useEffect(() => {
    const media = matchMedia(consulta)
    const mudar = () => setAtiva(media.matches)
    media.addEventListener("change", mudar)
    return () => media.removeEventListener("change", mudar)
  }, [consulta])
  return ativa
}

/** Mapa de satélite em tela cheia, filtros à esquerda, legenda embaixo. Dados extensos só abrem sob demanda. */
export function Explorar({ municipio: municipioRota, uf: ufRota, pedidoId }: { municipio: string | null; uf: string | null; pedidoId?: string }) {
  const [focoNoPedido, setFocoNoPedido] = useState<FocoTerritorialMapa>({ municipio: null, uf: null })
  const municipio = pedidoId ? focoNoPedido.municipio : municipioRota
  const uf = pedidoId ? focoNoPedido.uf : ufRota
  const escolherTerritorio = (territorio: { municipio: string } | { uf: string }) => {
    const destino = destinoTerritorialMapa(pedidoId, territorio)
    if (destino.tipo === "foco") setFocoNoPedido(destino.foco)
    else location.hash = destino.hash
  }
  useEffect(() => {
    const preparo = prepararContextoMapa()
    return preparo.cancelar
  }, [])
  const sessao = useSessao()
  const [tentativaPedido, setTentativaPedido] = useState(0)
  const pedidoApi = useCarga<Pedido | null>(async () => {
    if (!pedidoId) return null
    if (sessaoPedidos.modo !== "api") throw new Error("Este mapa exige uma API autenticada conectada. O resumo público não identifica quais fazendas compõem o lote.")
    if (!sessao) throw new Error("Entre na sua conta para abrir este pedido no mapa.")
    const { pedidos } = await import("../pedidos")
    const p = await pedidos.pedido(pedidoId)
    if (!p) throw new Error("Este pedido não foi encontrado ou não está disponível para a conta atual.")
    if (p.exemplo || p.publicacao) throw new Error("Esta resposta não autoriza o desenho de um lote real. Consulte o resumo público ou um pedido calculado pela API.")
    return p
  }, [pedidoId, sessao?.token, tentativaPedido])
  const [pedidoAberto, setPedidoAberto] = useState(Boolean(pedidoId))
  const [selecaoPedido, setSelecaoPedido] = useState<SelecaoPedidoMapaV2 | null>(null)
  const geometriaLoteAutorizada = useMemo<Geo | null>(() => pedidoAberto && selecaoPedido?.origem === "api" && sessaoPedidos.modo === "api" && sessao && pedidoApi.dado?.id === selecaoPedido.pedidoId && !pedidoApi.carregando && !pedidoApi.erro
    ? { type: "FeatureCollection", features: selecaoPedido.fazendas.map(f => ({ type: "Feature", properties: {}, geometry: f.geometria })) } : null, [pedidoAberto, selecaoPedido, sessao, pedidoApi.dado, pedidoApi.carregando, pedidoApi.erro])
  const [desenhando, setDesenhando] = useState(false)
  const [dadosAbertos, setDadosAbertos] = useState(false)
  const processamento = useProcessamentoEstados(!municipio && dadosAbertos)
  // O MapLibre abre desde a primeira tela. Os limites dos 5.571 municípios só entram ao aproximar.
  const [aproximou, setAproximou] = useState(false)
  const detalhe = Boolean(municipio || uf || aproximou || selecaoPedido?.uf)
  const brasil = useCarga(() => fonte.geo.brasil({ municipios: detalhe }), [detalhe])
  const coberturaMapa = useCarga(() => fonte.geo.cobertura(), [])
  const estados = useCarga(() => fonte.estados(), [])
  const municipios = useCarga(() => fonte.municipios(), [])
  // o estado em foco: o escolhido, ou o do município aberto; os pontos são só dele
  const ufFoco = municipio ? ufDoCodigo(municipio) : uf
  const agregados = useCarga(() => fonte.geo.agregados ? fonte.geo.agregados() : Promise.resolve(null), [])
  const leiloes = useCarga(() => municipio ? calendario.leiloes({ estado: ufFoco || undefined }) : Promise.resolve(null), [municipio, ufFoco])
  const emLeilao = useMemo(() => leiloes.dado ? codigosEmLeilao(leiloes.dado.eventos) : new Set<string>(), [leiloes.dado])
  const funil = useCarga(() => (municipio ? fonte.municipio(municipio) : Promise.resolve(null)), [municipio])
  const imoveis = useCarga(() => (municipio ? fonte.imoveis(municipio) : Promise.resolve(null)), [municipio])
  const basicos = useCarga(() => (municipio && fonte.basicos ? fonte.basicos(municipio) : Promise.resolve(null)), [municipio])
  const [situacaoBasica, setSituacaoBasica] = useState<SituacaoBasica | null>(null)
  const geoMunicipio = useCarga<GeoMunicipio | null>(async () => {
    if (!municipio) return null
    const [m, i, ti, uc, rios, terraPublica, base] = await Promise.all([
      fonte.geo.camada(municipio, "municipio"),
      fonte.geo.camada(municipio, "imoveis"),
      fonte.geo.camada(municipio, "ti"),
      fonte.geo.camada(municipio, "uc"),
      fonte.geo.camada(municipio, "rios"),
      fonte.geo.camada(municipio, "terra_publica").catch(() => null), // só a API tem; a amostra não
      fonte.geo.base(municipio),
    ])
    return { municipio: m, imoveis: i, ti, uc, rios, terraPublica, base }
  }, [municipio])

  const [foco, setFoco] = useState<Foco>(null)
  const [camada, setCamada] = useState<CamadaAssunto>("situacao")
  const [destaque, setDestaque] = useState<string | null>(null)
  const [legenda, setLegenda] = useState<LegendaHexagonos | null>(null)
  const [zoom, setZoom] = useState(0)
  const [ampliado, setAmpliado] = useState(false)
  const [margem, setMargem] = useState(0)
  const [margemDireita, setMargemDireita] = useState(0)
  const [areaDesenhada, setAreaDesenhada] = useState<Geo | null>(null)
  const dadosDialogo = useRef<HTMLDialogElement>(null)
  const celular = useMedia("(max-width: 700px)")
  const [filtrosAbertos, setFiltrosAbertos] = useState(() => !matchMedia("(max-width: 700px)").matches && innerHeight >= 760)
  const [bioma, setBioma] = useState<Bioma | null>(null)
  const [areasOcultas, setAreasOcultas] = useState<ReadonlySet<TipoArea>>(new Set())
  const [oferta, setOferta] = useState<Oferta>("aptas")
  // Bioma de cada município pela sede (IBGE): carregado só quando a pessoa escolhe um bioma.
  const biomaDosMunicipios = useCarga<Map<string, string> | null>(async () => {
    if (!bioma) return null
    const base = import.meta.env.BASE_URL + "mapa/"
    const [sedes, todos] = await Promise.all([fetch(base + "sedes_municipios.json").then(r => r.json()) as Promise<Record<string, [number, number]>>, fetch(base + "biomas.geojson").then(r => r.json()) as Promise<Geo>])
    const mapa = new Map<string, string>()
    for (const [cod, ponto] of Object.entries(sedes)) {
      const achado = todos.features.find(f => dentroDe(ponto, f.geometry))
      if (achado) mapa.set(cod, String(achado.properties.nome))
    }
    return mapa
  }, [Boolean(bioma)])
  const biomas = useCarga<Geo | null>(async () => {
    if (!bioma) return null
    const r = await fetch(import.meta.env.BASE_URL + "mapa/biomas.geojson")
    if (!r.ok) throw new Error("Contorno dos biomas indisponível.")
    const todos = await r.json() as Geo
    return { type: "FeatureCollection", features: todos.features.filter(f => f.properties.nome === bioma) }
  }, [bioma])
  const cartao = useRef<HTMLDivElement>(null)
  const arraste = useRef<number | null>(null)
  useEffect(() => { dadosDialogo.current?.close() }, [municipio, uf])
  useEffect(() => {
    setFoco(null); setSituacaoBasica(null); setCamada("situacao"); setDestaque(null)
  }, [municipio])
  useEffect(() => {
    let alturaCartao = 0
    const aplicarMargens = () => {
      const celular = matchMedia("(max-width: 700px)").matches
      setMargem(celular && !pedidoAberto ? alturaCartao + 8 : 0)
      setMargemDireita(!celular ? pedidoAberto ? 462 : 400 : 0)
    }
    aplicarMargens()
    // O navegador entrega a medida após o layout; não força uma leitura síncrona
    // enquanto React ainda está montando a entrada e carregando as fontes.
    const observer = new ResizeObserver(([entrada]) => {
      if (!entrada) return
      alturaCartao = entrada.borderBoxSize[0]?.blockSize ?? entrada.contentRect.height
      aplicarMargens()
    })
    if (cartao.current) observer.observe(cartao.current)
    window.addEventListener("resize", aplicarMargens)
    return () => { observer.disconnect(); window.removeEventListener("resize", aplicarMargens) }
  }, [ampliado, pedidoAberto])

  const processados = useMemo(() => new Set((municipios.dado ?? []).map((m) => m.cod_ibge)), [municipios.dado])
  const listas = useMemo(() => new Set((estados.dado?.estados ?? []).flatMap((e) => e.com_lista)), [estados.dado])
  const feicao = municipio ? brasil.dado?.municipios?.features.find((f) => String(f.properties.cod_ibge) === municipio) : undefined
  const centro = useMemo<[number, number] | null>(() => {
    if (!feicao) return null
    let x0 = Infinity,
      y0 = Infinity,
      x1 = -Infinity,
      y1 = -Infinity
    const andar = (c: unknown): void => {
      if (Array.isArray(c) && typeof c[0] === "number") {
        x0 = Math.min(x0, c[0])
        x1 = Math.max(x1, c[0])
        y0 = Math.min(y0, c[1] as number)
        y1 = Math.max(y1, c[1] as number)
      } else if (Array.isArray(c)) c.forEach(andar)
    }
    andar(feicao.geometry.coordinates)
    return [(x0 + x1) / 2, (y0 + y1) / 2]
  }, [feicao])

  const ufExibida = pedidoId && uf ? uf : (pedidoAberto || desenhando) && selecaoPedido?.uf ? selecaoPedido.uf : uf
  // A identidade protege também o primeiro render da nova rota, antes do efeito de useCarga.
  const funilAtual = funil.dado?.cod_ibge === municipio ? funil.dado : null
  const nomeMunicipio = funilAtual?.municipio ?? String(feicao?.properties.nome ?? municipio ?? "Município")
  const carregandoFunilAtual = funil.carregando || Boolean(funil.dado && !funilAtual)
  const nome = municipio ? `Brasil / ${UFS[ufFoco ?? ""] ?? ufFoco ?? ""} / ${nomeMunicipio}` : ufExibida ? `Brasil / ${UFS[ufExibida] ?? ufExibida}${bioma ? ` / ${bioma}` : ""}` : bioma ? `Brasil / ${bioma}` : "Brasil"
  // Os filtros recortam a oferta: estado e bioma tiram municípios; a situação muda o que cada bola soma.
  const municipiosFiltrados = useMemo(() => municipios.dado?.filter(m => (!ufExibida || m.uf === ufExibida)
    && (!bioma || biomaDosMunicipios.dado?.get(m.cod_ibge) === bioma)), [municipios.dado, ufExibida, bioma, biomaDosMunicipios.dado])
  const resumo = useMemo(() => municipio ? (carregandoFunilAtual ? undefined : funilAtual ? [funilAtual] : []) : municipiosFiltrados, [municipio, funilAtual, carregandoFunilAtual, municipiosFiltrados])
  const oportunidades = useMemo(() => bioma && !biomaDosMunicipios.dado ? null : municipiosFiltrados?.map(m => ({ cod_ibge: m.cod_ibge, uf: m.uf,
    aptas: oferta === "matricula" ? m.aptas_com_matricula : oferta === "agrupar" ? m.para_agrupar : m.aptas_carbono,
    ha: oferta === "matricula" ? m.ha_carbono_matricula : oferta === "agrupar" ? -1 : m.ha_carbono })) ?? null, [municipiosFiltrados, oferta, bioma, biomaDosMunicipios.dado])
  const contagem = coberturaMapa.dado ? contarCobertura(coberturaMapa.dado) : null
  const escala = legenda && zoom < 9 && pedidoAberto && selecaoPedido ? <div className="legenda-mapa-bloco legenda-mapa-escala">
    <RotuloMono>{legenda.unidade} por hexágono (~{fmtInt(legenda.areaAproximadaKm2)} km²)</RotuloMono>
    <div className="legenda-v2-escala">{legenda.limites.map((n, i) => <div key={i}><i style={{ backgroundColor: legenda.cores[i] }} /><span>{fmtInt(n)}{i === 5 ? "+" : ""}</span></div>)}</div>
  </div> : null
  const legendaMapa = <div className="legenda-mapa" aria-label="Legenda do mapa">
    {escala}
    <ul className="legenda-mapa-bloco legenda-mapa-itens">
      <li><i className="amostra-linha-estado" aria-hidden="true" />Limite de estado</li>
      {!municipio && <li><i className="amostra-oportunidade" aria-hidden="true" /><span><strong>{ROTULO_OFERTA[oferta]}</strong>{oferta === "agrupar" ? " (número de imóveis)" : " e hectares que podem voltar a ser mata"}. Toque para aproximar.</span></li>}
      {bioma && <li><i className="amostra-linha-bioma" aria-hidden="true" />Bioma {bioma}</li>}
      {municipio && <>
        <li><i className="amostra-situacao apta" aria-hidden="true" />Apta</li>
        <li><i className="amostra-situacao pendencia" aria-hidden="true" />Com pendência</li>
        <li><i className="amostra-situacao nao-apta" aria-hidden="true" />Não apta</li>
      </>}
    </ul>
    <div className="legenda-mapa-bloco legenda-mapa-fonte">
      <span>Satélite Sentinel-2 {SATELITE_PUBLICO.periodo} ao aproximar ({SATELITE_PUBLICO.licenca})</span>
      <span><RotuloMono partes={contagem ? [`${fmtInt(contagem.municipios)} municípios`, `${fmtInt(contagem.estados)} estados`] : ["Lendo a cobertura"]} />{coberturaMapa.dado?.gerado_em && <> <time dateTime={coberturaMapa.dado.gerado_em}>atualizado {fmtDataHoraBrasilia(coberturaMapa.dado.gerado_em)}</time></>}</span>
    </div>
  </div>
  const painelFiltros = <PainelFiltrosMapa aberto={filtrosAbertos} celular={celular} aoAlternar={() => setFiltrosAbertos(v => !v)}
    bioma={bioma} aoBioma={setBioma}
    uf={ufExibida ?? null} aoEstado={sigla => { if (sigla) escolherTerritorio({ uf: sigla }); else if (!pedidoId) location.hash = "#/"; else setFocoNoPedido({ municipio: null, uf: null }) }}
    ocultos={areasOcultas} aoTipo={(tipo, visivel) => setAreasOcultas(atual => { const novo = new Set(atual); if (visivel) novo.delete(tipo); else novo.add(tipo); return novo })}
    situacao={situacaoBasica} aoSituacao={setSituacaoBasica} municipioAberto={Boolean(municipio)}
    oferta={oferta} aoOferta={setOferta}
    aoLimpar={() => { setBioma(null); setOferta("aptas"); setAreasOcultas(new Set()); setSituacaoBasica(null); if (ufExibida || municipio) { if (pedidoId) setFocoNoPedido({ municipio: null, uf: null }); else location.hash = "#/" } }} />
  const soltar = (y: number) => { const inicio = arraste.current; arraste.current = null; if (inicio !== null) setAmpliado(Math.abs(inicio - y) < 8 ? !ampliado : inicio > y) }

  return (
    <div className={`explorar explorar-v2${pedidoAberto ? " com-pedido" : ""}`}>
      <Cabecalho atual="mapa" linkMapa="#/" modoMapa aoAbrirPedido={() => setPedidoAberto(v => !v)} pedidoAberto={pedidoAberto} />
      <main id="conteudo" tabIndex={-1} className="explorar-v2-mapa" style={{ "--altura-gaveta": `${margem}px` } as CSSProperties}>
        <div className="mapa-area">
        <Suspense fallback={<div className="mapa-brasil" aria-busy="true"><p className="mapa-aviso aviso" role="status">Abrindo o mapa do Brasil…</p></div>}><MapaBrasil
          brasil={brasil.dado}
          processados={processados}
          comLista={listas}
          estados={estados.dado}
          agregados={agregados.dado ?? null}
          agregadosCarregando={agregados.carregando}
          agregadosErro={Boolean(agregados.erro)}
          aoAproximar={() => setAproximou(true)}
          uf={ufExibida}
          municipio={municipio}
          geoMunicipio={geoMunicipio.carregando ? null : (geoMunicipio.dado ?? null)}
          imoveis={imoveis.dado ?? null}
          basicos={basicos.carregando ? null : basicos.dado ?? null}
          situacaoBasica={situacaoBasica}
          foco={foco}
          camada={camada}
          destaque={destaque}
          emLeilao={emLeilao}
          margemBaixo={margem}
          margemDireita={margemDireita}
          margemEsquerda={!celular && filtrosAbertos && !pedidoAberto ? 300 : 0}
          bioma={biomas.dado ?? null}
          areasOcultas={areasOcultas}
          oportunidades={oportunidades}
          hexagonosVisiveis={pedidoAberto && Boolean(selecaoPedido)}
          aoMudarLegenda={setLegenda}
          geometriaLoteAutorizada={geometriaLoteAutorizada}
          rotuloLoteAutorizado={geometriaLoteAutorizada?.features.length && selecaoPedido ? `Lote ${selecaoPedido.rotulo.toLowerCase()}` : null}
          aoMudarZoom={setZoom}
          desenhandoArea={desenhando}
          aoConcluirArea={geo => { setAreaDesenhada(geo); setDesenhando(false); setPedidoAberto(true) }}
          aoCancelarArea={() => { setDesenhando(false); setPedidoAberto(true) }}
          aoEscolherMunicipio={cod => escolherTerritorio({ municipio: cod })}
          aoEscolherEstado={sigla => escolherTerritorio({ uf: sigla })}
        /></Suspense>
        </div>
        {!desenhando && <div ref={cartao} className="cartao-v2-posicao"><CartaoTerritorioV2 nome={nome} municipios={resumo} carregando={municipio ? carregandoFunilAtual : municipios.carregando} aoAbrirDados={() => { setDadosAbertos(true); dadosDialogo.current?.showModal() }} ampliado={ampliado} aoAlternar={() => setAmpliado(v => !v)} aoArrastar={y => { arraste.current = y }} aoSoltar={soltar} /></div>}
        {!pedidoAberto && !desenhando && <>
          <div className={`filtros-mapa-posicao${filtrosAbertos ? " aberto" : ""}`}>{painelFiltros}{celular && filtrosAbertos && legendaMapa}</div>
          {!celular && <div className="legenda-mapa-posicao">{legendaMapa}</div>}
        </>}
        {pedidoAberto && <Suspense fallback={null}><PainelPedidoMapaV2 aberto={pedidoAberto} onFechar={() => { setPedidoAberto(false); setSelecaoPedido(null) }} onSelecionar={setSelecaoPedido} onDesenhar={() => { setDesenhando(true); setPedidoAberto(false) }} areaDesenhada={areaDesenhada}
          pedidoSolicitado={Boolean(pedidoId)} pedidoAutenticado={!pedidoApi.carregando && !pedidoApi.erro ? pedidoApi.dado : null}
          carregandoPedido={pedidoApi.carregando} erroPedido={pedidoApi.erro?.message} onRecarregarPedido={() => setTentativaPedido(t => t + 1)}
        /></Suspense>}
        <dialog ref={dadosDialogo} className="dialogo-mapa-v2 dados-mapa-v2" aria-labelledby="titulo-dados-v2" onClose={() => setDadosAbertos(false)}>
          <header><h2 id="titulo-dados-v2">Sobre os dados de {nome}</h2><button aria-label="Fechar dados" onClick={() => dadosDialogo.current?.close()}><X size={20} /></button></header>
          {dadosAbertos && <><p>O cartão soma os resumos de aptidão do motor. Os hexágonos contam cadastros do CAR, incluindo imóveis ainda não aptos. São bases com coberturas diferentes; não representam créditos disponíveis para venda.</p>
            {municipio && !geoMunicipio.carregando && !geoMunicipio.dado?.imoveis?.features.length && (
              <p className="aviso" role="status">
                {coberturaMapa.dado?.acesso === "restrito" && coberturaMapa.dado.com_desenho.includes(municipio)
                  ? "O desenho das fazendas deste município está na base. Para consultar uma fazenda, abra a ficha com acesso pago."
                  : "O desenho das fazendas deste município ainda não está disponível."}
                {listas.has(municipio) && " Os dados e a lista continuam disponíveis."}
              </p>
            )}
            <Suspense fallback={<p className="painel-conteudo" role="status">Abrindo o município…</p>}>{municipio && estados.dado?.acesso === "publico_basico" ? (
              <PainelMunicipioBasico
                key={municipio}
                nome={nomeMunicipio}
                uf={ufFoco ?? ""}
                centro={centro}
                funil={funilAtual}
                imoveis={basicos.carregando ? undefined : basicos.dado ?? null}
                situacao={situacaoBasica}
                mudarSituacao={setSituacaoBasica}
                aoPassar={setDestaque}
                emLeilao={emLeilao}
                atualizadoEm={estados.dado.estados.find((e) => e.uf === ufFoco)?.atualizado_em ?? estados.dado.gerado_em}
              />
            ) : municipio ? (
              <PainelMunicipio
                cod={municipio}
                nome={(feicao?.properties.nome as string | undefined) ?? null}
                uf={(feicao?.properties.uf as string | undefined) ?? null}
                centro={centro}
                funil={carregandoFunilAtual ? undefined : funilAtual}
                imoveis={imoveis.carregando ? undefined : (imoveis.dado ?? null)}
                foco={foco}
                aoFocar={(f) => setFoco(f)}
                camada={camada}
                mudarCamada={setCamada}
                aoPassar={setDestaque}
                emLeilao={emLeilao}
              />
            ) : (
              <PainelBrasil
                municipios={municipios.dado}
                comLista={listas}
                estados={estados.dado}
                uf={ufExibida}
                pontos={undefined}
                carregando={municipios.carregando || estados.carregando}
                carregandoResumo={municipios.carregando}
                cobertura={coberturaMapa.dado}
                carregandoCobertura={coberturaMapa.carregando}
                andamento={<PainelProcessamentoEstados key="processamento" carga={processamento} uf={ufExibida} />}
              />
            )}</Suspense></>}

        </dialog>
      </main>
    </div>
  )
}
