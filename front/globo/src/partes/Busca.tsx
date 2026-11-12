import { useEffect, useId, useRef, useState } from "react"
import { CATEGORIAS, type RespostaBusca } from "../../../compartilhado/dados"
import { abreviarCar, fmtHa, fmtInt } from "../../../compartilhado/formato"
import { fonte } from "../dados"
import { linkFazenda, linkMunicipio, pedirVoo } from "../rota"

interface Opcao {
  id: string
  rotulo: string
  detalhe: string
  marca?: string
  /** marca em cinza (falta algo), não em verde */
  falta?: boolean
  ir: () => void
}

type Estado =
  | { fase: "parado" }
  | { fase: "buscando"; q: string }
  | { fase: "pronto"; q: string; r: RespostaBusca }
  | { fase: "erro"; q: string }

const ESPERA_MS = 250

function abrirImovel(car: string) {
  pedirVoo(car)
  location.hash = linkFazenda(car)
}
const abrirMunicipio = (cod: string) => {
  location.hash = linkMunicipio(cod)
}

/**
 * Busca por código do CAR ou município, sempre no topo (abertura, painel e ficha). Chama GET /busca?q= pela camada
 * de dados, espera o usuário parar de digitar e cancela a busca anterior. Imóvel abre a ficha com o mapa voando até o
 * município; município abre o painel dele.
 */
export function Busca({ aoEscolher }: { aoEscolher?: () => void }) {
  const [texto, setTexto] = useState("")
  const [estado, setEstado] = useState<Estado>({ fase: "parado" })
  const [aberta, setAberta] = useState(false)
  const [ativo, setAtivo] = useState(0)
  const abrirAoChegar = useRef(false)
  const caixa = useRef<HTMLDivElement>(null)
  const entrada = useRef<HTMLInputElement>(null)
  const idLista = useId()

  // busca com espera e cancelamento
  useEffect(() => {
    const q = texto.trim()
    if (q.length < 2) return
    const ctrl = new AbortController()
    const t = setTimeout(() => {
      setEstado({ fase: "buscando", q })
      fonte.buscar(q, ctrl.signal).then(
        (r) => {
          setEstado({ fase: "pronto", q, r })
          // Enter apertado antes da resposta: abre se houver um só imóvel ou um só resultado
          if (abrirAoChegar.current) {
            abrirAoChegar.current = false
            const ir =
              r.imoveis.length === 1
                ? () => abrirImovel(r.imoveis[0].cod_imovel)
                : !r.imoveis.length && r.municipios.length === 1
                  ? () => abrirMunicipio(r.municipios[0].cod_ibge)
                  : null
            if (ir) {
              ir()
              fecharRef.current()
            }
          }
        },
        (e: Error) => e.name !== "AbortError" && setEstado({ fase: "erro", q }),
      )
    }, ESPERA_MS)
    return () => {
      clearTimeout(t)
      ctrl.abort()
    }
  }, [texto])

  // "/" em qualquer lugar leva para a busca
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      const alvo = e.target as HTMLElement
      if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(alvo.tagName)) {
        e.preventDefault()
        entrada.current?.focus()
      }
    }
    window.addEventListener("keydown", tecla)
    return () => window.removeEventListener("keydown", tecla)
  }, [])

  const fechar = () => {
    setTexto("")
    setAberta(false)
    abrirAoChegar.current = false
    entrada.current?.blur()
    aoEscolher?.()
  }
  const fecharRef = useRef(fechar)
  useEffect(() => {
    fecharRef.current = fechar
  })

  function opcoesDe(r: RespostaBusca | null): Opcao[] {
    return [
      ...(r?.imoveis ?? []).map((i) => ({
        id: "i" + i.cod_imovel,
        rotulo: abreviarCar(i.cod_imovel),
        detalhe: `${i.municipio} (${i.uf}) · ${fmtHa(i.ha)}`,
        marca: i.apta ? `${fmtHa(i.carbono_ha)} aptos` : CATEGORIAS.find((c) => c.id === i.categoria)?.rotulo,
        falta: !i.apta,
        ir: () => {
          abrirImovel(i.cod_imovel)
          fechar()
        },
      })),
      ...(r?.municipios ?? []).map((m) => ({
        id: "m" + m.cod_ibge,
        rotulo: `${m.municipio} (${m.uf})`,
        detalhe: `${fmtInt(m.imoveis)} imóveis no CAR`,
        marca: m.tem_imoveis ? "lista por fazenda" : "sem lista por fazenda",
        falta: !m.tem_imoveis,
        ir: () => {
          abrirMunicipio(m.cod_ibge)
          fechar()
        },
      })),
    ]
  }
  const q = texto.trim()
  const r = estado.fase === "pronto" && estado.q === q ? estado.r : null
  const opcoes = opcoesDe(r)
  const mostrar = aberta && q.length >= 2
  // ocupado: há consulta e a resposta para ela ainda não chegou (inclui a espera de 250 ms)
  const ocupado = q.length >= 2 && !((estado.fase === "pronto" || estado.fase === "erro") && estado.q === q)

  return (
    <div
      className="busca"
      ref={caixa}
      onBlur={(e) => {
        if (!caixa.current?.contains(e.relatedTarget as Node)) setAberta(false)
      }}
    >
      <label className="sr" htmlFor={idLista + "-q"}>
        Código do CAR ou município
      </label>
      <input
        id={idLista + "-q"}
        ref={entrada}
        type="search"
        role="combobox"
        aria-expanded={mostrar}
        aria-controls={idLista}
        aria-busy={ocupado}
        aria-activedescendant={mostrar && opcoes[ativo] ? idLista + opcoes[ativo].id : undefined}
        autoComplete="off"
        spellCheck={false}
        placeholder="Código do CAR ou município"
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
          else if (e.key === "Enter") {
            if (!ocupado && opcoes[ativo]) opcoes[ativo].ir()
            else if (ocupado) abrirAoChegar.current = true
          } else if (e.key === "Escape") setAberta(false)
          else return
          e.preventDefault()
        }}
      />
      {ocupado && <span className="busca-girando" aria-hidden="true" />}
      {mostrar && (
        <div className="busca-caixa" role="region" aria-live="polite">
          {ocupado && <p className="busca-estado">Buscando “{q}”…</p>}
          {!ocupado && estado.fase === "erro" && estado.q === q && (
            <p className="busca-estado erro">Não deu para buscar agora. Confira a conexão e tente de novo.</p>
          )}
          {!ocupado && r?.mensagem && <p className={"busca-estado " + (r.situacao === "curta" ? "" : "aviso")}>{r.mensagem}</p>}
          {!ocupado && opcoes.length > 0 && (
            <ul id={idLista} role="listbox" aria-label="Resultados">
              {opcoes.map((o, n) => (
                <li
                  key={o.id}
                  id={idLista + o.id}
                  role="option"
                  aria-selected={n === ativo}
                  onMouseEnter={() => setAtivo(n)}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    o.ir()
                  }}
                >
                  <span>
                    <strong>{o.rotulo}</strong>
                    <small>{o.detalhe}</small>
                  </span>
                  {o.marca && <em className={o.falta ? "sem" : undefined}>{o.marca}</em>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
