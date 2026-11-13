import { lazy, Suspense, useEffect, useRef } from "react"
import { useRota } from "./rota"
import { pedidos, useSessao } from "./pedidos"
import { Explorar } from "./telas/Explorar"

const AcertoModelo = lazy(() => import("./telas/AcertoModelo").then((m) => ({ default: m.AcertoModelo })))
const Entrar = lazy(() => import("./telas/Entrar").then((m) => ({ default: m.Entrar })))
const FichaTerra = lazy(() => import("./telas/FichaTerra").then((m) => ({ default: m.FichaTerra })))
const Prospeccao = lazy(() => import("./telas/Prospeccao").then((m) => ({ default: m.Prospeccao })))
const Grupo = lazy(() => import("./telas/Grupo").then((m) => ({ default: m.Grupo })))
const MeusPedidos = lazy(() => import("./telas/MeusPedidos").then((m) => ({ default: m.MeusPedidos })))
const NovoPedido = lazy(() => import("./telas/NovoPedido").then((m) => ({ default: m.NovoPedido })))
const PedidoTela = lazy(() => import("./telas/PedidoTela").then((m) => ({ default: m.PedidoTela })))
const Calendario = lazy(() => import("./telas/Calendario").then((m) => ({ default: m.Calendario })))

/**
 * A entrada é o mapa do Brasil, sem abertura: quem chega já vê os estados pintados pelo que a Raíz já leu. Tocar num
 * estado aproxima e carrega só ele; a busca e o toque num município levam ao painel dele; o código do CAR leva direto
 * à ficha. A área logada (pedido de lote da cena-alvo) pede a entrada por e-mail com link.
 */
function TelaAtual() {
  const rota = useRota()
  const primeira = useRef(true)
  useEffect(() => {
    if (primeira.current) { primeira.current = false; return }
    // A rota pode chegar em um chunk separado: espera o conteúdo, sem prender o teclado no carregamento.
    const focar = () => {
      const principal = document.querySelector<HTMLElement>('main:not([aria-busy="true"])')
      if (!principal) return false
      principal.tabIndex = -1
      principal.focus({ preventScroll: true })
      window.scrollTo(0, 0)
      return true
    }
    if (focar()) return
    const observer = new MutationObserver(() => { if (focar()) observer.disconnect() })
    observer.observe(document.getElementById("root")!, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [rota])
  const sessao = useSessao()
  if (rota.tela === "acerto") return <AcertoModelo />
  if (rota.tela === "calendario") return <Calendario key={rota.car || "todos"} car={rota.car} />
  if (rota.tela === "fazenda") return <FichaTerra key={`${rota.car}-${sessao?.token ?? "publica"}`} car={rota.car} />
  if (rota.tela === "prospeccao") return <Prospeccao key={sessao?.token ?? "publica"} />
  if (rota.tela === "entrar") return <Entrar token={rota.token} />
  if (rota.tela === "pedidos" || rota.tela === "pedido-novo" || rota.tela === "pedido" || rota.tela === "grupo") {
    // sem sessão, entra primeiro e volta para onde ia
    if (!sessao && (!pedidos.publica || rota.tela === "grupo")) return <Entrar token={null} volta={location.hash} />
    if (rota.tela === "pedidos") return <MeusPedidos key={sessao?.token ?? "publica"} />
    if (rota.tela === "pedido-novo") return <NovoPedido key={sessao?.token ?? "publica"} />
    if (rota.tela === "grupo") return <Grupo key={`${rota.id}-${sessao?.token ?? "publica"}`} id={rota.id} />
    return <PedidoTela key={`${rota.id}-${sessao?.token ?? "publica"}`} id={rota.id} />
  }
  return (
    <Explorar municipio={rota.tela === "municipio" ? rota.municipio : null} uf={rota.tela === "estado" ? rota.uf : null} />
  )
}

/** A entrada não baixa telas de consulta, pagamento e lote antes de serem abertas. */
export default function App() {
  return <Suspense fallback={<main id="conteudo" tabIndex={-1} className="pagina" aria-busy="true"><p role="status">Abrindo a tela…</p></main>}><TelaAtual /></Suspense>
}
