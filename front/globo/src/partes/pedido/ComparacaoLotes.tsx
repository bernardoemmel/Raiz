import { fmtHa, fmtInt, fmtPct } from "../../../../compartilhado/formato"
import { fmtTir, fmtUsd, ROTULO_CAMINHO, ROTULO_OPCAO } from "../../../../compartilhado/pedidos/texto"
import type { IdOpcao, Opcao, OpcaoPublicada } from "../../../../compartilhado/pedidos/tipos"

const IDS: IdOpcao[] = ["barata", "segura", "compacta"]
const numero = (valor: number | null | undefined, formatar: (n: number) => string = fmtInt) =>
  typeof valor === "number" && Number.isFinite(valor) ? formatar(valor) : "Ainda não publicado"

/** Uma comparação única deixa claras as diferenças, inclusive quando o motor ainda não publicou uma métrica. */
export function ComparacaoLotes({ opcoes, publicadas, selecionar }: { opcoes: Opcao[]; publicadas?: OpcaoPublicada[]; selecionar: (id: IdOpcao) => void }) {
  const porId = new Map(opcoes.map((opcao) => [opcao.id, opcao]))
  const doRelease = new Map(publicadas?.map((opcao) => [opcao.id, opcao]) ?? [])
  const linhas: { titulo: string; valor: (opcao: Opcao | undefined) => string }[] = [
    { titulo: "Créditos líquidos P10 (t CO2e)", valor: (o) => numero(o?.creditos?.p10) },
    { titulo: "Créditos líquidos P50 (t CO2e)", valor: (o) => numero(o?.creditos?.p50) },
    { titulo: "Créditos líquidos P90 (t CO2e)", valor: (o) => numero(o?.creditos?.p90) },
    { titulo: "TIR P10", valor: (o) => numero(o?.tir?.p10, fmtTir) },
    { titulo: publicadas ? "TIR do cenário" : "TIR P50", valor: (o) => numero(o?.tir?.p50, fmtTir) },
    { titulo: "TIR P90", valor: (o) => numero(o?.tir?.p90, fmtTir) },
    { titulo: publicadas ? "Custo médio por crédito" : "Custo por crédito P50", valor: (o) => numero(o?.custo_usd_credito?.p50, fmtUsd) },
    { titulo: "Área para restaurar", valor: (o) => numero(o?.hectares, fmtHa) },
    { titulo: "Fazendas no lote", valor: (o) => numero(o?.fazendas) },
    { titulo: "Fazendas pequenas agrupadas", valor: (o) => numero(o?.pequenas) },
    { titulo: "Fazendas de reserva", valor: (o) => o ? fmtInt(o.itens.filter((i) => i.papel === "reserva").length) : "Ainda não publicado" },
    { titulo: "Pendências de terra", valor: (o) => {
      if (!o?.mistura_terra?.length) return "Ainda não publicado"
      const pendencias = o.mistura_terra.filter((item) => item.caminho !== "matricula_conferida" && item.caminho !== "concessao" && item.fracao > 0)
      return pendencias.length
        ? pendencias.map((item) => `${ROTULO_CAMINHO[item.caminho]}: ${fmtPct(item.fracao)}`).join("; ")
        : "Sem caminho pendente informado"
    } },
  ]
  const valorPublicado = (titulo: string, o: OpcaoPublicada | undefined): string => {
    if (!o) return "Área autenticada"
    if (titulo.startsWith("Créditos líquidos")) return numero(o.creditos?.[titulo.includes("P10") ? "p10" : titulo.includes("P90") ? "p90" : "p50"])
    if (titulo === "TIR do cenário") return numero(o.tir_p50, fmtTir)
    if (titulo.startsWith("TIR")) return "Ainda não publicado"
    if (titulo === "Custo médio por crédito") return numero(o.custo_usd_credito, fmtUsd)
    if (titulo === "Área para restaurar") return numero(o.hectares, fmtHa)
    if (titulo === "Fazendas no lote") return numero(o.fazendas)
    if (titulo === "Fazendas pequenas agrupadas") return numero(o.pequenas)
    if (titulo === "Fazendas de reserva") return numero(o.reservas)
    return o.pendencias_terra.length ? o.pendencias_terra.map((p) => `${ROTULO_CAMINHO[p.caminho]}: ${numero(p.fazendas)} fazendas, ${numero(p.hectares, fmtHa)}`).join("; ") : "Ainda não publicado"
  }
  return (
    <section className="secao-painel comparacao-lotes" aria-labelledby="comparacao-lotes-titulo">
      <h2 id="comparacao-lotes-titulo">Compare os três lotes</h2>
      <p className="legenda-frase">{publicadas && "Os números de cada lote são consultados na área autenticada. "}P10 é a estimativa conservadora, P50 a central e P90 a alta. As faixas não são promessa de entrega. TIR é a taxa interna de retorno.</p>
      <div className="tabela-rolagem" role="region" aria-label="Comparação dos lotes, deslize para ver todas as opções" tabIndex={0}>
        <table className="tabela-simples tabela-comparacao">
          <caption className="sr">Créditos, retorno, área e situação da terra por alternativa</caption>
          <thead><tr><th scope="col">Medida</th>{IDS.map((id) => (
            <th scope="col" key={id}><button type="button" className={`link opcao-marca opcao-${id}`} onClick={() => selecionar(id)}>
              <i aria-hidden="true" />{ROTULO_OPCAO[id].nome}
            </button></th>
          ))}</tr></thead>
          <tbody>{linhas.map((linha) => <tr key={linha.titulo}>
            <th scope="row">{linha.titulo}</th>{IDS.map((id) => <td key={id}>{publicadas ? valorPublicado(linha.titulo, doRelease.get(id)) : linha.valor(porId.get(id))}</td>)}
          </tr>)}</tbody>
        </table>
      </div>
    </section>
  )
}
