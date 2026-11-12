import { useEffect, useRef } from "react"
import type { Imovel } from "../../../compartilhado/dados"
import { fmtCompacto, fmtHa, fmtInt } from "../../../compartilhado/formato"
import { camposDeFutebol } from "../../../compartilhado/comparacoes"
import { tituloDe, type Frente } from "../filtros"
import { IconeBaixar } from "./Icones"

/** Resumo da seleção como rascunho de projeto. Gravar o projeto é da API (negocio.grupos); aqui sai a planilha. */
export function Projeto({ lista, frente, municipio, fechar, baixar }: { lista: Imovel[]; frente: Frente; municipio: string; fechar: () => void; baixar: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.focus()
    const esc = (e: KeyboardEvent) => e.key === "Escape" && fechar()
    window.addEventListener("keydown", esc)
    return () => window.removeEventListener("keydown", esc)
  }, [fechar])
  const area = lista.reduce((s, i) => s + frente.area(i), 0)
  const co2 = lista.reduce((s, i) => s + i.carbono_tco2_ano, 0)
  const por = (t: string) => lista.filter((i) => tituloDe(i) === t).length
  const pequenas = lista.filter((i) => i.pequena).length
  return (
    <div className="janela-fundo" onMouseDown={(e) => e.target === e.currentTarget && fechar()}>
      <div className="janela" role="dialog" aria-modal="true" aria-labelledby="projeto-titulo" tabIndex={-1} ref={ref}>
        <h2 id="projeto-titulo">Projeto com a seleção</h2>
        <p>
          {fmtInt(lista.length)} fazendas de {municipio}, frente {frente.rotulo.toLowerCase()}. As pequenas entram juntas no
          mesmo projeto.
        </p>
        <dl className="num">
          <dt>Área ({frente.sobre})</dt>
          <dd>{fmtHa(area)}</dd>
          <dt>Tamanho em campos de futebol</dt>
          <dd>{camposDeFutebol(area).replace(/^são |^é /, "")}</dd>
          {co2 > 0 && (
            <>
              <dt>Carbono tirado do ar (bruto)</dt>
              <dd>≈{fmtCompacto(co2)} tCO₂/ano</dd>
            </>
          )}
          <dt>Privada com matrícula (a conferir no cartório)</dt>
          <dd>{fmtInt(por("privada_matricula"))}</dd>
          <dt>Pública sob concessão</dt>
          <dd>{fmtInt(por("publica_concessao"))}</dd>
          <dt>Posse em titulação (entra quando o título sair)</dt>
          <dd>{fmtInt(por("posse_em_titulacao"))}</dd>
          <dt>Lotes de assentamento (dependem do INCRA)</dt>
          <dd>{fmtInt(por("assentamento"))}</dd>
          <dt>Pequenas (até 4 módulos fiscais)</dt>
          <dd>{fmtInt(pequenas)}</dd>
        </dl>
        <p>
          O próximo passo é conferir a matrícula de quem tem, acompanhar a titulação de quem está em espera e pedir o
          aceite do dono. Gravar o projeto fica com o
          back-end; por enquanto, baixe a planilha.
        </p>
        <div className="acoes">
          <button type="button" className="botao" onClick={fechar}>
            Fechar
          </button>
          <button type="button" className="botao principal" onClick={baixar} disabled={!lista.length}>
            <IconeBaixar /> Baixar planilha do projeto
          </button>
        </div>
      </div>
    </div>
  )
}
