import { BASE_HA, caixaDeFatos, PRAZO_ANOS } from "../../../compartilhado/cenario"
import type { Imovel } from "../../../compartilhado/dados"
import { fmtCompacto, fmtInt } from "../../../compartilhado/formato"

const fmt = (v: number, tipo: string) => (tipo === "tco2" && Math.abs(v) >= 10_000 ? fmtCompacto(v) : fmtInt(v))

/**
 * Caixa de fatos: três colunas fixas (o que se mede, não fazer nada, restaurar), base fixa de 100 ha e prazo fixo
 * de 10 anos, para que fazendas de qualquer tamanho fiquem lado a lado.
 */
export function CaixaDeFatos({ imovel }: { imovel: Imovel }) {
  const c = caixaDeFatos(imovel)
  return (
    <section className="fatos" aria-labelledby="fatos-titulo">
      <header>
        <h2 id="fatos-titulo">Caixa de fatos</h2>
        <p>
          A cada <strong>{BASE_HA} ha</strong> deste imóvel, em <strong>{PRAZO_ANOS} anos</strong>
        </p>
      </header>
      <div className="tabela-rolagem">
      <table>
        <thead>
          <tr>
            <th scope="col">
              <span className="sr">O que se mede</span>
            </th>
            <th scope="col">Não fazer nada</th>
            <th scope="col" className="fatos-restaurar">
              Restaurar a área apta
            </th>
          </tr>
        </thead>
        <tbody>
          {c.linhas.map((l) => {
            const dif = l.restaurar - l.nada
            return (
              <tr key={l.id}>
                <th scope="row">
                  {l.rotulo}
                  {l.nota && <small>{l.nota}</small>}
                </th>
                <td className="num">
                  {fmt(l.nada, l.tipo)} <span className="fatos-un">{l.unidade}</span>
                </td>
                <td className="num fatos-restaurar">
                  {fmt(l.restaurar, l.tipo)} <span className="fatos-un">{l.unidade}</span>
                  {Math.round(dif) !== 0 && (
                    <span className={"fatos-dif " + (dif > 0 ? "dif-mais" : "dif-menos")}>
                      {dif > 0 ? "+" : "−"}
                      {fmt(Math.abs(dif), l.tipo)}
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      </div>
      <ul className="fatos-notas">
        {c.notas.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </section>
  )
}
