import { describe, expect, it } from "vitest"
import { COR, rgb01 } from "../cores"
import { especificacaoFaixas } from "../../globo/src/partes/graficos/modelos"

// WCAG 2.1: sRGB linearizado e luminância relativa, incluindo a composição da opacidade.
function luminancia(rgb: readonly number[]) {
  const canais = rgb.map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4)
  return canais.reduce((total, c, i) => total + c * [.2126, .7152, .0722][i], 0)
}
function contraste(frente: string, fundo: string, opacidade = 1) {
  const fundoRgb = rgb01(fundo)
  const composto = rgb01(frente).map((c, i) => c * opacidade + fundoRgb[i] * (1 - opacidade))
  const [menor, maior] = [luminancia(composto), luminancia(fundoRgb)].sort((a, b) => a - b)
  return (maior + .05) / (menor + .05)
}

describe("contraste não textual das faixas e marcadores (WCAG 1.4.11)", () => {
  it.each([320, 1280])("mantém faixa e símbolos identificáveis em %i px", largura => {
    const spec = especificacaoFaixas([], largura)
    if (!("layer" in spec)) throw new Error("O gráfico precisa das camadas de faixa, P50 e observado")
    const marcas = spec.layer.map(c => typeof c.mark === "object" ? c.mark : {})
    const [faixa, mediana, observado] = marcas
    expect(contraste(faixa.color as string, COR.papel, faixa.opacity as number)).toBeGreaterThanOrEqual(3)
    expect(mediana.shape).toBe("circle")
    expect(observado.shape).toBe("diamond")
    for (const ponto of [mediana, observado]) {
      expect(ponto.opacity).toBe(1)
      expect(contraste(ponto.color as string, COR.papel)).toBeGreaterThanOrEqual(3)
      // Sobre a faixa, o halo separa duas cores cujo contraste direto seria insuficiente.
      expect(ponto.strokeWidth as number).toBeGreaterThanOrEqual(2)
      expect(contraste(ponto.color as string, ponto.stroke as string)).toBeGreaterThanOrEqual(3)
      expect(contraste(ponto.stroke as string, faixa.color as string)).toBeGreaterThanOrEqual(3)
    }
  })
})
