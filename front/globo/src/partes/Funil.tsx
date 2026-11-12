import { useContagem, type ModoContagem } from "./contagem"
import { fmtInt } from "../../../compartilhado/formato"

export interface Etapa {
  id: string
  rotulo: string
  numero: number
  sub: string
  /** fração do total de imóveis, para a barrinha do funil */
  fracao: number
  ativo: boolean
  aoEscolher?: () => void
  dica?: string
  /** barras por parte da etapa (caminho da terra: pronta agora, em espera, só mostrar); somam o número da etapa */
  partes?: { id: string; rotulo: string; numero: number }[]
}

function Cartao({ e, modo }: { e: Etapa; modo: ModoContagem }) {
  const n = useContagem(e.numero, modo)
  const escala = Math.min(1, e.fracao) * (e.numero ? n / e.numero : 1)
  const conteudo = (
    <>
      <div className="etapa-rotulo">{e.rotulo}</div>
      <div className="etapa-numero num">{fmtInt(n)}</div>
      <div className="etapa-sub">{e.sub}</div>
      <div className="etapa-barra" aria-hidden="true">
        <i style={{ transform: `scaleX(${escala})` }} />
      </div>
      {e.partes && e.numero > 0 && (
        <div className="etapa-partes">
          <div className="etapa-partes-barra" aria-hidden="true">
            {e.partes.map((p) => (
              <i key={p.id} className={"parte-" + p.id} style={{ width: `${(100 * p.numero) / e.numero}%` }} />
            ))}
          </div>
          <ul>
            {e.partes.map((p) => (
              <li key={p.id} className={"parte-" + p.id}>
                <span className="num">{fmtInt(p.numero)}</span> {p.rotulo.toLowerCase()}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
  const classe = "etapa" + (e.ativo ? " ativo" : "") + (e.aoEscolher ? "" : " estatica")
  return e.aoEscolher ? (
    <button type="button" className={classe} aria-pressed={e.ativo} onClick={e.aoEscolher} title={e.dica}>
      {conteudo}
    </button>
  ) : (
    <div className={classe} title={e.dica}>
      {conteudo}
    </div>
  )
}

export function Funil({ etapas, modo }: { etapas: Etapa[]; modo: ModoContagem }) {
  return (
    <ul className="funil" aria-label="Funil do município">
      {etapas.map((e) => (
        <li key={e.id}>
          <Cartao e={e} modo={modo} />
        </li>
      ))}
    </ul>
  )
}
