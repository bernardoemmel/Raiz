import { SITUACOES_BASICAS, type SituacaoBasica } from "../../../compartilhado/dados/basico"
import { lazy, Suspense, useEffect, useMemo, useRef, useState, type CSSProperties } from "react"
import { codigosEmLeilao } from "../../../compartilhado/calendario"
import { calendario } from "../calendario"
import { fmtDataHoraBrasilia, fmtInt, UFS, ufDoCodigo } from "../../../compartilhado/formato"
import type { Foco } from "../../../compartilhado/funil-etapas"
import { fonte, useCarga } from "../dados"
import type { CamadaAssunto, GeoMunicipio } from "../mapa/MapaBrasil"
import { Cabecalho } from "../partes/Cabecalho"
import { useProcessamentoEstados } from "../processamento-estados"
import { destinoTerritorialMapa, type FocoTerritorialMapa } from "../rota"
import type { Geo } from "../../../compartilhado/dados"
import { contarCobertura } from "../../../compartilhado/dados/cobertura-mapa"
import { Layers, X, ChevronDown } from "lucide-react"
import type { LegendaHexagonos } from "../mapa/hexagonos"
import { prepararContextoMapa } from "../mapa/preparar-contexto"
import { CartaoTerritorioV2 } from "../partes/CartaoTerritorioV2"
import { RotuloMono } from "../partes/RotuloMono"
import type { SelecaoPedidoMapaV2 } from "../partes/pedido/PainelPedidoMapaV2"
import type { Pedido } from "../../../compartilhado/pedidos/tipos"
import { sessaoPedidos, useSessao } from "../sessao"
import "./explorar-v2.css"

const PainelBrasil = lazy(() => import("../partes/PainelBrasil").then(m => ({ default: m.PainelBrasil })))
const PainelProcessamentoEstados = lazy(() => import("../partes/PainelProcessamentoEstados").then(m => ({ default: m.PainelProcessamentoEstados })))
const PainelPedidoMapaV2 = lazy(() => import("../partes/pedido/PainelPedidoMapaV2").then(m => ({ default: m.PainelPedidoMapaV2 })))
const MapaBrasil = lazy(() => import("../mapa/MapaBrasil").then((m) => ({ default: m.MapaBrasil })))
const PainelMunicipio = lazy(() => import("../partes/PainelMunicipio").then((m) => ({ default: m.PainelMunicipio })))
const PainelMunicipioBasico = lazy(() => import("../partes/PainelMunicipioBasico").then((m) => ({ default: m.PainelMunicipioBasico })))

/** Mapa contínuo, com controles e resumos sobrepostos. Dados extensos só abrem sob demanda. */
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
    return () => { void preparo.then(liberar => liberar()) }
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
  const [avisoFiltro, setAvisoFiltro] = useState("")
  const dadosDialogo = useRef<HTMLDialogElement>(null)
  const camadasDialogo = useRef<HTMLDialogElement>(null)
  const filtrosDialogo = useRef<HTMLDialogElement>(null)
  const cartao = useRef<HTMLDivElement>(null)
  const arraste = useRef<number | null>(null)
  useEffect(() => { dadosDialogo.current?.close() }, [municipio, uf])
  useEffect(() => {
    setFoco(null); setSituacaoBasica(null); setCamada("situacao"); setDestaque(null)
  }, [municipio])
  useEffect(() => {
    const medir = () => {
      const celular = matchMedia("(max-width: 700px)").matches
      setMargem(celular && !pedidoAberto ? cartao.current?.getBoundingClientRect().height ?? 240 : 0)
      setMargemDireita(!celular && pedidoAberto ? 462 : 0)
    }
    medir()
    const observer = new ResizeObserver(medir)
    if (cartao.current) observer.observe(cartao.current)
    window.addEventListener("resize", medir)
    return () => { observer.disconnect(); window.removeEventListener("resize", medir) }
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
  const nome = municipio ? `Brasil / ${UFS[ufFoco ?? ""] ?? ufFoco ?? ""} / ${funil.dado?.municipio ?? String(feicao?.properties.nome ?? "Município")}` : ufExibida ? `Brasil / ${UFS[ufExibida] ?? ufExibida}` : "Brasil"
  const resumo = useMemo(() => municipio ? (funil.carregando ? undefined : funil.dado ? [funil.dado] : []) : municipios.dado?.filter(m => !ufExibida || m.uf === ufExibida), [municipio, funil.dado, funil.carregando, municipios.dado, ufExibida])
  const contagem = coberturaMapa.dado ? contarCobertura(coberturaMapa.dado) : null
  const abrirFiltro = (mensagem: string) => { setAvisoFiltro(mensagem); filtrosDialogo.current?.showModal() }
  const filtros = <>
    <button className="topo-pilula filtro-v2" onClick={() => abrirFiltro("Os agregados publicados ainda não têm bioma por célula. Para fazer um pedido por bioma, use os critérios do pedido.")}>Bioma <span>todos</span><ChevronDown size={12} /></button>
    <button className="topo-pilula filtro-v2" onClick={() => abrirFiltro(municipio ? "Filtre a situação básica dos imóveis deste município. Os hexágonos continuam sendo o total cadastrado." : "A situação individual está disponível ao abrir um município. O agregado nacional conta todos os cadastros, sem inferir aptidão.")}>Situação <span>{situacaoBasica ? SITUACOES_BASICAS[situacaoBasica] : "todas"}</span><ChevronDown size={12} /></button>
    <button className="topo-pilula filtro-v2" onClick={() => abrirFiltro("O resumo aberto não contém o título de cada fazenda. A análise documental é consultada na ficha autorizada.")}>Título <span>qualquer</span><ChevronDown size={12} /></button>
    <button className="topo-pilula filtro-v2" onClick={() => abrirFiltro("Os agregados não separam o tamanho dos imóveis. Fazendas pequenas também entram na base e podem formar projetos agrupados.")}>Tamanho <span>todas</span><ChevronDown size={12} /></button>
  </>
  const escolherCamada = (valor: CamadaAssunto | "uso" | "vizinhos") => {
    if (valor === "situacao") { setCamada(valor); return }
    if (municipio && imoveis.dado?.length && valor === "titulo") { setCamada(valor); return }
    camadasDialogo.current?.close()
    abrirFiltro(valor === "fogo" ? "Os recortes de desmatamento não estão neste agregado. Dados de queimadas não substituem a perda de floresta; consulte a ficha autorizada quando essa camada estiver disponível." : valor === "uso" ? "O uso da terra e a área para restaurar são recortes medidos, disponíveis na ficha autorizada quando publicados. O agregado H3 não representa essa geometria." : valor === "vizinhos" ? "A proximidade entre imóveis é analisada no pedido autorizado. O resumo aberto não revela a composição dos lotes." : "Esta camada detalhada depende dos dados do município e do acesso à ficha. Nenhuma classificação foi presumida no mapa aberto.")
  }
  const camadas = <div className="camadas-v2-opcoes" role="group" aria-label="Assunto do mapa">{([
    ["situacao", "Fazendas cadastradas"], ["uso", "Uso da terra"], ["titulo", "Título"], ["fogo", "Desmatamento"], ["vizinhos", "Vizinhos"],
  ] as const).map(([id, rotulo]) => <button type="button" key={id} aria-pressed={camada === id} onClick={() => escolherCamada(id)}><span>{rotulo}</span><i className={id === "situacao" ? "camada-v2-espectro" : ""} aria-hidden="true"><b /><b /><b /><b /></i></button>)}</div>
  const escala = legenda && zoom < 9 ? <div className="legenda-v2" aria-label={legenda.titulo}>
    <RotuloMono>{legenda.unidade} por hexágono (cada um ~{fmtInt(legenda.areaAproximadaKm2)} km²)</RotuloMono>
    <div className="legenda-v2-escala">{legenda.limites.map((n, i) => <div key={i}><i style={{ backgroundColor: legenda.cores[i] }} /><span>{fmtInt(n)}{i === 5 ? "+" : ""}</span></div>)}</div>
  </div> : null
  const soltar = (y: number) => { const inicio = arraste.current; arraste.current = null; if (inicio !== null) setAmpliado(Math.abs(inicio - y) < 8 ? !ampliado : inicio > y) }

  return (
    <div className={`explorar explorar-v2${pedidoAberto ? " com-pedido" : ""}`}>
      <Cabecalho atual="mapa" linkMapa="#/" modoMapa aoAbrirPedido={() => setPedidoAberto(v => !v)} pedidoAberto={pedidoAberto} filtros={filtros} />
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
        {!desenhando && <div ref={cartao} className="cartao-v2-posicao"><CartaoTerritorioV2 nome={nome} municipios={resumo} carregando={municipio ? funil.carregando : municipios.carregando} aoAbrirDados={() => { setDadosAbertos(true); dadosDialogo.current?.showModal() }} ampliado={ampliado} aoAlternar={() => setAmpliado(v => !v)} aoArrastar={y => { arraste.current = y }} aoSoltar={soltar} /></div>}
        {!pedidoAberto && !desenhando && <>
          <nav className="camadas-v2" aria-label="Camadas do mapa">{camadas}</nav>
          <button type="button" className="camadas-v2-abrir" onClick={() => camadasDialogo.current?.showModal()}><Layers size={18} aria-hidden="true" />Camadas</button>
          <div className="legenda-v2-posicao">{escala}</div>
          <div className="status-mapa-v2"><RotuloMono partes={contagem ? [`${fmtInt(contagem.municipios)} municípios`, `${fmtInt(contagem.estados)} estados`] : ["Lendo a cobertura"]} /><br />{coberturaMapa.dado?.gerado_em && <time dateTime={coberturaMapa.dado.gerado_em}>atualizado {fmtDataHoraBrasilia(coberturaMapa.dado.gerado_em)}</time>}</div>
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
                nome={funil.dado?.municipio ?? (feicao?.properties.nome as string | undefined) ?? "Município"}
                uf={ufFoco ?? ""}
                centro={centro}
                funil={funil.dado ?? null}
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
                funil={funil.carregando ? undefined : (funil.dado ?? null)}
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
        <dialog ref={camadasDialogo} className="dialogo-mapa-v2" aria-labelledby="titulo-camadas-v2"><header><h2 id="titulo-camadas-v2">Camadas do mapa</h2><button aria-label="Fechar camadas" onClick={() => camadasDialogo.current?.close()}><X size={20} /></button></header>{camadas}{escala}</dialog>
        <dialog ref={filtrosDialogo} className="dialogo-mapa-v2" aria-labelledby="titulo-filtros-v2"><header><h2 id="titulo-filtros-v2">Dados disponíveis</h2><button aria-label="Fechar informação" onClick={() => filtrosDialogo.current?.close()}><X size={20} /></button></header><p>{avisoFiltro}</p>
          {municipio && <label className="campo">Situação básica<select value={situacaoBasica ?? ""} onChange={e => { setSituacaoBasica(e.target.value as SituacaoBasica || null); filtrosDialogo.current?.close() }}><option value="">Todas as situações</option>{Object.entries(SITUACOES_BASICAS).map(([id, rotulo]) => <option key={id} value={id}>{rotulo}</option>)}</select></label>}
          <a href="#/pedidos/novo">Abrir critérios de um pedido</a>
        </dialog>
      </main>
    </div>
  )
}
