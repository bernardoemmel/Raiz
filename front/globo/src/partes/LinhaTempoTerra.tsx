import type { FichaTerraDados } from "../../../compartilhado/prospeccao"
import { dataTerra, numeroTerra } from "../prospeccao"

const USOS = { mata: "Mata", pasto: "Pasto", lavoura: "Lavoura", agua: "Água" } as const

/** A cor ajuda a leitura; a mesma medida e a proveniência ficam escritas e acessíveis por teclado. */
export function LinhaTempoTerra({ ficha }: { ficha: FichaTerraDados }) {
  const anos = [...new Set([...ficha.serie_uso.map((s) => s.ano), ...ficha.perdas.flatMap((p) => p.ano === null ? [] : [p.ano])])].sort((a, b) => a - b)
  if (!anos.length) return <p>A linha do tempo depende das séries de uso e perdas, ainda não disponíveis nesta carga.</p>
  return <div>
    <p>Avance pelos anos para comparar a cobertura e as perdas. Uma lacuna significa ausência de dado, não ausência de perda.</p>
    <ol className="linha-tempo-terra" tabIndex={0} aria-label="Linha do tempo de uso e perdas da fazenda">
      {anos.map((ano) => {
        const uso = ficha.serie_uso.find((s) => s.ano === ano)
        const perdas = ficha.perdas.filter((p) => p.ano === ano)
        const soma = uso ? Object.keys(USOS).reduce((v, k) => v + (uso[k as keyof typeof USOS].valor ?? 0), 0) : 0
        return <li key={ano}><h3>{ano}</h3>
          {uso ? <><div className="uso-terra-barra" aria-hidden="true">{(Object.keys(USOS) as (keyof typeof USOS)[]).map((c) => <span key={c} className={c} style={{ width: `${(uso[c].valor ?? 0) / Math.max(100, soma) * 100}%` }} />)}</div>
            {(Object.keys(USOS) as (keyof typeof USOS)[]).map((c) => <p key={c}>{USOS[c]}: {numeroTerra(uso[c].valor)}{uso[c].valor === null ? "" : ` ${uso[c].unidade}`}<small>Fonte: {uso[c].fonte}. Referência: {dataTerra(uso[c].data_referencia)}.</small></p>)}
          </> : <p>Uso da terra não informado neste ano.</p>}
          {perdas.length ? perdas.map((p, n) => <p key={`${p.tipo}-${n}`}><strong>{p.rotulo}</strong>: {numeroTerra(p.area.valor)}{p.area.valor === null ? "" : ` ${p.area.unidade}`}<small>Fonte: {p.area.fonte}. Referência: {dataTerra(p.area.data_referencia)}.</small></p>) : <p>Perdas não informadas neste ano.</p>}
        </li>
      })}
    </ol>
  </div>
}
