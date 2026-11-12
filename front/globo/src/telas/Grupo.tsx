import NumberFlow from "@number-flow/react"
import * as Janela from "@radix-ui/react-dialog"
import { Copy, Lock, X } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { renderSVG } from "uqr"
import { COR } from "../../../compartilhado/cores"
import { abreviarCar, fmtHa, fmtInt, fmtPct } from "../../../compartilhado/formato"
import { grupoDe } from "../../../compartilhado/pedidos/exemplo"
import { dataCurta, dataLonga, fmtBrl, fmtMeta, ROTULO_INTERESSE, seloDeNivel, tituloDoPedido } from "../../../compartilhado/pedidos/texto"
import type { Andamento, Cobranca, FazendaDoLote, Pedido } from "../../../compartilhado/pedidos/tipos"
import { fonte, useCarga } from "../dados"
import { MapaLote } from "../mapa/MapaLote"
import { pedidos } from "../pedidos"
import { Cabecalho } from "../partes/Cabecalho"
import { Estado } from "../partes/Estado"
import { AvisoExemplo } from "../partes/pedido/AvisoExemplo"
import { SeloStatus } from "../partes/pedido/SeloStatus"
import { linkFazenda, linkPedido, linkPedidos } from "../rota"

/**
 * O grupo fechado: as fazendas com dono interessado que atendem o pedido. "Reservar este grupo" mostra o valor, o prazo
 * de exclusividade e que a reserva é abatida da conexão; abre o Pix (QR e copia e cola). Pago, o selo "Reservado até
 * dd/mm" com a contagem regressiva. Durante a reserva, as fazendas somem para os outros clientes.
 */
export function Grupo({ id }: { id: string }) {
  const [pedido, setPedido] = useState<Pedido | null | undefined>(undefined)
  const [andamento, setAndamento] = useState<Andamento | null | undefined>(undefined)
  const [cobranca, setCobranca] = useState<Cobranca | null>(null)
  const [pixAberto, setPixAberto] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const [escolhida, setEscolhida] = useState<string | null>(null)
  const brasil = useCarga(() => fonte.geo.brasil(), [])

  const ler = () =>
    Promise.all([pedidos.pedido(id), pedidos.andamento(id), pedidos.reserva(id)]).then(
      ([p, a, c]) => {
        setPedido(p)
        setAndamento(a)
        setCobranca(c)
        setErro(null)
      },
      (e: Error) => setErro(e.message),
    )
  useEffect(() => {
    ler()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  const grupo = useMemo(() => (andamento ? new Set(grupoDe(andamento)) : new Set<string>()), [andamento])
  // o grupo: quem tem dono interessado (ou mais), com o nível de agora
  const itens = useMemo<FazendaDoLote[]>(() => (andamento?.fazendas ?? []).filter((f) => grupo.has(f.cod_imovel)), [andamento, grupo])

  async function reservar() {
    setErro(null)
    try {
      setCobranca(await pedidos.reservar(id))
      setPixAberto(true)
    } catch (e) {
      setErro((e as Error).message)
    }
  }

  // com o Pix aberto, confere sozinho se o pagamento chegou
  useEffect(() => {
    if (!pixAberto || cobranca?.pago) return
    const t = setInterval(async () => {
      const c = await pedidos.reserva(id)
      if (c?.pago) {
        setCobranca(c)
        ler()
      }
    }, 4000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pixAberto, cobranca?.pago, id])

  if (pedido === undefined || andamento === undefined)
    return (
      <Moldura>
        {erro ? (
          <Estado tipo="erro" titulo="Não foi possível ler o grupo">
            <p>{erro.startsWith("429 ") ? "A empresa atingiu o limite de consultas. Aguarde um minuto e tente de novo." : erro}</p>
            <button type="button" className="botao" onClick={() => { setErro(null); void ler() }}>Tentar de novo</button>
          </Estado>
        ) : <Estado tipo="carregando" titulo="Lendo o grupo" />}
      </Moldura>
    )
  if (!pedido)
    return (
      <Moldura>
        <Estado tipo="erro" titulo="Não achamos este pedido.">
          <p>{erro ?? "Ele pode ser de outra conta."}</p>
          <a href={linkPedidos}>Voltar a Meus pedidos</a>
        </Estado>
      </Moldura>
    )
  if (!andamento?.grupo_pronto_em)
    return (
      <Moldura>
        <Migalhas pedido={pedido} />
        <Estado tipo="vazio" titulo="O grupo ainda não fechou.">
          <p>A busca de interesse continua. Avisamos aqui, por e-mail e por WhatsApp quando fechar.</p>
          <a href={linkPedido(id)}>Ver o andamento</a>
        </Estado>
      </Moldura>
    )

  const reservado = pedido.status === "reservado"
  const hectares = itens.reduce((s, i) => s + i.hectares, 0)
  return (
    <Moldura>
      <div className="pedido-corpo">
        <aside className="pedido-painel" aria-label="O grupo">
          <Migalhas pedido={pedido} />
          <h1>{reservado ? "Grupo reservado" : "Grupo pronto"}</h1>
          <div className="selos">
            <SeloStatus status={pedido.status} reservadoAte={pedido.reservado_ate} />
          </div>
          {reservado && pedido.reservado_ate && <ContagemRegressiva ate={pedido.reservado_ate} />}
          <AvisoExemplo ativo={!!pedido.exemplo} />
          <p className="frase">
            {fmtInt(itens.length)} {itens.length === 1 ? "fazenda" : "fazendas"} com dono interessado: {fmtHa(hectares)} e {fmtMeta(andamento.com_interessado, pedido.campos.meta.tipo)},{" "}
            {fmtPct(andamento.com_interessado / Math.max(1, andamento.meta))} da meta. Fechou em {dataLonga(andamento.grupo_pronto_em)}.
          </p>
          <dl className="numeros">
            <div>
              <dt>Com dono interessado</dt>
              <dd>
                <NumberFlow value={Math.min(1, andamento.com_interessado / Math.max(1, andamento.meta))} format={{ style: "percent", maximumFractionDigits: 0 }} locales="pt-BR" />
              </dd>
            </div>
            <div>
              <dt>Com aceite</dt>
              <dd>
                <NumberFlow value={Math.min(1, andamento.com_aceite / Math.max(1, andamento.meta))} format={{ style: "percent", maximumFractionDigits: 0 }} locales="pt-BR" />
              </dd>
            </div>
            <div>
              <dt>Com contrato</dt>
              <dd>
                <NumberFlow value={Math.min(1, andamento.com_contrato / Math.max(1, andamento.meta))} format={{ style: "percent", maximumFractionDigits: 0 }} locales="pt-BR" />
              </dd>
            </div>
          </dl>

          {!reservado && cobranca && (
            <section className="secao-painel reservar" aria-labelledby="reservar-titulo">
              <h2 id="reservar-titulo">Reservar este grupo</h2>
              <dl className="ficha-numeros">
                <div>
                  <dt>Valor da reserva</dt>
                  <dd className="destaque">{fmtBrl(cobranca.valor_brl)}</dd>
                </div>
                <div>
                  <dt>Prazo de exclusividade</dt>
                  <dd>{fmtInt(cobranca.prazo_dias)} dias</dd>
                </div>
              </dl>
              <p>
                Durante o prazo, estas fazendas ficam invisíveis para os outros clientes e você negocia com elas pela Raíz. {cobranca.abatimento}
              </p>
              {pedido.status === "reserva_vencida" && <p className="aviso-forte">A reserva anterior venceu sem contrato e o grupo voltou para a base.</p>}
              <button type="button" className="botao principal grande" onClick={reservar}>
                <Lock size={20} aria-hidden="true" /> Reservar este grupo
              </button>
              {erro && (
                <p className="erro-campo" role="alert">
                  {erro}
                </p>
              )}
            </section>
          )}

          {reservado && (
            <p className="aviso">
              <Lock size={20} aria-hidden="true" />
              <span>
                Estas fazendas não aparecem para nenhum outro cliente até {dataLonga(pedido.reservado_ate!)}. A negociação passa pela Raíz; o valor da reserva é
                abatido da conexão por hectare quando o contrato fechar.
              </span>
            </p>
          )}

          <section className="secao-painel" aria-labelledby="grupo-lista">
            <h2 id="grupo-lista">Fazendas do grupo</h2>
            <div className="tabela-rolagem">
              <table className="tabela-simples tabela-lote">
                <thead>
                  <tr>
                    <th scope="col">Fazenda</th>
                    <th scope="col" className="num">
                      Hectares
                    </th>
                    <th scope="col">Interesse</th>
                    <th scope="col">Nível</th>
                  </tr>
                </thead>
                <tbody>
                  {itens.map((i) => {
                    const n = i.interesse
                    const selo = seloDeNivel(i.caminho, n)
                    return (
                      <tr key={i.cod_imovel} aria-selected={escolhida === i.cod_imovel}>
                        <th scope="row">
                          <a href={linkFazenda(i.cod_imovel)}>
                            <code>{abreviarCar(i.cod_imovel)}</code>
                          </a>
                          <small>{i.municipio}</small>
                        </th>
                        <td className="num">{fmtHa(i.hectares, false)}</td>
                        <td>{ROTULO_INTERESSE[n]}</td>
                        <td>
                          <span className={`selo-nivel ${selo.classe}`}>{selo.texto}</span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="legenda-frase">Sem nome, CPF ou contato do dono: o contato passa pela Raíz.</p>
          </section>
        </aside>
        <div className="pedido-mapa">
          {brasil.dado && <MapaLote base={brasil.dado.base} fazendas={itens} modo="interesse" escolhida={escolhida} aoEscolher={setEscolhida} />}
        </div>
      </div>

      <Janela.Root open={pixAberto} onOpenChange={setPixAberto}>
        <Janela.Portal>
          <Janela.Overlay className="janela-fundo" />
          <Janela.Content className="janela janela-pix" aria-describedby="pix-descricao">
            <div className="secao-cabeca">
              <Janela.Title>{cobranca?.pago ? "Reserva paga" : "Pague a reserva com Pix"}</Janela.Title>
              <Janela.Close className="botao" aria-label="Fechar">
                <X size={20} aria-hidden="true" />
              </Janela.Close>
            </div>
            {cobranca && <ConteudoPix cobranca={cobranca} pedido={pedido} aoPagar={() => ler()} />}
          </Janela.Content>
        </Janela.Portal>
      </Janela.Root>
    </Moldura>
  )
}

function ConteudoPix({ cobranca, pedido, aoPagar }: { cobranca: Cobranca; pedido: Pedido; aoPagar: () => void }) {
  const [copiado, setCopiado] = useState(false)
  const [conferindo, setConferindo] = useState(false)
  const qr = useMemo(
    () => (cobranca.pix ? renderSVG(cobranca.pix.copia_e_cola, { border: 2, pixelSize: 6, blackColor: COR.tinta, whiteColor: COR.superficie }) : ""),
    [cobranca.pix],
  )
  if (cobranca.pago)
    return (
      <div id="pix-descricao">
        <p className="frase">Pagamento recebido. O grupo está reservado até {dataLonga(cobranca.reservado_ate!)}.</p>
        <Janela.Close className="botao principal">Ver o grupo reservado</Janela.Close>
      </div>
    )
  if (!cobranca.pix) return <Estado tipo="carregando" titulo="Gerando o Pix" />
  return (
    <div id="pix-descricao" className="pix">
      <p>
        <strong>{fmtBrl(cobranca.valor_brl)}</strong> para reservar o grupo por {fmtInt(cobranca.prazo_dias)} dias. Abra o app do banco, escolha Pix e leia o código
        ou cole o texto.
      </p>
      {cobranca.exemplo && <p className="aviso aviso-exemplo">Pix de exemplo: este código não paga nada. O back-end gera o Pix de verdade.</p>}
      {cobranca.modo_teste && <p className="aviso aviso-exemplo">Pix de teste: este código não paga nada.</p>}
      <div className="pix-qr" role="img" aria-label="Código QR do Pix" dangerouslySetInnerHTML={{ __html: qr }} />
      <label className="campo">
        <span>Pix copia e cola</span>
        <textarea readOnly rows={3} value={cobranca.pix.copia_e_cola} onFocus={(e) => e.currentTarget.select()} />
      </label>
      <div className="acoes">
        <button
          type="button"
          className="botao"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(cobranca.pix!.copia_e_cola)
              setCopiado(true)
            } catch {
              setCopiado(false)
            }
          }}
        >
          <Copy size={20} aria-hidden="true" /> {copiado ? "Copiado" : "Copiar o código"}
        </button>
        {pedidos.pagarExemplo && (
          <button
            type="button"
            className="botao principal"
            disabled={conferindo}
            onClick={async () => {
              setConferindo(true)
              await pedidos.pagarExemplo!(pedido.id)
              aoPagar()
            }}
          >
            Simular o pagamento (exemplo)
          </button>
        )}
      </div>
      <p className="legenda-frase">
        {cobranca.pix.expira_em && <>O código vale até {new Date(cobranca.pix.expira_em).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}. </>}
        Esta tela confere sozinha quando o banco avisar o pagamento.
      </p>
    </div>
  )
}

/** "Faltam 59 dias, 23 horas e 12 minutos", que anda a cada minuto */
function ContagemRegressiva({ ate }: { ate: string }) {
  const [agora, setAgora] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setAgora(Date.now()), 30_000)
    return () => clearInterval(t)
  }, [])
  const resto = Math.max(0, new Date(ate).getTime() - agora)
  const dias = Math.floor(resto / 86_400_000)
  const horas = Math.floor((resto % 86_400_000) / 3_600_000)
  const minutos = Math.floor((resto % 3_600_000) / 60_000)
  return (
    <p className="contagem" role="timer" aria-live="off">
      <Lock size={18} aria-hidden="true" /> Reservado até {dataCurta(ate)}: faltam {dias === 1 ? "1 dia" : `${fmtInt(dias)} dias`}, {horas === 1 ? "1 hora" : `${fmtInt(horas)} horas`} e{" "}
      {minutos === 1 ? "1 minuto" : `${fmtInt(minutos)} minutos`}.
    </p>
  )
}

function Migalhas({ pedido }: { pedido: Pedido }) {
  return (
    <ol className="migalhas" aria-label="Onde você está">
      <li>
        <a href={linkPedidos}>Meus pedidos</a>
      </li>
      <li>
        <a href={linkPedido(pedido.id)}>{tituloDoPedido(pedido.campos)}</a>
      </li>
      <li aria-current="page">Grupo</li>
    </ol>
  )
}

function Moldura({ children }: { children: React.ReactNode }) {
  return (
    <div className="tela-pedidos tela-pedido">
      <Cabecalho atual="pedidos" />
      <main className="pedido-main">{children}</main>
    </div>
  )
}
