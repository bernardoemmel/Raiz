import { useRota } from "./rota"
import { Explorar } from "./telas/Explorar"
import { Fazenda } from "./telas/Fazenda"

/**
 * A entrada é o mapa do Brasil, sem abertura: quem chega já vê os estados pintados pelo que a Raíz já leu. Tocar num
 * estado aproxima e carrega só ele; a busca e o toque num município levam ao painel dele; o código do CAR leva direto
 * à ficha.
 */
export default function App() {
  const rota = useRota()
  if (rota.tela === "fazenda") return <Fazenda key={rota.car} car={rota.car} />
  return (
    <Explorar municipio={rota.tela === "municipio" ? rota.municipio : null} uf={rota.tela === "estado" ? rota.uf : null} />
  )
}
