import { MOTIVOS, PORTES, type EtapaFunil, type Foco } from "../../../compartilhado/funil-etapas"
import { SITUACOES as SITUACOES_TERRA } from "../../../compartilhado/terra"
import { fmtHa, fmtInt, fmtPct } from "../../../compartilhado/formato"

export type Unidade = "imoveis" | "hectares"

interface Props {
  etapas: EtapaFunil[]
  foco: Foco
  aoFocar: (f: Foco) => void
  unidade: Unidade
  mudarUnidade: (u: Unidade) => void
}

/**
 * Funil em barras horizontais que afinam, alinhadas à esquerda (guia, item 4.2). Cada barra se divide por porte; o que
 * saiu fica como contorno do tamanho da etapa anterior, com os motivos escritos. Tocar na barra deixa no mapa só quem
 * chegou ali; tocar no contorno mostra quem saiu, pintado pelo motivo (item 4.3).
 */
export function FunilBarras({ etapas, foco, aoFocar, unidade, mudarUnidade }: Props) {
  const temHa = etapas.every((e) => Number.isFinite(e.total.ha))
  const und: Unidade = temHa ? unidade : "imoveis"
  const valor = (c: { n: number; ha: number }) => (und === "hectares" ? c.ha : c.n)
  const fmt = (v: number) => (und === "hectares" ? fmtHa(v) : fmtInt(v))
  const max = Math.max(1, valor(etapas[0].total))
  const temPorte = etapas.some((e) => Object.keys(e.porte).length > 0)

  return (
    <section className="funil-barras" aria-labelledby="funil-titulo">
      <div className="fb-cabeca">
        <h2 id="funil-titulo">Funil</h2>
        <div className="alternar" role="radiogroup" aria-label="Contar por">
          {(["imoveis", "hectares"] as Unidade[]).map((u) => (
            <button
              key={u}
              type="button"
              role="radio"
              aria-checked={und === u}
              disabled={u === "hectares" && !temHa}
              title={u === "hectares" && !temHa ? "Os hectares por etapa chegam com a lista por fazenda" : undefined}
              onClick={() => mudarUnidade(u)}
            >
              {u === "imoveis" ? "Imóveis" : "Hectares"}
            </button>
          ))}
        </div>
      </div>
      <ol>
        {etapas.map((e, k) => {
          const v = valor(e.total)
          const anterior = k ? valor(etapas[k - 1].total) : v
          const largura = (100 * v) / max
          const larguraAnt = (100 * anterior) / max
          const dentroAtivo = foco?.etapa === e.id && foco.lado === "dentro"
          const foraAtivo = foco?.etapa === e.id && foco.lado === "fora"
          const saiu = anterior - v
          let x = 0
          return (
            <li key={e.id}>
              <div className="fb-titulo">
                <span title={e.dica}>{e.rotulo}</span>
                <span className="fb-numero num">
                  <strong>{fmt(v)}</strong>
                  {k > 0 && anterior > 0 && <small>{fmtPct(v / anterior)} da etapa anterior</small>}
                </span>
              </div>
              <div className="fb-trilho">
                {k > 0 && saiu > 0 && (
                  <button
                    type="button"
                    className="fb-fora"
                    style={{ width: `${larguraAnt}%` }}
                    aria-pressed={foraAtivo}
                    aria-label={`Ver no mapa os ${fmt(saiu)} que saíram nesta etapa`}
                    onClick={() => aoFocar(foraAtivo ? null : { etapa: e.id, lado: "fora" })}
                  />
                )}
                <button
                  type="button"
                  className="fb-dentro"
                  style={{ width: `max(${largura}%, 4px)` }}
                  aria-pressed={dentroAtivo}
                  aria-label={`Ver no mapa só os ${fmt(v)} desta etapa`}
                  onClick={() => aoFocar(dentroAtivo ? null : { etapa: e.id, lado: "dentro" })}
                >
                  <svg viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">
                    {temPorte ? (
                      PORTES.map((p) => {
                        const c = e.porte[p.id]
                        const w = c && v > 0 ? (100 * valor(c)) / v : 0
                        const r = <rect key={p.id} x={x} y={0} width={w} height={10} fill={p.cor} fillOpacity={p.opacidade} />
                        x += w
                        return r
                      })
                    ) : (
                      <rect x={0} y={0} width={100} height={10} fill={PORTES[1].cor} />
                    )}
                  </svg>
                </button>
              </div>
              {e.terra && (
                <ul className="fb-partes" aria-label="Situação da terra">
                  {SITUACOES_TERRA.map((s) => (
                    <li key={s.id} className={"parte-" + s.id}>
                      <span className="num">{fmt(valor(e.terra![s.id] ?? { n: 0, ha: 0 }))}</span> {s.nome.toLowerCase()}
                    </li>
                  ))}
                </ul>
              )}
              {k > 0 && e.perdas.length > 0 && (
                <p className="fb-perdas">
                  {e.perdas
                    .slice(0, 3)
                    .map((p) => MOTIVOS[p.motivo].frase(und === "hectares" ? fmtHa(p.ha) : fmtInt(p.n)))
                    .join(", ")}
                  .
                </p>
              )}
            </li>
          )
        })}
      </ol>
      {temPorte && (
        <ul className="fb-legenda" aria-label="Porte">
          {PORTES.map((p) => (
            <li key={p.id}>
              <i style={{ background: p.cor, opacity: p.opacidade }} />
              {p.rotulo}
            </li>
          ))}
        </ul>
      )}
      {foco && (
        <button type="button" className="link" onClick={() => aoFocar(null)}>
          Mostrar todas as fazendas de novo
        </button>
      )}
    </section>
  )
}
