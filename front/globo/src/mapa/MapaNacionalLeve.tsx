import { ALTURA, ESTADOS, LARGURA } from "../../../compartilhado/brasil-estados"
import type { Estados } from "../../../compartilhado/dados"
import { fmtInt, UFS } from "../../../compartilhado/formato"
import { linkEstado } from "../rota"

/** A escala do país usa vetores leves, com os mesmos dados e links do painel. O mapa detalhado carrega ao aproximar. */
export function MapaNacionalLeve({ estados, carregandoDetalhe = false }: { estados: Estados | undefined; carregandoDetalhe?: boolean }) {
  return <div className="mapa-brasil mapa-nacional-leve">
    <svg viewBox={`-4 -4 ${LARGURA + 8} ${ALTURA + 8}`} role="group" aria-label="Mapa do Brasil por estado">
      {Object.entries(ESTADOS).map(([uf, d]) => {
        const e = estados?.estados.find((item) => item.uf === uf)
        const situacao = e?.situacao ?? "sem_dados"
        const descricao = `${uf}, ${UFS[uf] ?? uf}: ${e?.municipios ? `${fmtInt(e.municipios)} municípios processados` : "ainda não processado"}`
        // O centro serve só ao rótulo. A seleção continua sendo o contorno real do estado.
        const pontos = [...d.matchAll(/(-?[\d.]+),(-?[\d.]+)/g)].map((p) => [Number(p[1]), Number(p[2])])
        const xs = pontos.map((p) => p[0]), ys = pontos.map((p) => p[1])
        const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
        return <a key={uf} href={linkEstado(uf)} aria-label={descricao} className={`estado-vetor ${situacao}`}>
          <path d={d} />
          {(x1 - x0) > 15 && (y1 - y0) > 14 && <text x={(x0 + x1) / 2} y={(y0 + y1) / 2} aria-hidden="true">{uf}</text>}
        </a>
      })}
    </svg>
    <p className="mapa-nacional-legenda">Verde: estado com municípios processados. Cinza: ainda sem dados. Escolha um estado para aproximar.</p>
    {carregandoDetalhe && <p className="mapa-aviso aviso" role="status">Abrindo o mapa detalhado…</p>}
  </div>
}
