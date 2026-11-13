import { describe, expect, it } from "vitest"
import { createExpression, validateStyleMin } from "@maplibre/maplibre-gl-style-spec"
import { latLngToCell } from "h3-js"
import { IndiceHexagonos } from "./hexagonos"
import { camadasHexagonos, filtroFaixaHexagonos, descreverHexagono, fontePublicaHexagonos } from "./camadas-hexagonos"
import { camadasImoveis } from "./cartografia"

const fonte = { type: "geojson" as const, data: { type: "FeatureCollection" as const, features: [] } }
const dados = { type: "FeatureCollection", features: [{ type: "Feature", properties: { h3: latLngToCell(-6.5, -50, 5), fazendas: 5, potencial_ha: null }, geometry: { type: "Point", coordinates: [-50, -6.5] } }] }

describe("contratos visuais H3 e detalhe", () => {
  it("valida camadas reais no schema MapLibre, inclusive faixa de transição e expressão quantitativa", () => {
    const indice = new IndiceHexagonos(dados)
    for (const z of [4, 6]) {
      const consulta = indice.consultar([-180, -85, 180, 85], z)
      const camadas = camadasHexagonos()
      if (camadas[0].type !== "fill") throw new Error("Camada inválida")
      expect(validateStyleMin({ version: 8, sources: { hexagonos: fonte, imoveis: fonte }, layers: [...camadas, ...camadasImoveis()] })).toEqual([])
      for (let faixa = 0; faixa < 6; faixa++) {
        const e = createExpression(filtroFaixaHexagonos(consulta.legenda, faixa, false, false), "layers.hexagonos.filter")
        expect(e.result).toBe("success")
        if (e.result !== "success") throw new Error("Faixa inválida")
        for (let f = 0; f < 6; f++) expect(e.value.evaluate({ zoom: z }, { type: 3, properties: { valor: consulta.legenda.limites[f], selecionado: false } })).toBe(faixa === f)
        const lote = createExpression(filtroFaixaHexagonos(consulta.legenda, faixa, true, true), "layers.hexagonos.filter")
        const fundo = createExpression(filtroFaixaHexagonos(consulta.legenda, faixa, false, true), "layers.hexagonos.filter")
        if (lote.result !== "success" || fundo.result !== "success") throw new Error("Seleção inválida")
        const item = { type: 3 as const, properties: { valor: consulta.legenda.limites[faixa], selecionado: true } }
        expect(lote.value.evaluate({ zoom: z }, item)).toBe(true)
        expect(fundo.value.evaluate({ zoom: z }, item)).toBe(false)
      }
      expect(camadasImoveis().every(c => c.minzoom === 9)).toBe(true)
    }
  })
  it("não diz apta nem converte medida desconhecida em zero", () => {
    const h = new IndiceHexagonos(dados).consultar([-180, -85, 180, 85], 4).hexagonos[0]
    expect(descreverHexagono(h)).toContain("5 fazendas cadastradas")
    expect(descreverHexagono(h)).toContain("hectares não informados")
    expect(descreverHexagono(h)).not.toMatch(/aptas|0 ha/)
  })
  it("limita o encaminhamento de URL ao arquivo público exato", () => {
    const url = "https://raiz.example/Raiz/geo/agregados_brasil.geojson"
    expect(fontePublicaHexagonos(url, url)).toBe(url)
    for (const proibida of [url + "?token=x", url + "#fragmento", url.replace("raiz.example", "outro.example"), url.replace("https://", "https://segredo@")])
      expect(fontePublicaHexagonos(proibida, url)).toBeNull()
  })
})
