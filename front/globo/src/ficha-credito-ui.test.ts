import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { lerFichaCredito, type BaseFichaCredito } from "../../compartilhado/ficha-credito"
import { fichaCreditoDemonstracao } from "../../compartilhado/pedidos/ficha-credito-demonstracao"
import { FatosCredito } from "./partes/ficha-credito/FatosCredito"

describe("métrica declarada nos fatos do lote", () => {
  it.each<[BaseFichaCredito["metrica"], string]>([
    ["credito_carbono", "Créditos de carbono"],
    ["credito_liquido", "Créditos líquidos de carbono"],
    ["reducao_flag", "Reduções para meta FLAG"],
  ])("rotula %s somente depois da validação da base", (metrica, titulo) => {
    const documento = fichaCreditoDemonstracao({ id: "barata", creditos: { p10: 100, p50: 200, p90: 300 }, hectares: 100 })
    documento.base!.metrica = metrica
    documento.base!.classe_ativo = metrica === "reducao_flag" ? "flag" : "credito_carbono"
    documento.resultados = null
    const ficha = lerFichaCredito(documento, { opcao_id: "barata", revisao_lote: null, exemplo: true })
    expect(ficha.estado).toBe("disponivel")
    const html = renderToStaticMarkup(createElement(FatosCredito, { ficha }))
    expect(html).toContain(`<caption>${titulo}, em tCO₂e</caption>`)
    expect(html).toContain("Estimativa de modelo não é crédito emitido nem entregue.")
    if (metrica === "credito_carbono") expect(html).not.toContain("líquidos")
    if (metrica === "reducao_flag") expect(html).toContain("não são somadas a créditos de carbono vendáveis")
  })
})
