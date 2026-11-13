import { describe, expect, it } from "vitest"
import { createExpression, validateStyleMin } from "@maplibre/maplibre-gl-style-spec"
import { latLngToCell } from "h3-js"
import { IndiceHexagonos } from "./hexagonos"
import { camadasHexagonos, corHexagonos, descreverHexagono, fontePublicaHexagonos } from "./camadas-hexagonos"
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
      camadas[0].paint!["fill-color"] = corHexagonos(consulta.legenda)
      expect(validateStyleMin({ version: 8, sources: { hexagonos: fonte, imoveis: fonte }, layers: [...camadas, ...camadasImoveis()] })).toEqual([])
      const e = createExpression(corHexagonos(consulta.legenda), "layers.hexagonos.paint.fill-color")
      expect(e.result).toBe("success")
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
