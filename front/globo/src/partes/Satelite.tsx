import type { Imovel } from "../../../compartilhado/dados"
import { num } from "../../../compartilhado/dados/colunas"
import { fmtHa, fmtInt } from "../../../compartilhado/formato"
import { causaPerda, classeMapbiomas, classeTmf, textoFogo } from "../../../compartilhado/satelite"

const pct = (v: number) => `${fmtInt(v)}%`

/** O que o satélite mostra: floresta tropical (JRC TMF), causa da perda (WRI), fogo e cobertura do ano (MapBiomas). */
export function Satelite({ imovel: i }: { imovel: Imovel }) {
  const tmf = classeTmf(i.tmf_classe)
  const causa = causaPerda(i.causa_perda)
  const fogo = textoFogo(i)
  const ano = i.mb_ano
  const floresta = ano ? num(i.linha, `mb_floresta_${ano}_ha`) : null
  const pasto = ano ? num(i.linha, `mb_pasto_${ano}_ha`) : null
  const cobertura = classeMapbiomas(i.mb_classe)
  if (!tmf && !causa && !fogo.historico && !fogo.recente && !cobertura) return null

  return (
    <section className="painel bloco satelite" aria-labelledby="satelite-titulo">
      <h2 id="satelite-titulo">O que o satélite mostra</h2>
      <div className="satelite-grade">
        {tmf && (
          <div>
            <h3>Floresta tropical</h3>
            <span className={"selo " + tmf.tom}>{tmf.rotulo}</span>
            <p>{tmf.texto.charAt(0).toUpperCase() + tmf.texto.slice(1)}.</p>
            {(i.tmf_floresta_pct !== null || i.tmf_regeneracao_pct !== null) && (
              <dl className="barras curtas">
                {i.tmf_floresta_pct !== null && (
                  <div>
                    <dt>Floresta</dt>
                    <dd>
                      <span className="barra">
                        <i style={{ width: `${Math.min(100, i.tmf_floresta_pct)}%` }} />
                      </span>
                      <span className="num">{pct(i.tmf_floresta_pct)}</span>
                    </dd>
                  </div>
                )}
                {i.tmf_regeneracao_pct !== null && (
                  <div>
                    <dt>Em regeneração</dt>
                    <dd>
                      <span className="barra">
                        <i style={{ width: `${Math.min(100, i.tmf_regeneracao_pct)}%` }} />
                      </span>
                      <span className="num">{pct(i.tmf_regeneracao_pct)}</span>
                    </dd>
                  </div>
                )}
              </dl>
            )}
            <small>Classe principal do imóvel no JRC TMF 2025 (Comissão Europeia).</small>
          </div>
        )}
        {causa && (
          <div>
            <h3>Causa da perda de floresta</h3>
            <span className={"selo " + causa.tom}>{causa.rotulo}</span>
            <p>{causa.texto.charAt(0).toUpperCase() + causa.texto.slice(1)}.</p>
            <small>
              WRI e Google DeepMind (v1.2), grade de 1 km: o que mais derrubou floresta no lugar do imóvel. Diz a causa da
              região, não acusa o dono.
            </small>
          </div>
        )}
        {(fogo.historico || fogo.recente) && (
          <div>
            <h3>Fogo</h3>
            {i.fogo_anos_max !== null && (
              <span className={"selo " + (i.fogo_anos_max >= 3 ? "ruim" : i.fogo_anos_max >= 1 ? "conferir" : "ok")}>
                {i.fogo_anos_max < 0.5 ? "Sem fogo" : `${fmtInt(i.fogo_anos_max)} ${Math.round(i.fogo_anos_max) === 1 ? "ano" : "anos"} com fogo`}
              </span>
            )}
            {fogo.historico && <p>{fogo.historico}</p>}
            {fogo.recente && <p>{fogo.recente}</p>}
            <small>MapBiomas Fogo: histórico no arquivo extras_ e o ano novo pela API.</small>
          </div>
        )}
        {cobertura && ano && (
          <div>
            <h3>Cobertura em {ano}</h3>
            <span className="selo neutro">{cobertura}</span>
            <p>Classe que mais ocupa o imóvel.</p>
            {(floresta !== null || pasto !== null) && (
              <p className="num">
                {floresta !== null && <>Floresta: {fmtHa(floresta)}</>}
                {floresta !== null && pasto !== null && ", "}
                {pasto !== null && <>Pasto: {fmtHa(pasto)}</>}
              </p>
            )}
            <small>MapBiomas, coleção 11, pela API da Plataforma.</small>
          </div>
        )}
      </div>
    </section>
  )
}
