import { useRota } from "./rota"
import { useSessao } from "./pedidos"
import { Entrar } from "./telas/Entrar"
import { Explorar } from "./telas/Explorar"
import { Calendario } from "./telas/Calendario"
import { Fazenda } from "./telas/Fazenda"
import { Grupo } from "./telas/Grupo"
import { MeusPedidos } from "./telas/MeusPedidos"
import { NovoPedido } from "./telas/NovoPedido"
import { PedidoTela } from "./telas/PedidoTela"

/**
 * A entrada é o mapa do Brasil, sem abertura: quem chega já vê os estados pintados pelo que a Raíz já leu. Tocar num
 * estado aproxima e carrega só ele; a busca e o toque num município levam ao painel dele; o código do CAR leva direto
 * à ficha. A área logada (pedido de lote da cena-alvo) pede a entrada por e-mail com link.
 */
export default function App() {
  const rota = useRota()
  const sessao = useSessao()
  if (rota.tela === "calendario") return <Calendario key={rota.car || "todos"} car={rota.car} />
  if (rota.tela === "fazenda") return <Fazenda key={rota.car} car={rota.car} />
  if (rota.tela === "entrar") return <Entrar token={rota.token} />
  if (rota.tela === "pedidos" || rota.tela === "pedido-novo" || rota.tela === "pedido" || rota.tela === "grupo") {
    // sem sessão, entra primeiro e volta para onde ia
    if (!sessao) return <Entrar token={null} volta={location.hash} />
    if (rota.tela === "pedidos") return <MeusPedidos />
    if (rota.tela === "pedido-novo") return <NovoPedido />
    if (rota.tela === "grupo") return <Grupo key={rota.id} id={rota.id} />
    return <PedidoTela key={rota.id} id={rota.id} />
  }
  return (
    <Explorar municipio={rota.tela === "municipio" ? rota.municipio : null} uf={rota.tela === "estado" ? rota.uf : null} />
  )
}
