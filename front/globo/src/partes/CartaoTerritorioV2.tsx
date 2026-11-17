import { ArrowUpRight } from "lucide-react"
import type { FunilMunicipio } from "../../../compartilhado/dados"
import { fmtCompacto, fmtHa, fmtInt } from "../../../compartilhado/formato"
import { numerosDoBrasil } from "../../../compartilhado/funil-etapas"
import { RotuloMono } from "./RotuloMono"

/** Número grande do cartão com a unidade por extenso: "22,8" + "milhões de ha" (o "mi" abreviado se lia como "mil"). */
function medidaGrande(ha: number): { numero: string; unidade: string } {
  const [numero, ...resto] = fmtCompacto(ha).split(" ")
  const palavra = resto.join(" ")
  return { numero, unidade: !palavra ? "ha" : palavra === "mil" ? "mil ha" : `${palavra} de ha` }
}

/** O cartão usa o resumo do motor. A cobertura cartográfica é uma medida separada. */
export function CartaoTerritorioV2({ nome, municipios, carregando, aoAbrirDados, ampliado, aoAlternar, aoArrastar, aoSoltar, oferta = "aptas" }: {
  nome: string
  /** a Situação do filtro: muda o número grande e a frase, como muda o que cada círculo soma */
  oferta?: "aptas" | "matricula" | "agrupar"
  municipios: FunilMunicipio[] | undefined
  carregando: boolean
  aoAbrirDados: () => void
  ampliado: boolean
  aoAlternar: () => void
  aoArrastar: (y: number) => void
  aoSoltar: (y: number) => void
}) {
  const n = municipios?.length ? numerosDoBrasil(municipios) : null
  const haOferta = n ? oferta === "matricula" ? n.haMatricula : n.ha : 0
  return <section className={`cartao-territorio-v2${ampliado ? " cartao-ampliado" : ""}`} aria-labelledby="territorio-v2-titulo">
    <button className="cartao-v2-alca" type="button" aria-label={ampliado ? "Recolher resumo" : "Expandir resumo"} aria-expanded={ampliado}
      onClick={e => { if (e.detail === 0) aoAlternar() }}
      onPointerDown={e => { aoArrastar(e.clientY); e.currentTarget.setPointerCapture(e.pointerId) }} onPointerUp={e => aoSoltar(e.clientY)}><span /></button>
    <h1 id="territorio-v2-titulo"><RotuloMono partes={[nome, "terra para restaurar"]} /></h1>
    {oferta === "agrupar" ? <div className="cartao-v2-medida" aria-label={n ? `${fmtInt(n.agrupar)} lotes de assentamento para agrupar` : undefined}>
      <strong>{n ? fmtCompacto(n.agrupar) : "n/d"}</strong>{n && <span>{n.agrupar === 1 ? "lote" : "lotes"}</span>}
    </div> : <div className="cartao-v2-medida" aria-label={n ? `${fmtHa(haOferta)} com potencial no resumo` : undefined}>
      <strong>{n ? medidaGrande(haOferta).numero : "n/d"}</strong>{n && <span>{medidaGrande(haOferta).unidade}</span>}
    </div>}
    <p className="cartao-v2-frase">{n ? oferta === "agrupar"
      ? <>de assentamento do INCRA que a Raíz agrupa num projeto só. Pequenas áreas entram juntas.</>
      : oferta === "matricula"
        ? <>podem voltar a ser mata nas fazendas aptas com matrícula identificada. <span className="cartao-v2-frase-detalhe"> São <strong>{fmtCompacto(n.prontas)}</strong> fazendas.</span></>
        : <>podem voltar a ser mata nos imóveis avaliados. <span className="cartao-v2-frase-detalhe"> Desses, <strong>{fmtCompacto(n.prontas)}</strong> têm área apta e matrícula identificada.</span></>
      : carregando ? "Lendo os resumos publicados do motor…" : "O resumo deste território ainda não foi publicado."}</p>
    <dl className="cartao-v2-numeros">
      <div><dt>imóveis lidos</dt><dd title={n ? fmtInt(n.imoveis) : undefined}>{n ? fmtCompacto(n.imoveis) : "n/d"}</dd></div>
      <div><dt>fazendas aptas</dt><dd title={n ? fmtInt(n.aptas) : undefined}>{n ? fmtCompacto(n.aptas) : "n/d"}</dd></div>
      <div><dt>com matrícula</dt><dd title={n ? fmtInt(n.prontas) : undefined}>{n ? fmtCompacto(n.prontas) : "n/d"}</dd></div>
    </dl>
    {ampliado && <p className="cartao-v2-detalhe">{n ? `Resumo de aptidão de ${fmtInt(n.municipios)} ${n.municipios === 1 ? "município" : "municípios"}. ` : ""}Os hexágonos contam todos os cadastros publicados, com cobertura diferente. Área potencial não equivale a créditos emitidos nem a aprovação do título.</p>}
    <button className="cartao-v2-fonte" onClick={aoAbrirDados}>Sobre os dados <ArrowUpRight size={12} aria-hidden="true" /></button>
  </section>
}
