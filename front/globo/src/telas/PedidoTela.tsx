import NumberFlow from "@number-flow/react"
import * as Abas from "@radix-ui/react-tabs"
import { Bell, ShieldCheck, TriangleAlert } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { abreviarCar, fmtHa, fmtInt, fmtPct } from "../../../compartilhado/formato"
import { PREMISSAS } from "../../../compartilhado/pedidos/exemplo"
import {
  dataLonga,
  fmtFaixa,
  fmtFaixaMeta,
  fmtMeta,
  fmtTir,
  fmtUsd,
  ROTULO_CAMINHO,
  ROTULO_INTERESSE,
  ROTULO_META,
  ROTULO_METODO,
  ROTULO_OPCAO,
  seloDeNivel,
  tituloDoPedido,
} from "../../../compartilhado/pedidos/texto"
import type { Andamento, FazendaDoLote, IdOpcao, NivelInteresse, Opcao, Pedido } from "../../../compartilhado/pedidos/tipos"
import { fonte, useCarga } from "../dados"
import { MapaLote, type FazendaNoMapa } from "../mapa/MapaLote"
import { pedidos } from "../pedidos"
import { Cabecalho } from "../partes/Cabecalho"
import { Estado } from "../partes/Estado"
import { AvisoExemplo } from "../partes/pedido/AvisoExemplo"
import { FaixaBarra } from "../partes/pedido/FaixaBarra"
import { SeloStatus } from "../partes/pedido/SeloStatus"
import { ComparacaoLotes } from "../partes/pedido/ComparacaoLotes"
import { AvisoPublicacao, BasePublicada, QuadroDestrava } from "../partes/pedido/PublicacaoPedido"
import "../partes/pedido/pedido.css"
import { linkFazenda, linkGrupo, linkPedidos } from "../rota"

const IDS: IdOpcao[] = ["barata", "segura", "compacta"]

/**
 * O pedido: logo ao enviar, "Quanto existe na nossa base"; depois as 3 opções (mais barata, mais segura, mais
 * compacta) em abas, com o lote no mapa; e, depois de "Solicitar interesse dos donos", o andamento em ondas até o grupo
 * fechar. Nunca aparece nome, CPF ou contato do dono.
 */
export function PedidoTela({ id }: { id: string }) {
  const [pedido, setPedido] = useState<Pedido | null | undefined>(undefined)
  const [erro, setErro] = useState<string | null>(null)
  const [aba, setAba] = useState<IdOpcao>("barata")
  const [escolhida, setEscolhida] = useState<string | null>(null)
  const [andamento, setAndamento] = useState<Andamento | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const brasil = useCarga(() => fonte.geo.brasil(), [])

  const ler = useCallback(() => pedidos.pedido(id).then(setPedido, (e: Error) => setErro(e.message)), [id])
  useEffect(() => {
    ler()
  }, [ler])
  useEffect(() => {
    if (pedido?.opcao_escolhida) setAba(pedido.opcao_escolhida)
  }, [pedido?.opcao_escolhida])

  // andamento: enquanto busca, pergunta de tempos em tempos (no back-end, as ondas são de dias)
  const buscando = !!pedido?.opcao_escolhida
  useEffect(() => {
    if (!buscando) return
    let vivo = true
    let statusAntes = pedido?.status
    const perguntar = () =>
      pedidos.andamento(id).then((a) => {
        if (!vivo) return
        setAndamento(a)
        if (a && a.status !== statusAntes) {
          statusAntes = a.status
          ler()
        }
      })
    perguntar()
    const t = setInterval(perguntar, pedidos.exemplo ? Math.min(3000, PREMISSAS.onda_ms / 4) : 30_000)
    return () => {
      vivo = false
      clearInterval(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buscando, id])

  const opcao = pedido?.opcoes.find((o) => o.id === aba) ?? null
  const fazendas = useMemo<FazendaNoMapa[]>(() => {
    // Fora do acompanhamento, as três alternativas dividem o mesmo mapa, cada uma com sua cor.
    return andamento ? andamento.fazendas : (pedido?.opcoes ?? []).flatMap((o) => o.itens.map((f) => ({ ...f, opcao: o.id })))
  }, [pedido?.opcoes, andamento])

  async function mudar(acao: "tirar" | "trocar", cod: string, por?: string) {
    if (!pedido) return
    setOcupado(true)
    try {
      setPedido(await pedidos.mudarLote(pedido.id, { opcao: aba, acao, cod_imovel: cod, por }))
      setEscolhida(por ?? null)
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setOcupado(false)
    }
  }


  if (pedido === undefined && !erro)
    return (
      <Moldura titulo="Pedido">
        <Estado tipo="carregando" titulo="Montando o lote: lendo a base e as três opções" />
      </Moldura>
    )
  if (!pedido)
    return (
      <Moldura titulo="Pedido">
        <Estado tipo="erro" titulo="Não achamos este pedido.">
          <p>{erro ?? "Ele pode ser de outra conta."}</p>
          <a href={linkPedidos}>Voltar a Meus pedidos</a>
        </Estado>
      </Moldura>
    )

  const unidade = ROTULO_META[pedido.campos.meta.tipo].unidade
  const item = escolhida ? (andamento?.fazendas.find((i) => i.cod_imovel === escolhida) ?? opcao?.itens.find((i) => i.cod_imovel === escolhida) ?? null) : null
  const nivelNoAndamento = escolhida ? andamento?.fazendas.find((f) => f.cod_imovel === escolhida)?.interesse : undefined
  return (
    <Moldura titulo={tituloDoPedido(pedido.campos)}>
      <div className={`pedido-corpo${!fazendas.length ? " pedido-sem-mapa" : ""}`}>
        <aside className="pedido-painel" aria-label="O pedido">
          <ol className="migalhas" aria-label="Onde você está">
            <li>
              <a href={linkPedidos}>Meus pedidos</a>
            </li>
            <li aria-current="page">Pedido de {dataLonga(pedido.criado_em)}</li>
          </ol>
          <h1>{tituloDoPedido(pedido.campos)}</h1>
          <p>{pedido.campos.dinheiro.custo_max_usd_credito === null ? "Sem custo máximo definido." : `Custo máximo pedido: ${fmtUsd(pedido.campos.dinheiro.custo_max_usd_credito)} por crédito.`}</p>
          <div className="selos">
            {!pedido.publicacao && <SeloStatus status={pedido.status} reservadoAte={pedido.reservado_ate} />}
            <span className="selo neutro">
              <ShieldCheck size={16} aria-hidden="true" /> {pedido.publicacao ? "Consulta salva neste navegador" : "Pedido salvo"}
            </span>
          </div>
          {!pedido.publicacao && <Alertas pedido={pedido} />}
          <AvisoExemplo ativo={!!pedido.exemplo} />
          {pedido.publicacao && <AvisoPublicacao publicacao={pedido.publicacao} />}
          {erro && (
            <p className="erro-campo" role="alert">
              {erro}
            </p>
          )}

          {pedido.publicacao ? <BasePublicada publicacao={pedido.publicacao} /> : <QuadroBase pedido={pedido} unidade={unidade} />}
          <ComparacaoLotes opcoes={pedido.opcoes} publicadas={pedido.publicacao?.opcoes} selecionar={(id) => { setAba(id); setEscolhida(null) }} />

          {item && (
            <FazendaEscolhida
              item={item}
              nivel={nivelNoAndamento ?? item.interesse}
              opcao={opcao!}
              podeMudar={!pedido.opcao_escolhida && !ocupado && !pedido.publicacao}
              mudar={mudar}
              fechar={() => setEscolhida(null)}
            />
          )}

          <section className="secao-painel" aria-labelledby="opcoes-titulo">
            <h2 id="opcoes-titulo">O melhor agrupamento</h2>
            <Abas.Root value={aba} onValueChange={(v) => (setAba(v as IdOpcao), setEscolhida(null))}>
              <Abas.List className="abas" aria-label="Opções de lote">
                {IDS.map((i) => (
                  <Abas.Trigger key={i} value={i} className="aba" disabled={!!pedido.opcao_escolhida && pedido.opcao_escolhida !== i}>
                    {ROTULO_OPCAO[i].nome}
                  </Abas.Trigger>
                ))}
              </Abas.List>
              {!pedido.opcoes.length && IDS.map((id) => <Abas.Content key={id} value={id} className="aba-conteudo"><p>{ROTULO_OPCAO[id].criterio.replace(/^./, (letra) => letra.toUpperCase())}. Os detalhes por fazenda aguardam uma resposta autorizada do motor.</p></Abas.Content>)}
              {pedido.opcoes.map((o) => (
                <Abas.Content key={o.id} value={o.id} className="aba-conteudo">
                  <NumerosOpcao opcao={o} meta={pedido.campos.meta.valor} unidade={unidade} exemplo={!!pedido.exemplo} versao={pedido.versao_modelo} />
                  <TabelaLote opcao={o} andamento={andamento} escolher={setEscolhida} escolhida={escolhida} />
                </Abas.Content>
              ))}
            </Abas.Root>
          </section>

          <QuadroDestrava pedido={pedido} opcao={aba} />

          {!pedido.opcao_escolhida ? (
            <section className="secao-painel" aria-labelledby="solicitar-titulo">
              <h2 id="solicitar-titulo">Contato somente na fase final</h2>
              <p>Primeiro compare os lotes e confira o que falta resolver. O contato com os donos fica para a fase final, pela Raíz. Nenhum nome, CPF ou contato aparece neste pedido.</p>
              <button type="button" className="botao" disabled aria-describedby="contato-pendente">Solicitar interesse dos donos</button>
              <p id="contato-pendente" className="legenda-frase">Esta etapa ainda não inicia contatos.</p>
            </section>
          ) : (
            <PainelAndamento pedido={pedido} andamento={andamento} unidade={unidade} />
          )}
        </aside>
        <div className={`pedido-mapa${!fazendas.length ? " pedido-mapa-pendente" : ""}`}>
          {!fazendas.length ? <h2>Mapa dos lotes</h2> : brasil.dado ? (
            <MapaLote base={brasil.dado.base} fazendas={fazendas} modo={andamento ? "interesse" : "opcoes"} escolhida={escolhida} aoEscolher={setEscolhida} aoEscolherOpcao={setAba} opcaoAtiva={aba} />
          ) : (
            <div className="mapa-carregando">
              <span className="girando" aria-hidden="true" /> Carregando o mapa
            </div>
          )}
          <LegendaLote andamento={!!andamento} />
          {!fazendas.length && <p className="aviso" role="status">Os desenhos dependem de consulta autorizada e cobertura geográfica. Quando o motor entregar os contornos autorizados, as três opções aparecerão nas cores da legenda.</p>}
        </div>
      </div>
    </Moldura>
  )
}

function Moldura({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  useEffect(() => {
    document.title = `${titulo}: Raíz`
  }, [titulo])
  return (
    <div className="tela-pedidos tela-pedido">
      <Cabecalho atual="pedidos" />
      <main id="conteudo" tabIndex={-1} className="pedido-main">{children}</main>
    </div>
  )
}

function Alertas({ pedido }: { pedido: Pedido }) {
  return (
    <div className="alertas-pedido">
      <p className="legenda-frase">
        <Bell size={16} aria-hidden="true" /> Avisamos aqui quando aparecer fazenda que melhora o lote ou quando uma fazenda do grupo
        tiver desmatamento, embargo ou matrícula cancelada.
      </p>
      {pedido.alertas.length > 0 && (
        <ul className="lista-alertas" aria-label="Alertas do pedido">
          {pedido.alertas.map((a, k) => (
            <li key={k} className={a.tipo}>
              {a.tipo === "fazenda_com_problema" ? <TriangleAlert size={18} aria-hidden="true" /> : <Bell size={18} aria-hidden="true" />}
              <span>
                {a.texto}
                {a.cod_imovel && (
                  <>
                    {" "}
                    <a href={linkFazenda(a.cod_imovel)}>Ver a fazenda</a>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function QuadroBase({ pedido, unidade }: { pedido: Pedido; unidade: string }) {
  const b = pedido.base
  const meta = pedido.campos.meta
  return (
    <section className="secao-painel quadro-base" aria-labelledby="base-titulo">
      <h2 id="base-titulo">Quanto existe na nossa base</h2>
      <p className="frase">
        {b.fazendas
          ? `${fmtInt(b.fazendas)} ${b.fazendas === 1 ? "fazenda apta atende" : "fazendas aptas atendem"} o pedido: ${fmtHa(b.hectares)} e ${fmtFaixaMeta(b.creditos, "creditos")} líquidos.`
          : "Nenhuma fazenda da base atende o pedido como está."}
      </p>
      <FaixaBarra faixa={b.creditos} meta={meta.tipo === "creditos" ? meta.valor : undefined} rotulo={`Créditos na base, ${fmtFaixa(b.creditos)}, contra a meta de ${fmtMeta(meta.valor, meta.tipo)}`} />
      <p className="legenda-frase">
        Barra clara: de P10 a P90; ponto: P50{meta.tipo === "creditos" ? "; traço: a meta" : ""}. {b.observacao}
      </p>
      {!b.alcanca_meta && (
        <div className="falta">
          <p className="aviso-forte">
            Falta {fmtInt(b.falta)} {unidade} para a meta de {fmtMeta(meta.valor, meta.tipo)}.
          </p>
          {b.afrouxar.length > 0 && (
            <>
              <h3>O que afrouxar</h3>
              <ul className="lista-afrouxar">
                {b.afrouxar.map((a) => (
                  <li key={a.texto}>
                    {a.texto}: <strong>mais {fmtInt(a.ganho)} {unidade}</strong>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      {b.fazendas > 0 && (
        <div className="base-tabelas">
          <table className="tabela-simples">
            <caption>Por caminho da terra</caption>
            <thead>
              <tr>
                <th scope="col">Caminho</th>
                <th scope="col" className="num">
                  Fazendas
                </th>
                <th scope="col" className="num">
                  Créditos (P50)
                </th>
              </tr>
            </thead>
            <tbody>
              {b.por_caminho.map((c) => (
                <tr key={c.caminho}>
                  <th scope="row">{ROTULO_CAMINHO[c.caminho]}</th>
                  <td className="num">{fmtInt(c.fazendas)}</td>
                  <td className="num">{fmtInt(c.creditos)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table className="tabela-simples">
            <caption>Por interesse do dono</caption>
            <thead>
              <tr>
                <th scope="col">Interesse</th>
                <th scope="col" className="num">
                  Fazendas
                </th>
                <th scope="col" className="num">
                  Créditos (P50)
                </th>
              </tr>
            </thead>
            <tbody>
              {b.por_interesse.map((c) => (
                <tr key={c.nivel}>
                  <th scope="row">{ROTULO_INTERESSE[c.nivel]}</th>
                  <td className="num">{fmtInt(c.fazendas)}</td>
                  <td className="num">{fmtInt(c.creditos)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function NumerosOpcao({ opcao: o, meta, unidade, exemplo, versao }: { opcao: Opcao; meta: number; unidade: string; exemplo: boolean; versao: string }) {
  const reservas = o.itens.filter((i) => i.papel === "reserva").length
  return (
    <div className="numeros-opcao">
      <p className="criterio">{ROTULO_OPCAO[o.id].criterio.replace(/^./, (c) => c.toUpperCase())}.</p>
      {!o.alcanca_meta && (
        <p className="aviso-forte">
          Esta opção não fecha a meta: faltam {fmtInt(o.falta)} {unidade}.
        </p>
      )}
      {o.abaixo_equilibrio?.aviso && <p className="aviso-forte">{o.abaixo_equilibrio.aviso}</p>}
      <div className="numero-principal">
        <span className="rotulo">Créditos líquidos</span>
        <span className="valor">{fmtFaixa(o.creditos)}</span>
        <FaixaBarra faixa={o.creditos} meta={unidade === "créditos" ? meta : undefined} rotulo={`Créditos da opção: ${fmtFaixa(o.creditos)}`} />
      </div>
      <dl className="ficha-numeros">
        <div>
          <dt>Hectares</dt>
          <dd>{fmtHa(o.hectares)}</dd>
        </div>
        <div>
          <dt>Fazendas</dt>
          <dd>
            {fmtInt(o.fazendas)}
            {o.pequenas > 0 && <small> ({fmtInt(o.pequenas)} pequenas, agrupadas)</small>}
          </dd>
        </div>
        <div>
          <dt>De reserva</dt>
          <dd>{fmtInt(reservas)}</dd>
        </div>
        <div>
          <dt>Custo por crédito</dt>
          <dd>
            {fmtUsd(o.custo_usd_credito.p50)} <small>(de {fmtUsd(o.custo_usd_credito.p10)} a {fmtUsd(o.custo_usd_credito.p90)})</small>
          </dd>
        </div>
        <div>
          <dt>TIR</dt>
          <dd>
            {fmtTir(o.tir.p50)} <small>(de {fmtTir(o.tir.p10).replace(" ao ano", "")} a {fmtTir(o.tir.p90).replace(" ao ano", "")})</small>
          </dd>
        </div>
        <div>
          <dt>Pico de caixa</dt>
          <dd>{fmtUsd(o.pico_caixa_usd)}</dd>
        </div>
        <div>
          <dt>Multa esperada</dt>
          <dd>{fmtUsd(o.multa_esperada_usd)}</dd>
        </div>
      </dl>
      <table className="tabela-simples marcos-pedido">
        <caption>Chance de cumprir cada marco</caption>
        <thead>
          <tr>
            <th scope="col">Ano</th>
            <th scope="col" className="num">
              Da meta
            </th>
            <th scope="col" className="num">
              Chance
            </th>
          </tr>
        </thead>
        <tbody>
          {o.marcos.map((m) => (
            <tr key={m.ano}>
              <th scope="row">Ano {m.ano}</th>
              <td className="num">{fmtPct(m.fracao)}</td>
              <td className="num">{fmtPct(m.chance)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mistura">
        <strong>Caminho da terra:</strong> {o.mistura_terra.map((m) => `${ROTULO_CAMINHO[m.caminho].toLowerCase()} ${fmtPct(m.fracao)}`).join(", ")}.{" "}
        <strong>Restauração:</strong> {o.metodos.map((m) => `${ROTULO_METODO[m.metodo].toLowerCase()} em ${m.fazendas === 1 ? "1 fazenda" : `${fmtInt(m.fazendas)} fazendas`}`).join(", ")}.
      </p>
      <details className="como-calculamos-pedido">
        <summary>Ver como calculamos</summary>
        {exemplo ? <p>
          Crédito líquido = potencial de captura do motor (carbono_tco2_ano) em {PREMISSAS.anos} anos, menos {fmtPct(PREMISSAS.desconto_liquido)} de linha
          de base, vazamento e reserva de não permanência; faixa de {fmtPct(PREMISSAS.p10)} a {fmtPct(PREMISSAS.p90)} do P50. Custo por hectare
          restaurado: regeneração assistida {fmtUsd(PREMISSAS.custo_ha_usd.regeneracao_assistida)}, semeadura direta{" "}
          {fmtUsd(PREMISSAS.custo_ha_usd.semeadura_direta)}, plantio total {fmtUsd(PREMISSAS.custo_ha_usd.plantio_total)}, mais um custo fixo por
          fazenda. A mais segura fecha a meta no P10. Valores exatos: {fmtInt(o.creditos.p10)}, {fmtInt(o.creditos.p50)} e {fmtInt(o.creditos.p90)} {unidade}.
        </p> : <p>Números entregues pelo motor, modelo {versao}. Créditos líquidos P10: {fmtInt(o.creditos.p10)}, P50: {fmtInt(o.creditos.p50)}, P90: {fmtInt(o.creditos.p90)}. As faixas de custo e retorno são as publicadas para este lote; não são calculadas pela tela.</p>}
      </details>
    </div>
  )
}

function TabelaLote({ opcao, andamento, escolher, escolhida }: { opcao: Opcao; andamento: Andamento | null; escolher: (c: string) => void; escolhida: string | null }) {
  const nivel = new Map(andamento?.fazendas.map((f) => [f.cod_imovel, f.interesse]) ?? [])
  const [todas, setTodas] = useState(false)
  const lista = todas ? opcao.itens : opcao.itens.slice(0, 12)
  return (
    <div className="tabela-rolagem">
      <table className="tabela-simples tabela-lote">
        <caption>Fazendas da opção (toque para ver a ficha)</caption>
        <thead>
          <tr>
            <th scope="col">Fazenda</th>
            <th scope="col">Papel</th>
            <th scope="col" className="num">
              Créditos
            </th>
            <th scope="col">Nível</th>
          </tr>
        </thead>
        <tbody>
          {lista.map((i) => {
            const selo = seloDeNivel(i.caminho, nivel.get(i.cod_imovel) ?? i.interesse)
            return (
              <tr key={i.cod_imovel} aria-selected={escolhida === i.cod_imovel}>
                <th scope="row">
                  <button type="button" className="link" onClick={() => escolher(i.cod_imovel)}>
                    <code>{abreviarCar(i.cod_imovel)}</code>
                  </button>
                  <small>{i.municipio}</small>
                </th>
                <td>{i.papel === "lote" ? (i.trocou ? "Lote (troca)" : "Lote") : "Reserva"}</td>
                <td className="num">{fmtInt(i.creditos.p50)}</td>
                <td>
                  <span className={`selo-nivel ${selo.classe}`}>{selo.texto}</span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {opcao.itens.length > 12 && (
        <button type="button" className="link" onClick={() => setTodas(!todas)}>
          {todas ? "Mostrar menos" : `Mostrar as ${fmtInt(opcao.itens.length)} fazendas`}
        </button>
      )}
    </div>
  )
}

function FazendaEscolhida({
  item,
  nivel,
  opcao,
  podeMudar,
  mudar,
  fechar,
}: {
  item: FazendaDoLote
  nivel: NivelInteresse
  opcao: Opcao
  podeMudar: boolean
  mudar: (acao: "tirar" | "trocar", cod: string, por?: string) => void
  fechar: () => void
}) {
  const [trocando, setTrocando] = useState(false)
  const reservas = opcao.itens.filter((i) => i.papel === "reserva").slice(0, 3)
  // a ficha aparece onde a pessoa está olhando (no celular, a lista fica longe do topo)
  const secao = useRef<HTMLElement>(null)
  useEffect(() => {
    secao.current?.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" })
  }, [item.cod_imovel])
  const selo = seloDeNivel(item.caminho, nivel)
  return (
    <section className="secao-painel fazenda-escolhida" aria-labelledby="fe-titulo" ref={secao}>
      <div className="secao-cabeca">
        <h2 id="fe-titulo">
          <code>{abreviarCar(item.cod_imovel)}</code>
        </h2>
        <button type="button" className="link" onClick={fechar}>
          Fechar
        </button>
      </div>
      <p>
        {item.papel === "lote" ? "No lote" : "De reserva"}, em {item.municipio} ({item.uf}). <span className={`selo-nivel ${selo.classe}`}>{selo.texto}</span>
      </p>
      <dl className="ficha-numeros">
        <div>
          <dt>Pode voltar a ser mata</dt>
          <dd>{fmtHa(item.hectares)}</dd>
        </div>
        <div>
          <dt>Créditos líquidos</dt>
          <dd>{fmtFaixa(item.creditos)}</dd>
        </div>
        <div>
          <dt>Restauração</dt>
          <dd>{ROTULO_METODO[item.metodo]}</dd>
        </div>
        <div>
          <dt>Caminho da terra</dt>
          <dd>{ROTULO_CAMINHO[item.caminho]}</dd>
        </div>
        <div>
          <dt>Custo por crédito</dt>
          <dd>{fmtUsd(item.custo_usd_credito)}</dd>
        </div>
        <div>
          <dt>Interesse do dono</dt>
          <dd>{ROTULO_INTERESSE[nivel]}</dd>
        </div>
      </dl>
      {item.pequena && <p className="legenda-frase">Pequena propriedade: entra agrupada com as vizinhas.</p>}
      <div className="acoes">
        <a className="botao" href={linkFazenda(item.cod_imovel)}>
          Abrir a ficha
        </a>
        {podeMudar && item.papel === "lote" && (
          <>
            <button type="button" className="botao" onClick={() => mudar("tirar", item.cod_imovel)}>
              Tirar do lote
            </button>
            <button type="button" className="botao" onClick={() => setTrocando(!trocando)} aria-expanded={trocando} disabled={!reservas.length}>
              Trocar
            </button>
          </>
        )}
      </div>
      {trocando && (
        <ul className="lista-trocas" aria-label="Trocar por uma fazenda de reserva">
          {reservas.map((r) => (
            <li key={r.cod_imovel}>
              <span>
                <code>{abreviarCar(r.cod_imovel)}</code> <small>{fmtInt(r.creditos.p50)} créditos, {fmtUsd(r.custo_usd_credito)} por crédito</small>
              </span>
              <button type="button" className="botao" onClick={() => mudar("trocar", item.cod_imovel, r.cod_imovel)}>
                Trocar por esta
              </button>
            </li>
          ))}
        </ul>
      )}
      {!podeMudar && item.papel === "lote" && <p className="legenda-frase">Com a busca de interesse em andamento, quem troca as fazendas é a Raíz, quando um dono recusa.</p>}
    </section>
  )
}

function PainelAndamento({ pedido, andamento: a, unidade }: { pedido: Pedido; andamento: Andamento | null; unidade: string }) {
  const [agora, setAgora] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setAgora(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])
  if (!a) return <Estado tipo="carregando" titulo="Começando a busca de interesse" />
  const meta = Math.max(1, a.meta)
  const parte = (v: number) => Math.min(1, v / meta)
  const proxima = a.proxima_onda_em ? Math.max(0, Math.round((new Date(a.proxima_onda_em).getTime() - agora) / 1000)) : null
  return (
    <section className="secao-painel andamento" aria-labelledby="andamento-titulo" aria-live="polite">
      <h2 id="andamento-titulo">Busca de interesse dos donos</h2>
      {a.status === "grupo_pronto" && (
        <div className="aviso aviso-pronto" role="status">
          <Bell size={20} aria-hidden="true" />
          <div>
            <strong>Grupo pronto.</strong> {fmtMeta(a.com_interessado, pedido.campos.meta.tipo)} com dono interessado, {fmtPct(parte(a.com_interessado))} da meta. Avisamos
            também por e-mail e WhatsApp.
            <p>
              <a className="botao principal" href={linkGrupo(pedido.id)}>
                Ver o grupo e reservar
              </a>
            </p>
          </div>
        </div>
      )}
      {(pedido.status === "reservado" || pedido.status === "reserva_vencida") && (
        <p>
          <a href={linkGrupo(pedido.id)}>Ver o grupo reservado</a>
        </p>
      )}
      {a.faltou && (
        <div className="falta">
          <p className="aviso-forte">
            As fazendas acabaram antes da meta: faltou {fmtInt(a.faltou.falta)} {unidade}.
          </p>
          <ul className="lista-afrouxar">
            {a.faltou.afrouxar.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="barra-meta" role="img" aria-label={`Da meta: ${fmtPct(parte(a.com_interessado))} com dono interessado, ${fmtPct(parte(a.com_aceite))} com aceite e ${fmtPct(parte(a.com_contrato))} com contrato`}>
        <span className="bm-interessado" style={{ width: `${parte(a.com_interessado) * 100}%` }} />
        <span className="bm-aceite" style={{ width: `${parte(a.com_aceite) * 100}%` }} />
        <span className="bm-contrato" style={{ width: `${parte(a.com_contrato) * 100}%` }} />
      </div>
      <dl className="numeros numeros-andamento">
        <div>
          <dt>
            <i className="bm-interessado" aria-hidden="true" /> Interessado
          </dt>
          <dd>
            <NumberFlow value={parte(a.com_interessado)} format={{ style: "percent", maximumFractionDigits: 0 }} locales="pt-BR" />
          </dd>
        </div>
        <div>
          <dt>
            <i className="bm-aceite" aria-hidden="true" /> Com aceite
          </dt>
          <dd>
            <NumberFlow value={parte(a.com_aceite)} format={{ style: "percent", maximumFractionDigits: 0 }} locales="pt-BR" />
          </dd>
        </div>
        <div>
          <dt>
            <i className="bm-contrato" aria-hidden="true" /> Com contrato
          </dt>
          <dd>
            <NumberFlow value={parte(a.com_contrato)} format={{ style: "percent", maximumFractionDigits: 0 }} locales="pt-BR" />
          </dd>
        </div>
      </dl>
      <p className="legenda-frase">Porcentagem da meta de {fmtMeta(a.meta, pedido.campos.meta.tipo)}; quem tem contrato também conta em aceite e em interessado.</p>
      <p>
        {fmtInt(a.contatados)} {a.contatados === 1 ? "dono contatado" : "donos contatados"}, {fmtInt(a.recusas)} {a.recusas === 1 ? "recusa" : "recusas"} e{" "}
        {fmtInt(a.sem_resposta)} sem resposta no prazo. Quem recusa ou não responde sai, e entra a próxima fazenda (primeiro as de reserva).
        {proxima !== null && ` Próxima onda em ${proxima < 90 ? `${fmtInt(proxima)} s` : `${fmtInt(proxima / 60)} min`}.`}
      </p>
      {a.motivos.length > 0 && (
        <>
          <h3>Por que recusaram</h3>
          <ul className="lista-motivos">
            {a.motivos.map((m) => (
              <li key={m.motivo}>
                {m.motivo}: <strong>{m.fazendas === 1 ? "1 fazenda" : `${fmtInt(m.fazendas)} fazendas`}</strong>
              </li>
            ))}
          </ul>
        </>
      )}
      <h3>Ondas de contato</h3>
      <ol className="lista-ondas">
        {a.ondas.map((o) => (
          <li key={o.numero}>
            <strong>Onda {o.numero}</strong>, {new Date(o.data).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}:{" "}
            {o.contatados === 1 ? "1 dono contatado" : `${fmtInt(o.contatados)} donos contatados`} por {juntar(o.canais)}.
          </li>
        ))}
      </ol>
      <p className="legenda-frase">Ninguém aqui vê nome, CPF ou contato do dono: o contato passa pela Raíz, com o termo de uso de dados (LGPD).</p>
    </section>
  )
}

const juntar = (l: string[]) => (l.length <= 1 ? (l[0] ?? "") : `${l.slice(0, -1).join(", ")} e ${l[l.length - 1]}`)

function LegendaLote({ andamento }: { andamento: boolean }) {
  if (!andamento)
    return (
      <p className="mapa-legenda-fixa">
        {IDS.map((id) => <span key={id} className={`opcao-marca opcao-${id}`}><i aria-hidden="true" />{ROTULO_OPCAO[id].nome}</span>)}
        <span>Contínuo: mais barata. Tracejado: mais segura. Pontilhado: mais compacta. Uma fazenda pode aparecer em mais de uma opção.</span>
        <span><i className="lg-reserva" aria-hidden="true" /> Reserva com listras deitadas.</span>
      </p>
    )
  const niveis: NivelInteresse[] = ["sem_contato", "contatado", "interessado", "aceite_fase1", "contrato_firme", "recusou"]
  return (
    <p className="mapa-legenda-fixa">
      {niveis.map((n) => (
        <span key={n}>
          <i className={`lg-nivel n-${n}`} aria-hidden="true" /> {ROTULO_INTERESSE[n]}
        </span>
      ))}
      <span>
        <i className="lg-troca" aria-hidden="true" /> Entrou no lugar de quem recusou
      </span>
    </p>
  )
}

