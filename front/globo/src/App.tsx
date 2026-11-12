import { Principal } from "./telas/Principal"
import { useRota } from "./rota"

export default function App() {
  const rota = useRota()
  if (rota.tela === "fazenda") return <p style={{ padding: 32 }}>Ficha da fazenda {rota.car}: em construção.</p>
  return <Principal key={rota.municipio} municipio={rota.municipio} />
}
