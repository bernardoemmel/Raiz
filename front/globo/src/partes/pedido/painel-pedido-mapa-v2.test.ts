import { describe, expect, it, vi } from "vitest"
import type { Geo } from "../../../../compartilhado/dados/tipos"
import type { Pedido, PublicacaoLote } from "../../../../compartilhado/pedidos/tipos"
import { CAMPOS_PADRAO } from "../../../../compartilhado/pedidos/exemplo"
import { aplicarCriteriosDoMapaV2, confirmarCriteriosDoMapaV2, lerCriteriosDoMapaV2, levarCriteriosDoMapaV2 } from "./criterios-do-mapa-v2"
import {
  anelPedidoMapaV2, carregarPublicacaoMapaV2, escalaFaixasMapaV2, modeloApiMapaV2, modeloPublicacaoMapaV2,
  posicoesFaixaMapaV2,
} from "./painel-pedido-mapa-v2"

/** Valores sintéticos exclusivos dos testes, deliberadamente distintos da maquete. */
function publicada(): PublicacaoLote {
  return {
    contrato: "publico_lotes", versao: 1, estado: "publicado", aviso: "", fonte: "", atualizado_em: "2026-10-01T12:00:00Z",
    cenario: "central_r11", modelo_versao: "teste-v2", uf: "PA", volume_creditos: 800, preco_contrato_usd: 42,
    pedido_recalculado: false,
    base: { fazendas: null, hectares: null, creditos: { p10: null, p50: null, p90: null }, observacao: "" },
    cobertura: { municipios: 4, estados: 1, fazendas: 15, hectares: 80 },
    opcoes: ["barata", "segura", "compacta"].map((id, i) => ({
      id: id as "barata" | "segura" | "compacta", fazendas: 5 + i, hectares: 20 + i,
      creditos: { p10: 600 + i, p50: 900 + i, p90: 1200 + i }, custo_usd_credito: 9 + i,
      terra_pronta: { creditos_p50: 400, fracao_meta: 0.5 },
    })),
  }
}

describe("painel público do mapa V2", () => {
  it("deriva meta, região e todas as medidas do snapshot sem carregar composição", () => {
    const p = publicada()
    Object.assign(p.opcoes[0], { itens: [{ cod_imovel: "NAO-PUBLICAR", geometria: { type: "Polygon", coordinates: [] } }], destrava: ["NAO-PUBLICAR"] })
    const modelo = modeloPublicacaoMapaV2(p)
    expect(modelo.meta).toBe(800)
    expect(modelo.preco).toBe(42)
    expect(modelo.uf).toBe("PA")
    expect(modelo.opcoes[0]).toMatchObject({ fazendas: 5, hectares: 20, creditos: { p10: 600, p50: 900, p90: 1200 }, terraPronta: 0.5 })
    expect(modelo.opcoes[0].selecao).toEqual({ origem: "publicacao", opcaoId: "barata", rotulo: "Mais barato", uf: "PA", hectares: 20, meta: 800 })
    expect(JSON.stringify(modelo)).not.toMatch(/NAO-PUBLICAR|cod_imovel|geometria|destrava/)
  })

  it("preserva zero real e desconhecido, com supressão pública de grupos pequenos", () => {
    const p = publicada()
    p.opcoes[0].hectares = 0
    p.opcoes[0].custo_usd_credito = null
    p.opcoes[1].fazendas = 4
    const modelo = modeloPublicacaoMapaV2(p)
    expect(modelo.opcoes[0].hectares).toBe(0)
    expect(modelo.opcoes[0].custo).toBeNull()
    expect(modelo.opcoes[1]).toMatchObject({ fazendas: 4, hectares: null, creditos: null, custo: null, terraPronta: null })
  })

  it("rejeita resposta privada/incompatível e conserva o caminho configurável", async () => {
    const transporte = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ pedido: {}, fazendas: ["privado"] }) })
    await expect(carregarPublicacaoMapaV2("/dominio/dados", undefined, transporte)).rejects.toThrow("formato incompatível")
    expect(transporte).toHaveBeenCalledWith("/dominio/dados/amostra/lote_PA_central_r11.json", { signal: undefined })
  })

  it("não exibe uma publicação que falhou na validação nem inventa números quando ausente", async () => {
    const p = publicada()
    p.opcoes.pop()
    const transporte = vi.fn().mockResolvedValue({ ok: true, json: async () => p })
    await expect(carregarPublicacaoMapaV2("/", undefined, transporte)).rejects.toThrow("não passou pela validação")
    const vazio = modeloPublicacaoMapaV2({ ...publicada(), estado: "ausente" })
    expect(vazio.meta).toBeNull()
    expect(vazio.uf).toBeNull()
    expect(vazio.opcoes).toEqual([])
  })
})

describe("faixas reais dos lotes", () => {
  it("usa a mesma escala para comparar alternativas com tamanhos distintos", () => {
    const faixas = [{ creditos: { p10: 2, p50: 4, p90: 10 } }, { creditos: { p10: 4, p50: 10, p90: 20 } }]
    const escala = escalaFaixasMapaV2(faixas)
    expect(posicoesFaixaMapaV2(faixas[0].creditos, escala)).toEqual({ p10: 10, p50: 20, p90: 50 })
    expect(posicoesFaixaMapaV2(faixas[1].creditos, escala)).toEqual({ p10: 20, p50: 50, p90: 100 })
  })

  it("não transforma ausência, inversão dos quantis ou escala nula em valores fictícios", () => {
    expect(escalaFaixasMapaV2([{ creditos: null }])).toBeNull()
    expect(escalaFaixasMapaV2([{ creditos: { p10: 3, p50: 2, p90: 1 } }])).toBeNull()
    const zero = { p10: 0, p50: 0, p90: 0 }
    expect(posicoesFaixaMapaV2(zero, escalaFaixasMapaV2([{ creditos: zero }]))).toEqual(zero)
  })
})

describe("desenho e autorização", () => {
  const geometria = { type: "Polygon", coordinates: [[[-50, -3], [-49, -3], [-49, -2], [-50, -3]]] }
  const pedido = {
    id: "pedido-real", criado_em: "2026-10-01T12:00:00Z", versao_modelo: "v2",
    campos: { meta: { tipo: "creditos", valor: 800 }, onde: { ufs: ["PA"] }, dinheiro: { custo_max_usd_credito: 42 } },
    opcoes: [{ id: "barata", fazendas: 5, hectares: 20, creditos: { p10: 600, p50: 900, p90: 1200 }, custo_usd_credito: { p10: 8, p50: 9, p90: 10 },
      itens: [{ cod_imovel: "autorizada", ficha_liberada: true, geometria }, { cod_imovel: "negada", ficha_liberada: false, geometria }, { cod_imovel: "sem-geometria", ficha_liberada: true }] }],
  } as unknown as Pedido

  it("nenhum pedido simulado, público ou sem sessão libera desenho", () => {
    expect(modeloApiMapaV2(pedido, false)).toBeNull()
    expect(modeloApiMapaV2({ ...pedido, exemplo: true }, true)).toBeNull()
    expect(modeloApiMapaV2({ ...pedido, publicacao: publicada() }, true)).toBeNull()
  })

  it("só passa geometria autorizada pela API, sem preencher a negada com fonte pública", () => {
    const selecao = modeloApiMapaV2(pedido, true)?.opcoes[0].selecao
    expect(selecao).toMatchObject({ origem: "api", fazendas: [{ cod_imovel: "autorizada", geometria }] })
    expect(JSON.stringify(selecao)).not.toMatch(/negada|sem-geometria/)
  })

  it("aceita um único anel fechado sem substituir um polígono inválido por outro recorte", () => {
    const geo: Geo = { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: geometria }] }
    expect(anelPedidoMapaV2(geo)).toEqual(geometria.coordinates[0])
    expect(anelPedidoMapaV2({ ...geo, features: [...geo.features, ...geo.features] })).toBeNull()
    expect(anelPedidoMapaV2({ type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[[-50, -3], [-49, -3], [-49, -2], [-48, -2]]] } }] })).toBeNull()
    expect(anelPedidoMapaV2(null)).toBeNull()
  })
})

describe("passagem dos critérios reais ao formulário", () => {
  const poligono: [number, number][] = [[-50, -3], [-49, -3], [-49, -2], [-50, -3]]
  const criterios = { origem: "publicacao" as const, meta: { tipo: "creditos" as const, valor: 800 }, ufs: ["PA"], precoVenda: 42, poligono }

  it("leva meta, região, preço e desenho sem converter preço do contrato em teto de custo", () => {
    const padrao = structuredClone(CAMPOS_PADRAO)
    padrao.dinheiro.custo_max_usd_credito = 13
    const aplicado = aplicarCriteriosDoMapaV2(padrao, criterios)
    expect(aplicado.meta.valor).toBe(800)
    expect(aplicado.onde).toMatchObject({ ufs: ["PA"], biomas: [], poligono })
    expect(aplicado.dinheiro).toMatchObject({ preco_venda_usd: 42, custo_max_usd_credito: 13 })
    expect(padrao.onde.poligono).not.toEqual(poligono)
  })

  it("mantém a leitura idempotente no StrictMode e elimina o rascunho depois de recebido", () => {
    levarCriteriosDoMapaV2(criterios)
    const primeira = lerCriteriosDoMapaV2()!
    const segunda = lerCriteriosDoMapaV2()!
    expect(primeira).toEqual(segunda)
    primeira.poligono![0][0] = 0
    expect(lerCriteriosDoMapaV2()!.poligono![0][0]).toBe(-50)
    confirmarCriteriosDoMapaV2(segunda.transferencia)
    expect(lerCriteriosDoMapaV2()).toBeNull()
  })

  it("conserva os filtros de um pedido autenticado enquanto aplica o desenho explícito", () => {
    const campos = structuredClone(CAMPOS_PADRAO)
    campos.onde.ufs = ["PA", "MT"]
    campos.dinheiro.preco_venda_usd = 17
    const aplicado = aplicarCriteriosDoMapaV2(CAMPOS_PADRAO, { ...criterios, origem: "api", campos, meta: campos.meta })
    expect(aplicado.onde.ufs).toEqual(["PA", "MT"])
    expect(aplicado.dinheiro.preco_venda_usd).toBe(17)
    expect(aplicado.onde.poligono).toEqual(poligono)
  })
})
