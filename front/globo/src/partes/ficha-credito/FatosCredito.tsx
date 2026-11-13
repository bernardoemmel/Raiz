import { useId } from "react"
import type { FichaCredito } from "../../../../compartilhado/ficha-credito"
import { ROTULO_METODO } from "../../../../compartilhado/pedidos/texto"
import { dataTerra, numeroTerra } from "../../prospeccao"

const EVIDENCIAS = {
  estimativa_modelo: "Estimativa de modelo",
  verificado: "Resultado verificado",
  emitido: "Créditos emitidos",
  entregue: "Créditos entregues",
} as const
const METRICAS = {
  credito_carbono: "Créditos de carbono",
  credito_liquido: "Créditos líquidos de carbono",
  reducao_flag: "Reduções para meta FLAG",
} as const
const EXCLUSOES = {
  embargo: "Embargo", terra_indigena: "Terra indígena", uc_protecao_integral: "Unidade de conservação de proteção integral",
  projeto_carbono: "Projeto de carbono existente", inelegivel_metodo: "Área não elegível para o método", outra: "Outra exclusão documentada",
} as const

/** A coluna por hectare nunca é calculada a partir da área do CAR ou de um resumo de outra execução. */
export function FatosCredito({ ficha }: { ficha: FichaCredito }) {
  const id = useId()
  const base = ficha.estado === "disponivel" ? ficha.base : null
  const total = base ? ficha.creditos_lote : null
  const porHa = base ? ficha.creditos_por_ha : null
  const flag = base?.classe_ativo === "flag"
  const metodo = base && ((ROTULO_METODO as Record<string, string>)[base.metodo] ?? base.metodo.replaceAll("_", " "))
  return <section className="fatos-credito" aria-labelledby={id}>
    <h3 id={id}>Fatos do lote</h3>
    <p className="fatos-base">{base ? `No mesmo horizonte de ${numeroTerra(base.horizonte_anos)} anos.` : "Horizonte ainda não informado."}</p>
    <p>{base ? `${EVIDENCIAS[base.classe_evidencia]}. ${METRICAS[base.metrica]}.` : "Classe de evidência ainda não informada."}</p>
    <p>{base ? `Carteira: ${base.escopo_carteira === "titulares_e_reservas" ? "titulares e reservas" : "titulares"}. A mesma composição nas duas colunas.` : "Composição da carteira ainda não informada."}</p>
    {base && <p className="fatos-periodo">Início: {dataTerra(base.inicio)}. Fim: {dataTerra(base.fim)}.</p>}
    <dl className="fatos-area">
      <div><dt>Área elegível da carteira</dt><dd>{numeroTerra(ficha.area_elegivel_ha)}{ficha.area_elegivel_ha !== null && " ha"}</dd></div>
      <div><dt>Área total da carteira</dt><dd>{numeroTerra(ficha.area_total_ha)}{ficha.area_total_ha !== null && " ha"}</dd></div>
    </dl>
    <table>
      <caption>{base ? METRICAS[base.metrica] : "Resultado do lote"}, em tCO₂e</caption>
      <thead><tr><th scope="col">Faixa</th><th scope="col">Por hectare elegível</th><th scope="col">Total do lote</th></tr></thead>
      <tbody>{(["p10", "p50", "p90"] as const).map((quantil) => <tr key={quantil} className={quantil === "p50" ? "fatos-central" : undefined}>
        <th scope="row">{quantil.toUpperCase()}</th><td>{numeroTerra(porHa?.[quantil])}</td><td>{numeroTerra(total?.[quantil])}</td>
      </tr>)}</tbody>
    </table>
    <p className="fatos-nota">P10, P50 e P90 descrevem a faixa da mesma carteira. A coluna por hectare usa somente a área elegível documentada dessa carteira.</p>
    {!porHa && <p>A comparação por hectare aguarda uma área elegível e uma base compatíveis. Não dividimos os créditos pela área total da fazenda.</p>}
    {base && <p>Método: {metodo}. Modelo: <code>{base.modelo_versao}</code>.</p>}
    <p>Fonte dos créditos: {base?.fonte || "não informada"}. Referência: {dataTerra(base?.data_referencia)}.</p>
    <p>Fonte da área: {ficha.fonte_area || "não informada"}. Referência: {dataTerra(ficha.data_referencia_area)}.</p>
    <h4>Exclusões da área</h4>
    {ficha.exclusoes === null ? <p>Exclusões ainda não documentadas.</p> : ficha.exclusoes.length === 0 ? <p>Nenhuma exclusão identificada na análise publicada.</p> : <>
      <dl className="fatos-exclusoes">{ficha.exclusoes.map((exclusao, i) => <div key={`${exclusao.motivo}-${i}`}>
        <dt>{EXCLUSOES[exclusao.motivo]}</dt><dd><strong>{numeroTerra(exclusao.hectares)}{exclusao.hectares !== null && " ha"}</strong><span>Fonte: {exclusao.fonte || "não informada"}. Referência: {dataTerra(exclusao.data_referencia)}.</span></dd>
      </div>)}</dl>
      <p>As áreas de exclusão podem se sobrepor. Não some as linhas.</p>
    </>}
    {base?.classe_evidencia === "estimativa_modelo" && <p className="fatos-nota">Estimativa de modelo não é crédito emitido nem entregue.</p>}
    {flag && <p className="fatos-nota">Reduções para meta FLAG não são somadas a créditos de carbono vendáveis.</p>}
  </section>
}
