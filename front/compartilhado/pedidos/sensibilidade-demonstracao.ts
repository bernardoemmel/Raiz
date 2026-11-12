/** Exercício didático com fluxos inventados. Não usa o Release, CARs, geometrias nem coeficientes do motor. */
import type { IdOpcao } from "./tipos"
import { conferirParametrosSensibilidade, type ParametrosSensibilidade, type ResultadoSensibilidade } from "./sensibilidade"

// As mesmas três composições inteiramente fictícias de pedidoDemonstracao(), sem ler pedido real.
const EXEMPLOS: { id: IdOpcao; creditos: { p10: number; p50: number; p90: number }; hectares: number; fazendas: number; tirCentral: number; custoAnual: number }[] = [
  { id: "barata", creditos: { p10: 900_000, p50: 1_100_000, p90: 1_300_000 }, hectares: 5_000, fazendas: 2, tirCentral: 0.12, custoAnual: 120_000 },
  { id: "segura", creditos: { p10: 960_000, p50: 1_130_000, p90: 1_320_000 }, hectares: 5_100, fazendas: 2, tirCentral: 0.13, custoAnual: 150_000 },
  { id: "compacta", creditos: { p10: 1_020_000, p50: 1_160_000, p90: 1_340_000 }, hectares: 5_200, fazendas: 2, tirCentral: 0.14, custoAnual: 100_000 },
]
const vpl = (fluxo: number[], taxa: number) => fluxo.reduce((total, n, ano) => total + n / (1 + taxa) ** ano, 0)
function tir(fluxo: number[]): number | null {
  // Estes fluxos sintéticos têm só uma mudança de sinal. Ausência de raiz permanece nula.
  let baixo = -0.99, alto = 10
  if (vpl(fluxo, baixo) * vpl(fluxo, alto) >= 0) return null
  for (let i = 0; i < 100; i++) {
    const meio = (baixo + alto) / 2
    if (vpl(fluxo, meio) > 0) baixo = meio
    else alto = meio
  }
  return (baixo + alto) / 2
}

export function simularSensibilidade(parametros: ParametrosSensibilidade, agora = new Date()): ResultadoSensibilidade {
  conferirParametrosSensibilidade(parametros)
  const captura = parametros.pessimista ? 0.6 : 1
  const custo = parametros.pessimista ? 1.3 : 1
  return {
    estado: "disponivel", exemplo: true, parametros: { ...parametros }, fonte: "Demonstração fictícia no navegador",
    atualizado_em: agora.toISOString(), modelo_versao: "demonstracao-sensibilidade-v1",
    aviso: "Valores fictícios para experimentar os controles. A composição dos três exemplos fica fixa; não há seleção de fazendas reais. No exemplo pessimista, a captura cai 40% e os custos sobem 30%. Essas premissas não representam o modelo do Pará e não servem para proposta comercial.",
    opcoes: EXEMPLOS.map((e) => {
      const fator = captura * (1 - parametros.reserva_reversao) / 0.8
      const creditos = { p10: e.creditos.p10 * fator, p50: e.creditos.p50 * fator, p90: e.creditos.p90 * fator }
      const futuros = (volume: number, preco: number, ajusteCusto: number) => Array.from({ length: 26 }, (_, ano) =>
        ano === 0 ? 0 : (ano >= 3 ? volume * preco / 23 : 0) - e.custoAnual * ajusteCusto)
      // Investimento inventado para reproduzir a TIR inicial da demonstração, nunca calibrado com o Release.
      const investimento = vpl(futuros(e.creditos.p50, 55, 1), e.tirCentral)
      const fluxo = futuros(creditos.p50, parametros.preco_credito_usd, custo)
      fluxo[0] = -investimento * custo
      return { id: e.id, creditos,
        hectares: e.hectares, fazendas: e.fazendas, vpl_usd: vpl(fluxo, parametros.taxa_desconto),
        tir_projeto: tir(fluxo), alcanca_meta: creditos.p50 >= 1_000_000 }
    }),
  }
}
