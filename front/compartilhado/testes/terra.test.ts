import fs from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"
import { lerCsv } from "../dados/csv"
import { caminhoDe, CAMINHOS, lerTerra, ORIGINAVEIS, porSituacao } from "../terra"

const AMOSTRA = path.resolve(__dirname, "../../../dados/amostra")
const linhas = lerCsv(fs.readFileSync(path.join(AMOSTRA, "imoveis_1504950.csv"), "utf8")).linhas

describe("caminho da terra", () => {
  it("toda fazenda tem caminho: ninguém some por falta de matrícula", () => {
    const sit = porSituacao(linhas.map((l) => ({ linha: l })))
    expect(sit.pronta_agora + sit.em_espera + sit.so_mostrar).toBe(linhas.length)
    expect(sit.em_espera).toBeGreaterThan(0)
    for (const l of linhas) expect(CAMINHOS.some((c) => c.id === caminhoDe(l))).toBe(true)
  })

  it("sem a coluna, segue a mesma ordem da regra do back-end", () => {
    const base = { ha: "100", matricula_ha: "0", assentamento_ha: "0", ti_ha: "0" }
    expect(caminhoDe({ ...base, matricula_ha: "80" })).toBe("privada_matricula")
    expect(caminhoDe(base)).toBe("posse_em_titulacao")
    expect(caminhoDe({ ...base, tipo_imovel: "AST" })).toBe("assentamento")
    expect(caminhoDe({ ...base, matricula_ha: "90", ti_ha: "10" })).toBe("terra_indigena_ou_tradicional")
    expect(caminhoDe({ ...base, caminho_terra: "publica_concessao" })).toBe("publica_concessao")
  })

  it("posse em espera traz o aviso do que falta, sem chamar posse de propriedade", () => {
    const t = lerTerra({ ha: "100" })
    expect(t.caminho).toBe("posse_em_titulacao")
    expect(t.situacao).toBe("em_espera")
    expect(t.aviso).toMatch(/título/)
    expect(JSON.stringify(CAMINHOS.find((c) => c.id === "posse_em_titulacao"))).not.toMatch(/propriedade/i)
    expect(ORIGINAVEIS).toContain("posse_em_titulacao")
  })
})
