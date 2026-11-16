import { describe, expect, it } from "vitest"
import { lerBasico } from "../dados/basico"

const linha = { cod_imovel: "PA-1505536-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", cod_ibge: "1505536", municipio: "Parauapebas", uf: "PA", situacao_basica: "com_pendencia" }

describe("contrato público básico", () => {
  it("projeta somente identidade territorial e situação, sem herdar dados novos do motor", () => {
    expect(lerBasico({ ...linha, ha: "200", credito_p50: "1234", risco: "baixo", registro_matricula: "privado" })).toEqual(linha)
  })
  it.each(["apto", "com_pendencia", "nao_apto"])("mantém imóvel com situação %s sem exigir área mínima", (situacao_basica) => {
    expect(lerBasico({ ...linha, situacao_basica })).toEqual({ ...linha, situacao_basica })
  })
  it("recusa situação desconhecida e CAR inválido sem inventar aptidão", () => {
    expect(lerBasico({ ...linha, situacao_basica: "desconhecido" })).toBeNull()
    expect(lerBasico({ ...linha, cod_imovel: "CAR-INVALIDO" })).toBeNull()
  })
})
