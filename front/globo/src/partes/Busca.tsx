import { useMemo, useRef, useState } from "react"
import type { FunilMunicipio, Imovel } from "../../../compartilhado/dados"
import { abreviarCar, fmtInt, normalizar } from "../../../compartilhado/formato"
import { fonte, useCarga } from "../dados"
import { linkFazenda, linkMunicipio } from "../rota"

interface Opcao {
  id: string
  rotulo: string
  detalhe: string
  link: string
}

/** Busca de município (todos os do resumo) ou de código do CAR (dos municípios com dado por fazenda carregados). */
export function Busca({ imoveis }: { imoveis?: Imovel[] | null }) {
  const municipios = useCarga(() => fonte.municipios(), [])
  const [texto, setTexto] = useState("")
  const [aberta, setAberta] = useState(false)
  const [ativo, setAtivo] = useState(0)
  const caixa = useRef<HTMLDivElement>(null)

  const opcoes = useMemo<Opcao[]>(() => {
    const q = normalizar(texto)
    if (q.length < 2) return []
    const ms = (municipios.dado ?? [])
      .filter((m: FunilMunicipio) => normalizar(m.municipio).includes(q) || m.cod_ibge.startsWith(q))
      .sort((a, b) => Number(!normalizar(a.municipio).startsWith(q)) - Number(!normalizar(b.municipio).startsWith(q)))
      .slice(0, 8)
      .map((m) => ({
        id: "m" + m.cod_ibge,
        rotulo: `${m.municipio} (${m.uf})`,
        detalhe: `${fmtInt(m.imoveis)} imóveis`,
        link: linkMunicipio(m.cod_ibge),
      }))
    const qCar = texto.trim().toUpperCase()
    const cs =
      qCar.length >= 4
        ? (imoveis ?? [])
            .filter((i) => i.cod_imovel.includes(qCar))
            .slice(0, 6)
            .map((i) => ({ id: "c" + i.cod_imovel, rotulo: abreviarCar(i.cod_imovel), detalhe: i.municipio, link: linkFazenda(i.cod_imovel) }))
        : []
    return [...ms, ...cs]
  }, [texto, municipios.dado, imoveis])

  const ir = (o: Opcao) => {
    location.hash = o.link
    setTexto("")
    setAberta(false)
  }

  return (
    <div
      className="busca"
      ref={caixa}
      onBlur={(e) => {
        if (!caixa.current?.contains(e.relatedTarget as Node)) setAberta(false)
      }}
    >
      <label className="sr" htmlFor="busca">
        Buscar município ou código do CAR
      </label>
      <input
        id="busca"
        type="search"
        role="combobox"
        aria-expanded={aberta && texto.length >= 2}
        aria-controls="busca-opcoes"
        autoComplete="off"
        placeholder="Buscar município ou código do CAR"
        value={texto}
        onChange={(e) => {
          setTexto(e.target.value)
          setAtivo(0)
          setAberta(true)
        }}
        onFocus={() => setAberta(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setAtivo((a) => Math.min(a + 1, opcoes.length - 1))
          else if (e.key === "ArrowUp") setAtivo((a) => Math.max(a - 1, 0))
          else if (e.key === "Enter" && opcoes[ativo]) ir(opcoes[ativo])
          else if (e.key === "Escape") setAberta(false)
          else return
          e.preventDefault()
        }}
      />
      {aberta && texto.trim().length >= 2 && (
        <ul id="busca-opcoes" role="listbox">
          {opcoes.length === 0 && <li className="vazio">Nada encontrado</li>}
          {opcoes.map((o, n) => (
            <li
              key={o.id}
              role="option"
              aria-selected={n === ativo}
              tabIndex={-1}
              onMouseEnter={() => setAtivo(n)}
              onMouseDown={(e) => {
                e.preventDefault()
                ir(o)
              }}
            >
              <span>{o.rotulo}</span>
              <small>{o.detalhe}</small>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
