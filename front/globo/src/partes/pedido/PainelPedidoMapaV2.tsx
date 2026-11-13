import { ChevronDown, SlidersHorizontal, X } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import type { Geo } from "../../../../compartilhado/dados/tipos"
import { fmtCompacto, fmtHa, fmtInt, fmtPct, UFS } from "../../../../compartilhado/formato"
import type { IdOpcao, Pedido, PublicacaoLote } from "../../../../compartilhado/pedidos/tipos"
import { linkNovoPedido, linkPedido } from "../../rota"
import { sessaoPedidos, useSessao } from "../../sessao"
import { RotuloMono } from "../RotuloMono"
import { levarCriteriosDoMapaV2 } from "./criterios-do-mapa-v2"
import {
  anelPedidoMapaV2, carregarPublicacaoMapaV2, escalaFaixasMapaV2, modeloApiMapaV2, modeloPublicacaoMapaV2,
  posicoesFaixaMapaV2, type OpcaoMapaV2, type SelecaoPedidoMapaV2,
} from "./painel-pedido-mapa-v2"
import "./PainelPedidoMapaV2.css"

export type { SelecaoPedidoMapaV2 } from "./painel-pedido-mapa-v2"

export interface PainelPedidoMapaV2Props {
  aberto: boolean
  onFechar: () => void
  onSelecionar?: (selecao: SelecaoPedidoMapaV2 | null) => void
  onDesenhar?: () => void
  areaDesenhada?: Geo | null
  /** Opcional, somente resposta real obtida pela API autenticada. */
  pedidoAutenticado?: Pedido | null
  pedidoSolicitado?: boolean
  carregandoPedido?: boolean
  erroPedido?: string | null
  onRecarregarPedido?: () => void
}

const compacto = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 2 })
const dinheiro = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const data = new Intl.DateTimeFormat("pt-BR", { timeZone: "UTC", dateStyle: "short" })
const mostrar = (n: number | null, formato: (valor: number) => string = fmtInt) => n === null ? "n/d" : formato(n)

export function PainelPedidoMapaV2({ aberto, onFechar, onSelecionar, onDesenhar, areaDesenhada, pedidoAutenticado, pedidoSolicitado, carregandoPedido, erroPedido, onRecarregarPedido }: PainelPedidoMapaV2Props) {
  const sessao = useSessao()
  const [publicacao, setPublicacao] = useState<PublicacaoLote | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [tentativa, setTentativa] = useState(0)
  const [opcaoManual, setAtiva] = useState<IdOpcao | null>(null)
  const [mostrarAcesso, setMostrarAcesso] = useState(false)
  const painel = useRef<HTMLElement>(null)
  const acesso = useRef<HTMLDivElement>(null)
  const selecionarRef = useRef(onSelecionar)
  useEffect(() => { selecionarRef.current = onSelecionar }, [onSelecionar])
  const api = useMemo(() => pedidoAutenticado ? modeloApiMapaV2(pedidoAutenticado, sessaoPedidos.modo === "api" && !!sessao) : null, [pedidoAutenticado, sessao])
  const ativa = opcaoManual ?? (api && pedidoAutenticado?.opcao_escolhida) ?? "barata"
  const modelo = useMemo(() => api ?? (!pedidoSolicitado && publicacao ? modeloPublicacaoMapaV2(publicacao) : null), [api, publicacao, pedidoSolicitado])
  const escala = useMemo(() => escalaFaixasMapaV2(modelo?.opcoes ?? []), [modelo])
  const anel = useMemo(() => anelPedidoMapaV2(areaDesenhada), [areaDesenhada])

  useEffect(() => {
    if (!aberto || pedidoSolicitado || api || publicacao) return
    const controlador = new AbortController()
    carregarPublicacaoMapaV2(import.meta.env.VITE_RAIZ_DADOS_BASE || import.meta.env.BASE_URL || "/", controlador.signal)
      .then(p => { setPublicacao(p); setErro(null) })
      .catch((e: unknown) => { if (!controlador.signal.aborted) setErro(e instanceof Error ? e.message : "Não foi possível ler os lotes publicados.") })
    return () => controlador.abort()
  }, [aberto, api, publicacao, tentativa, pedidoSolicitado])

  useEffect(() => {
    if (!aberto) return
    const anterior = document.activeElement instanceof HTMLElement ? document.activeElement : null
    painel.current?.focus({ preventScroll: true })
    return () => { if (anterior?.isConnected) anterior.focus({ preventScroll: true }) }
  }, [aberto])

  useEffect(() => {
    selecionarRef.current?.(aberto ? modelo?.opcoes.find(o => o.id === ativa)?.selecao ?? null : null)
  }, [aberto, modelo, ativa])

  useEffect(() => { if (mostrarAcesso) acesso.current?.scrollIntoView({ block: "nearest" }) }, [mostrarAcesso])

  if (!aberto) return null
  const selecionada = modelo?.opcoes.find(o => o.id === ativa)
  const erroExibido = pedidoSolicitado ? erroPedido : erro
  const tituloMeta = modelo?.meta === null || !modelo ? null : `${fmtCompacto(modelo.meta)}${modelo.meta >= 1e6 ? " de " : " "}${modelo.unidade}`
  const cobrem = modelo?.meta !== null && modelo?.unidade === "créditos" && modelo?.opcoes.length
    ? modelo.opcoes.filter(o => o.creditos && o.creditos.p50 >= modelo.meta!).length : 0
  const area = areaDesenhada ? (anel ? `${fmtInt(anel.length - 1)} cantos desenhados. A área ainda não foi aplicada aos lotes.` : "O desenho ainda não forma um polígono válido para o pedido.") : null
  const editarCriterios = () => levarCriteriosDoMapaV2({
    origem: modelo?.origem ?? "publicacao",
    meta: api && pedidoAutenticado ? pedidoAutenticado.campos.meta : modelo?.meta !== null && modelo?.meta !== undefined ? { tipo: "creditos", valor: modelo.meta } : null,
    ufs: modelo?.uf ? [modelo.uf] : [], precoVenda: modelo?.origem === "publicacao" ? modelo.preco : null, poligono: anel,
    ...(api && pedidoAutenticado ? { campos: pedidoAutenticado.campos } : {}),
  })

  return <section ref={painel} tabIndex={-1} className="pedido-mapa-v2" aria-labelledby="pedido-mapa-v2-titulo" onKeyDown={e => { if (e.key === "Escape") { e.stopPropagation(); onFechar() } }}>
    <header className="pedido-mapa-v2-cabecalho">
      <div className="pedido-mapa-v2-contexto"><RotuloMono partes={["Pedido", modelo?.uf ? UFS[modelo.uf] ?? modelo.uf : null, modelo?.origem === "publicacao" ? "resumo público" : null]} /><button type="button" className="pedido-mapa-v2-fechar" onClick={onFechar} aria-label="Fechar pedido"><X size={19} aria-hidden="true" /></button></div>
      <h2 id="pedido-mapa-v2-titulo">{tituloMeta ? <>{tituloMeta}.<br /><em>{modelo!.opcoes.length} lotes</em> {cobrem === modelo!.opcoes.length && cobrem > 0 ? "alcançam a meta no P50." : "para comparar."}</> : "Compare os lotes."}</h2>
      {!!modelo?.opcoes.length && <div className="pedido-mapa-v2-abas" role="group" aria-label="Alternativa selecionada">{modelo.opcoes.map(o => <button type="button" key={o.id} aria-pressed={ativa === o.id} onClick={() => setAtiva(o.id)}>{o.nome}</button>)}</div>}
    </header>

    <div className="pedido-mapa-v2-corpo">
      {erroExibido ? <div className="pedido-mapa-v2-estado" role="alert"><h3>{pedidoSolicitado ? "Pedido indisponível" : "Resumo indisponível"}</h3><p>{erroExibido}</p><button type="button" onClick={pedidoSolicitado ? onRecarregarPedido : () => { setErro(null); setTentativa(t => t + 1) }}>Tentar novamente</button></div>
        : !modelo ? <p className="pedido-mapa-v2-estado" role="status">{pedidoSolicitado ? (carregandoPedido ? "Carregando o pedido autorizado…" : "Este pedido ainda não trouxe opções autorizadas.") : "Carregando os números publicados dos lotes…"}</p>
        : !modelo.publicado || !modelo.opcoes.length ? <div className="pedido-mapa-v2-estado" role="status"><h3>Lotes ainda não publicados</h3><p>O painel mostrará os três resumos quando o cálculo real estiver disponível. Nenhum número foi estimado aqui.</p></div>
        : <>
          <div className="pedido-mapa-v2-lotes">{modelo.opcoes.map(o => <CartaoLote key={o.id} opcao={o} ativo={ativa === o.id} escala={escala} aoEscolher={() => setAtiva(o.id)} />)}</div>
          <details className="pedido-mapa-v2-fonte"><summary>Fonte, preço e limites <ChevronDown size={14} aria-hidden="true" /></summary><div>
            <p>{modelo.origem === "publicacao" ? "Resumo do cenário publicado. Novos filtros não recalculam estes lotes. A composição e o desenho das fazendas exigem autorização da API." : "Pedido calculado pela API. O mapa mostra somente geometrias autorizadas para esta sessão."}</p>
            <p>As três opções são alternativas; não some seus totais. P10/P50/P90 são quantis, não garantias de entrega.</p>
            <p>n/d significa que a medida não está disponível; não equivale a zero.</p>
            <p>Preço {modelo.origem === "publicacao" ? "do contrato publicado" : "máximo do pedido"}: {modelo.preco === null ? "não informado" : `US$ ${dinheiro.format(modelo.preco)} por crédito`}. Reserva contra reversão: não informada neste resumo.</p>
            <p>{modelo.atualizadoEm ? `Revisão de ${data.format(new Date(modelo.atualizadoEm))}. ` : "Data ainda não publicada. "}{modelo.versao ? `Modelo ${modelo.versao}.` : ""} {modelo.fonte && <a href={modelo.fonte} target="_blank" rel="noreferrer">Fonte da publicação</a>}</p>
          </div></details>
        </>}
      {area && <p className="pedido-mapa-v2-area" role="status">{area} Para usar esse recorte, envie um novo pedido à API autenticada.</p>}
      {mostrarAcesso && <div ref={acesso} id="pedido-mapa-v2-acesso" className="pedido-mapa-v2-acesso" role="status"><strong>Contato somente na fase final</strong><p>{api ? "Abra o pedido para revisar as fazendas, as pendências e a etapa de interesse. Nenhum contato foi iniciado." : "O resumo aberto não inicia contato. A revisão das fazendas e a confirmação do interesse ficam na área autenticada. Nenhum dono foi contatado."}</p>{api?.pedidoId ? <a href={linkPedido(api.pedidoId)}>Revisar pedido na área logada</a> : sessaoPedidos.modo === "api" ? <a href="#/entrar">Entrar para revisar o pedido</a> : <p>A API autenticada ainda não está conectada.</p>}</div>}
    </div>

    <footer className="pedido-mapa-v2-rodape">
      <div className="pedido-mapa-v2-criterios"><a href={linkNovoPedido} onClick={editarCriterios}><SlidersHorizontal size={14} aria-hidden="true" />Editar critérios do pedido</a><span>{selecionada?.selecao.origem === "api" && selecionada.selecao.fazendas.length ? "Geometria autorizada" : "Sem composição pública"}</span></div>
      <div className="pedido-mapa-v2-acoes"><button type="button" className="pedido-mapa-v2-desenhar" onClick={onDesenhar} disabled={!onDesenhar}>Desenhar área</button><button type="button" className="pedido-mapa-v2-interesse" aria-expanded={mostrarAcesso} aria-controls="pedido-mapa-v2-acesso" onClick={() => setMostrarAcesso(v => !v)}>Buscar interesse dos donos</button></div>
    </footer>
  </section>
}

function CartaoLote({ opcao: o, ativo, escala, aoEscolher }: { opcao: OpcaoMapaV2; ativo: boolean; escala: ReturnType<typeof escalaFaixasMapaV2>; aoEscolher: () => void }) {
  const posicoes = posicoesFaixaMapaV2(o.creditos, escala)
  const temMapa = o.selecao.origem === "api" && o.selecao.fazendas.length > 0
  return <article className={`pedido-mapa-v2-lote${ativo ? " ativo" : ""}`} aria-label={`Lote ${o.nome.toLowerCase()}`}>
    <div className="pedido-mapa-v2-lote-topo"><h3><button type="button" aria-pressed={ativo} onClick={aoEscolher}>{o.nome}</button></h3><span className="pedido-mapa-v2-selo">{temMapa ? (ativo ? "no mapa" : "ver no mapa") : o.selecao.origem === "publicacao" ? "resumo público" : "sem geometria"}</span></div>
    <dl className="pedido-mapa-v2-numeros"><div><dd>{mostrar(o.fazendas)}</dd><dt>fazendas</dt></div><div><dd>{mostrar(o.hectares, fmtHa)}</dd><dt>a restaurar</dt></div><div><dd>{mostrar(o.creditos?.p50 ?? null, n => compacto.format(n))}</dd><dt>créditos P50</dt></div></dl>
    <div className="pedido-mapa-v2-faixa">
      {posicoes && o.creditos ? <><div className="pedido-mapa-v2-faixa-barra" role="img" aria-label={`Créditos P10 ${fmtInt(o.creditos.p10)}, P50 ${fmtInt(o.creditos.p50)}, P90 ${fmtInt(o.creditos.p90)}. Todas as opções usam a mesma escala.`}><i style={{ left: `${posicoes.p10}%`, width: `${posicoes.p90 - posicoes.p10}%` }} /><b style={{ left: `${posicoes.p50}%` }} /></div><div className="pedido-mapa-v2-faixa-rotulos"><span>P10 {compacto.format(o.creditos.p10)}</span><span>P90 {compacto.format(o.creditos.p90)}</span></div></> : <p>Faixa de créditos ainda não publicada.</p>}
    </div>
    <div className="pedido-mapa-v2-complemento"><span>{o.custo === null ? "Preço n/d" : `US$ ${dinheiro.format(o.custo)}/crédito`}</span><span>{o.terraPronta === null ? "Terra pronta n/d" : `${fmtPct(o.terraPronta)} da meta com terra pronta`}</span></div>
  </article>
}
