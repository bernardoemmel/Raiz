import { useState } from "react"
import type { FunilMunicipio, Imovel } from "../../../compartilhado/dados"
import { abreviarCar, fmtCompacto, fmtHa, fmtInt, fmtModulos } from "../../../compartilhado/formato"
import { fmtReais, lerRestauracao, MODOS, ORDENS, type Modo, type OrdemRestauracao } from "../../../compartilhado/restauracao"
import type { Frente } from "../filtros"
import { linkFazenda } from "../rota"

interface Props {
  titulo: string
  frente: Frente
  lista: Imovel[] | null
  funil: FunilMunicipio | null | undefined
  pequenas: number
  selecionado: string | null
  aoPassar: (cod: string | null) => void
  verPequenas: () => void
  outroMunicipio?: { nome: string; link: string } | null
  /** ordem e filtro pelo valor para quem restaura (o desenvolvedor) */
  ordem?: OrdemRestauracao
  mudarOrdem?: (o: OrdemRestauracao) => void
  modo?: Modo | null
  mudarModo?: (m: Modo | null) => void
}

const PASSO = 60

export function ListaFazendas({
  titulo,
  frente,
  lista,
  funil,
  pequenas,
  selecionado,
  aoPassar,
  verPequenas,
  outroMunicipio,
  ordem = "area",
  mudarOrdem,
  modo = null,
  mudarModo,
}: Props) {
  // a lista mudou (filtro, município): volta a mostrar só as primeiras
  const [pagina, setPagina] = useState({ lista, quantas: PASSO })
  if (pagina.lista !== lista) setPagina({ lista, quantas: PASSO })
  const quantas = pagina.lista === lista ? pagina.quantas : PASSO
  const setQuantas = (f: (q: number) => number) => setPagina((p) => ({ lista, quantas: f(p.quantas) }))

  if (!lista) {
    return (
      <aside className="painel lista" aria-label="Fazendas">
        <div className="lista-cabeca">
          <h2>Fazendas aptas</h2>
          <span className="lista-total num">{funil ? fmtInt(funil.aptas_carbono) : ""}</span>
        </div>
        <div className="vazio-lista">
          <p>
            O motor já contou {funil ? fmtInt(funil.aptas_carbono) : "as"} fazendas aptas em {funil?.municipio ?? "este município"}
            {funil ? ` (${fmtInt(funil.ha_carbono)} ha)` : ""}, mas a lista por fazenda ainda não está na amostra.
          </p>
          <p>Ela aparece aqui sozinha quando o arquivo de imóveis do município chegar.</p>
          {outroMunicipio && (
            <a className="link" href={outroMunicipio.link}>
              Ver a lista de {outroMunicipio.nome} →
            </a>
          )}
        </div>
      </aside>
    )
  }

  const usaCarbono = frente.id === "carbono" || frente.id === "agrupar"
  const porValor = ordem !== "area"
  return (
    <aside className="painel lista" aria-label="Fazendas">
      <div className="lista-cabeca">
        <h2>{titulo}</h2>
        <span className="lista-total num">{fmtInt(lista.length)}</span>
      </div>
      {mudarOrdem && mudarModo && (
        <div className="lista-ordem">
          <label>
            Ordenar por
            <select value={ordem} onChange={(e) => mudarOrdem(e.target.value as OrdemRestauracao)}>
              {ORDENS.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.rotulo}
                </option>
              ))}
            </select>
          </label>
          <label>
            Caminho de restauração
            <select value={modo ?? ""} onChange={(e) => mudarModo((e.target.value || null) as Modo | null)}>
              <option value="">Todos</option>
              {MODOS.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nome}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {lista.length === 0 ? (
        <div className="vazio-lista">
          <p>
            {modo
              ? "Nenhuma fazenda deste caminho de restauração passa pelos filtros. Escolha outro caminho ou todos."
              : "Nenhuma fazenda passa por estes filtros. Afrouxe o título da terra ou o tempo sem desmatamento."}
          </p>
        </div>
      ) : (
        <ol>
          {lista.slice(0, quantas).map((i) => (
            <li key={i.cod_imovel}>
              <a
                className="linha-fazenda"
                href={linkFazenda(i.cod_imovel)}
                aria-current={selecionado === i.cod_imovel}
                onMouseEnter={() => aoPassar(i.cod_imovel)}
                onMouseLeave={() => aoPassar(null)}
                onFocus={() => aoPassar(i.cod_imovel)}
                onBlur={() => aoPassar(null)}
              >
                <div>
                  <div className="lf-car">{abreviarCar(i.cod_imovel)}</div>
                  <div className="lf-sub num">
                    {fmtHa(i.ha)}
                    {i.m_fiscal !== null && <> · {fmtModulos(i.m_fiscal)}</>}
                  </div>
                </div>
                <div className="lf-dir">
                  <div className="lf-ha num">{fmtHa(frente.area(i))}</div>
                  <div className="lf-co2 num">
                    {porValor ? (
                      (() => {
                        const r = lerRestauracao(i.linha)
                        return r ? `${fmtReais(r.valorDesenvolvedor)} para quem restaura` : "sem cálculo ainda"
                      })()
                    ) : usaCarbono && i.carbono_tco2_ano > 0 ? (
                      <>≈{fmtCompacto(i.carbono_tco2_ano)} tCO₂/ano</>
                    ) : (
                      frente.sobre
                    )}
                  </div>
                </div>
              </a>
            </li>
          ))}
          {lista.length > quantas && (
            <li>
              <button type="button" className="mais" onClick={() => setQuantas((q) => q + PASSO)}>
                Mostrar mais {fmtInt(Math.min(PASSO, lista.length - quantas))} de {fmtInt(lista.length - quantas)}
              </button>
            </li>
          )}
        </ol>
      )}
      {pequenas > 0 && frente.id !== "agrupar" && (
        <div className="lista-pe">
          <button type="button" className="link" onClick={verPequenas}>
            Ver as {fmtInt(pequenas)} pequenas para agrupar →
          </button>
        </div>
      )}
    </aside>
  )
}
