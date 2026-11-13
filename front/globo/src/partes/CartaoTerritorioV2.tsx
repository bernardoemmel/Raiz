import { ArrowUpRight } from "lucide-react"
import type { FunilMunicipio } from "../../../compartilhado/dados"
import { fmtCompacto, fmtHa, fmtInt } from "../../../compartilhado/formato"
import { numerosDoBrasil } from "../../../compartilhado/funil-etapas"
import { RotuloMono } from "./RotuloMono"

const numeroGrande = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 })

/** O cartão usa o resumo do motor. A cobertura cartográfica é uma medida separada. */
export function CartaoTerritorioV2({ nome, municipios, carregando, aoAbrirDados, ampliado, aoAlternar, aoArrastar, aoSoltar }: {
  nome: string
  municipios: FunilMunicipio[] | undefined
  carregando: boolean
  aoAbrirDados: () => void
  ampliado: boolean
  aoAlternar: () => void
  aoArrastar: (y: number) => void
  aoSoltar: (y: number) => void
}) {
  const n = municipios?.length ? numerosDoBrasil(municipios) : null
  return <section className={`cartao-territorio-v2${ampliado ? " cartao-ampliado" : ""}`} aria-labelledby="territorio-v2-titulo">
    <button className="cartao-v2-alca" type="button" aria-label={ampliado ? "Recolher resumo" : "Expandir resumo"} aria-expanded={ampliado}
      onClick={e => { if (e.detail === 0) aoAlternar() }}
      onPointerDown={e => { aoArrastar(e.clientY); e.currentTarget.setPointerCapture(e.pointerId) }} onPointerUp={e => aoSoltar(e.clientY)}><span /></button>
    <h1 id="territorio-v2-titulo"><RotuloMono partes={[nome, "terra para restaurar"]} /></h1>
    <div className="cartao-v2-medida" aria-label={n ? `${fmtHa(n.ha)} com potencial no resumo` : undefined}>
      <strong>{n ? numeroGrande.format(n.ha) : "n/d"}</strong>{n && <span>ha</span>}
    </div>
    <p className="cartao-v2-frase">{n ? <>podem voltar a ser mata nos imóveis avaliados. <span className="cartao-v2-frase-detalhe"> Desses, <strong>{fmtCompacto(n.prontas)}</strong> têm área apta e matrícula identificada.</span></> : carregando ? "Lendo os resumos publicados do motor…" : "O resumo deste território ainda não foi publicado."}</p>
    <dl className="cartao-v2-numeros">
      <div><dd title={n ? fmtInt(n.imoveis) : undefined}>{n ? fmtCompacto(n.imoveis) : "n/d"}</dd><dt>imóveis lidos</dt></div>
      <div><dd title={n ? fmtInt(n.aptas) : undefined}>{n ? fmtCompacto(n.aptas) : "n/d"}</dd><dt>fazendas aptas</dt></div>
      <div><dd title={n ? fmtInt(n.prontas) : undefined}>{n ? fmtCompacto(n.prontas) : "n/d"}</dd><dt>com matrícula</dt></div>
    </dl>
    {ampliado && <p className="cartao-v2-detalhe">{n ? `Resumo de aptidão de ${fmtInt(n.municipios)} ${n.municipios === 1 ? "município" : "municípios"}. ` : ""}Os hexágonos contam todos os cadastros publicados, com cobertura diferente. Área potencial não equivale a créditos emitidos nem a aprovação do título.</p>}
    <button className="cartao-v2-fonte" onClick={aoAbrirDados}>Sobre os dados <ArrowUpRight size={12} aria-hidden="true" /></button>
  </section>
}
