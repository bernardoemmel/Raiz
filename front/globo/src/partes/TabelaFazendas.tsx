import { useState } from "react"
import type { Imovel } from "../../../compartilhado/dados"
import { SITUACOES, situacaoDe } from "../../../compartilhado/funil-etapas"
import { abreviarCar, fmtDestaque, fmtHa, fmtInt } from "../../../compartilhado/formato"
import { fmtReais, lerRestauracao } from "../../../compartilhado/restauracao"
import { linkFazenda } from "../rota"

const PASSO = 40
const TOM = { apta: "ok", pendencia: "conferir", nao_apta: "ruim" } as const

/**
 * Fazendas como tabela de colunas fixas (guia, item 4.5), números à direita, ajuda curta no cabeçalho e a linha
 * "Total da seleção", que acompanha o funil. Passar o mouse numa linha acende o polígono no mapa.
 */
interface Props {
  lista: Imovel[]
  aoPassar: (cod: string | null) => void
  /** mostrar a coluna do valor para quem restaura (quando a lista está ordenada por ele) */
  valor?: boolean
}

export function TabelaFazendas({ lista, aoPassar, valor = false }: Props) {
  const [pagina, setPagina] = useState({ lista, quantas: PASSO })
  if (pagina.lista !== lista) setPagina({ lista, quantas: PASSO })
  const quantas = pagina.lista === lista ? pagina.quantas : PASSO
  const area = lista.reduce((s, i) => s + (i.apta ? i.carbono_ha : 0), 0)
  const co2 = lista.reduce((s, i) => s + (i.apta ? i.carbono_tco2_ano : 0), 0)

  if (!lista.length) return null
  return (
    <div className="tabela-fazendas">
      <table>
        <thead>
          <tr>
            <th scope="col">
              Fazenda<small>código do CAR</small>
            </th>
            <th scope="col" className="num">
              Restaurar<small>ha que voltam a ser mata</small>
            </th>
            <th scope="col" className="num">
              Carbono<small>t por ano, bruto</small>
            </th>
            {valor && (
              <th scope="col" className="num">
                Para quem restaura<small>valor presente, P50, estimativa</small>
              </th>
            )}
            <th scope="col">Situação</th>
          </tr>
        </thead>
        <tbody>
          {lista.slice(0, quantas).map((i) => {
            const s = situacaoDe(i)
            return (
              <tr key={i.cod_imovel} onMouseEnter={() => aoPassar(i.cod_imovel)} onMouseLeave={() => aoPassar(null)}>
                <th scope="row">
                  <a href={linkFazenda(i.cod_imovel)} onFocus={() => aoPassar(i.cod_imovel)} onBlur={() => aoPassar(null)}>
                    {abreviarCar(i.cod_imovel)}
                  </a>
                  <small>Imóvel de {fmtHa(i.ha)}</small>
                </th>
                <td className="num">{i.apta ? fmtInt(i.carbono_ha) : "0"}</td>
                <td className="num">{i.apta && i.carbono_tco2_ano > 0 ? fmtInt(i.carbono_tco2_ano) : "0"}</td>
                {valor && (
                  <td className="num">
                    {(() => {
                      const r = lerRestauracao(i.linha)
                      return r ? fmtReais(r.valorDesenvolvedor) : "sem cálculo ainda"
                    })()}
                  </td>
                )}
                <td>
                  <span className={"selo " + TOM[s]}>{SITUACOES.find((x) => x.id === s)!.rotulo}</span>
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Total da seleção: {fmtInt(lista.length)}</th>
            <td className="num">{fmtInt(area)}</td>
            <td className="num">{fmtDestaque(co2)}</td>
            {valor && <td />}
            <td />
          </tr>
        </tfoot>
      </table>
      {lista.length > quantas && (
        <button type="button" className="mais" onClick={() => setPagina({ lista, quantas: quantas + PASSO })}>
          Mostrar mais {fmtInt(Math.min(PASSO, lista.length - quantas))} de {fmtInt(lista.length - quantas)}
        </button>
      )}
    </div>
  )
}
