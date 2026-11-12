import { Bell, Plus } from "lucide-react"
import { useEffect, useState } from "react"
import { fmtPct } from "../../../compartilhado/formato"
import { dataLonga } from "../../../compartilhado/pedidos/texto"
import type { ResumoPedido } from "../../../compartilhado/pedidos/tipos"
import { avisarSessao, pedidos, useSessao } from "../pedidos"
import { Cabecalho } from "../partes/Cabecalho"
import { Estado } from "../partes/Estado"
import { AvisoExemplo } from "../partes/pedido/AvisoExemplo"
import { SeloStatus } from "../partes/pedido/SeloStatus"
import { linkGrupo, linkNovoPedido, linkPedido } from "../rota"

/** "Meus pedidos": cada pedido com o status (buscando interesse, grupo pronto, reservado até tal dia, contrato). */
export function MeusPedidos() {
  const sessao = useSessao()
  const [lista, setLista] = useState<ResumoPedido[] | null>(null)
  const [erro, setErro] = useState<string | null>(null)

  useEffect(() => {
    let vivo = true
    const ler = () =>
      pedidos.listar().then(
        (l) => vivo && (setLista(l), setErro(null)),
        (e: Error) => vivo && setErro(e.message),
      )
    ler()
    // a busca de interesse anda sozinha: a lista se atualiza
    const t = setInterval(ler, 10_000)
    return () => {
      vivo = false
      clearInterval(t)
    }
  }, [])

  const prontos = (lista ?? []).filter((p) => p.status === "grupo_pronto")
  return (
    <div className="tela-pedidos">
      <Cabecalho atual="pedidos" />
      <main id="conteudo" tabIndex={-1} className="pagina pagina-media">
        <div className="secao-cabeca">
          <h1>Meus pedidos</h1>
          <a className="botao principal" href={linkNovoPedido}>
            <Plus size={20} aria-hidden="true" /> Novo pedido
          </a>
        </div>
        <p className="legenda-frase">
          Entrou como {sessao?.email}.{" "}
          <button
            type="button"
            className="link"
            onClick={() => {
              pedidos.sair()
              avisarSessao()
              location.hash = "#/"
            }}
          >
            Sair
          </button>
        </p>
        <AvisoExemplo ativo={pedidos.exemplo} />
        {prontos.map((p) => (
          <p key={p.id} className="aviso aviso-pronto" role="status">
            <Bell size={20} aria-hidden="true" />
            <span>
              <strong>Grupo pronto</strong> em "{p.titulo}". Avisamos também por e-mail e WhatsApp.{" "}
              <a href={linkGrupo(p.id)}>Ver o grupo e reservar</a>
            </span>
          </p>
        ))}
        {erro ? (
          <Estado tipo="erro" titulo="Não deu para ler seus pedidos.">
            <p>{erro}</p>
          </Estado>
        ) : !lista ? (
          <Estado tipo="carregando" titulo="Lendo seus pedidos" />
        ) : !lista.length ? (
          <Estado tipo="vazio" titulo="Nenhum pedido ainda.">
            <p>Diga quantos créditos precisa, onde e em que prazo. A Raíz mostra quanto existe na base e monta o melhor lote no mapa.</p>
            <a href={linkNovoPedido}>Fazer o primeiro pedido</a>
          </Estado>
        ) : (
          <ol className="lista-pedidos">
            {lista.map((p) => (
              <li key={p.id}>
                <a href={linkPedido(p.id)}>
                  <span className="lp-titulo">
                    <strong>{p.titulo}</strong>
                    <small>Pedido de {dataLonga(p.criado_em)}</small>
                  </span>
                  <span className="lp-status">
                    <SeloStatus status={p.status} reservadoAte={p.reservado_ate} />
                    {p.com_interesse !== null && p.status === "buscando_interesse" && <small>{fmtPct(p.com_interesse)} da meta com dono interessado</small>}
                    {p.alertas > 0 && <small className="lp-alerta">{p.alertas === 1 ? "1 alerta" : `${p.alertas} alertas`}</small>}
                  </span>
                </a>
              </li>
            ))}
          </ol>
        )}
      </main>
    </div>
  )
}
