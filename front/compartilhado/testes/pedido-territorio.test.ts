import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { EstadoDados, Estados, FunilMunicipio } from "../dados/tipos"
import { UFS } from "../formato"
import { CAMPOS_PADRAO } from "../pedidos/exemplo"
import { fontePedidosApi } from "../pedidos/fonte-pedidos"
import { coberturaTerritorial, mudarEscopoPedido, resumirCoberturaMunicipal } from "../pedidos/territorio"
import { ResumoCoberturaPedido } from "../../globo/src/partes/pedido/CoberturaPedido"

const onde = { ...CAMPOS_PADRAO.onde, ufs: [], biomas: [] }
const manifesto = (contagens: Record<string, [number, number]> = { PA: [144, 144], GO: [10, 246] }): Estados => ({
  pasta: "publicada", lista_ibge: "DTB de teste", gerado_em: "2026-11-12T21:00:00Z",
  estados: Object.entries(UFS).map(([uf, nome]): EstadoDados => {
    const [municipios, municipios_ibge] = contagens[uf] ?? [0, 10]
    return { uf, nome, cod: "", municipios, municipios_ibge, com_lista: [], situacao: municipios === municipios_ibge ? "completo" : municipios ? "incompleto" : "sem_dados", completo: municipios === municipios_ibge, fora_da_lista: [] }
  }),
})
const municipio = (cod_ibge: string, uf: string, imoveis: string, ha_carbono: string, dados_suprimidos = "false") => ({ cod_ibge, uf, linha: { imoveis, ha_carbono, dados_suprimidos } } as FunilMunicipio)

afterEach(() => vi.unstubAllGlobals())

describe("pedido nacional e cobertura do processamento", () => {
  it("inclui um estado novo automaticamente e distingue falta de município de falta de estado", () => {
    const primeiro = coberturaTerritorial(onde, manifesto())
    expect(primeiro.disponiveis).toEqual(["GO", "PA"])
    expect(primeiro.parciais).toEqual(["GO"])
    expect(primeiro.faltantes).toHaveLength(25)
    const seguinte = coberturaTerritorial(onde, manifesto({ PA: [144, 144], GO: [246, 246], RS: [4, 497] }))
    expect(seguinte.disponiveis).toEqual(["GO", "PA", "RS"])
    expect(seguinte.parciais).toEqual(["RS"])
    expect(seguinte.municipios_processados).toBe(394)
    expect(seguinte.atualizado_em).toBe("2026-11-12T21:00:00Z")
  })

  it("conserva um estado escolhido ainda sem dados e não soma estados repetidos", () => {
    const c = coberturaTerritorial({ ...onde, ufs: ["SP", "PA", "PA"] }, manifesto())
    expect(c.disponiveis).toEqual(["PA"])
    expect(c.faltantes).toEqual(["SP"])
    expect(c.municipios_processados).toBe(144)
    expect(c.municipios_esperados).toBe(154)
  })

  it("não chama uma entrada ausente ou inválida de estado sem potencial", () => {
    const m = manifesto()
    m.estados = m.estados.filter((e) => e.uf !== "PA")
    m.estados.find((e) => e.uf === "GO")!.municipios = NaN
    const c = coberturaTerritorial({ ...onde, ufs: ["PA", "GO"] }, m)
    expect(c.desconhecidos).toEqual(["GO", "PA"])
    expect(c.faltantes).toEqual([])
    expect(c.municipios_processados).toBeNull()
    const html = renderToStaticMarkup(createElement(ResumoCoberturaPedido, { cobertura: c }))
    expect(html).toContain("ainda não pôde ser confirmada")
    expect(html).not.toContain("Nenhum estado com dados publicados")
    expect(html).toContain("Não foram contados como zero")
  })

  it("mostra que disponibilidade estadual não mede a oferta de um bioma", () => {
    const c = coberturaTerritorial({ ...onde, biomas: ["Cerrado", "Amazônia"] }, manifesto())
    const html = renderToStaticMarkup(createElement(ResumoCoberturaPedido, { cobertura: c }))
    expect(html).toContain("estes totais não medem a oferta do bioma")
    expect(html).toContain("Cobertura parcial")
    expect(html).toContain("Ainda sem dados publicados")
    expect(html).toContain('dateTime="2026-11-12T21:00:00Z"')
  })

  it("ao escolher Brasil limpa o recorte anterior e envia o mesmo formato para a API", async () => {
    const anterior = { ...CAMPOS_PADRAO.onde, ufs: ["PA"], municipios: ["1505536"], raio: { lon: -50, lat: -10, km: 25 }, poligono: [[-50, -10], [-51, -10], [-50, -11], [-50, -10]] as [number, number][] }
    const brasil = mudarEscopoPedido(anterior, "brasil")
    expect(brasil).toEqual({ biomas: [], ufs: [], municipios: [], raio: null, poligono: null, so_fornecedores_cadeia: false })
    let enviado: unknown
    vi.stubGlobal("fetch", vi.fn(async (_url, init) => { enviado = JSON.parse(init.body); return new Response(JSON.stringify({ id: "teste" })) }))
    await fontePedidosApi("/api/").criar({ ...CAMPOS_PADRAO, onde: brasil })
    expect(enviado).toMatchObject({ onde: brasil })
    const biomas = mudarEscopoPedido(anterior, "biomas")
    expect(biomas.ufs).toEqual([])
    expect(biomas.municipios).toEqual([])
    expect(biomas.biomas).toEqual(["Amazônia"])
  })
})

describe("limites dos agregados públicos do pedido", () => {
  const pa = municipio("1505536", "PA", "10", "100")
  const go = municipio("5200050", "GO", "5", "40")
  it("soma o Brasil sem duplicar municípios ou confundir o zero publicado com desconhecido", () => {
    expect(resumirCoberturaMunicipal(onde, [pa, go, pa])).toEqual({ municipios: 2, estados: 2, fazendas: 15, hectares: 140 })
    expect(resumirCoberturaMunicipal({ ...onde, ufs: ["GO"] }, [pa, municipio("5200050", "GO", "0", "0")])).toEqual({ municipios: 1, estados: 1, fazendas: 0, hectares: 0 })
  })
  it("não atribui um município inteiro ao bioma nem multiplica a oferta por biomas sobrepostos", () => {
    const c = resumirCoberturaMunicipal({ ...onde, biomas: ["Cerrado", "Amazônia", "Amazônia"] }, [pa, go])
    expect(c).toMatchObject({ municipios: 2, estados: 2, fazendas: null, hectares: null })
    expect(c.observacao).toContain("um estado inteiro")
  })
  it("preserva a ausência e a supressão; não apresenta oferta zero para um estado ainda não processado", () => {
    expect(resumirCoberturaMunicipal({ ...onde, ufs: ["RS"] }, [pa])).toMatchObject({ municipios: 0, estados: 0, fazendas: null, hectares: null })
    expect(resumirCoberturaMunicipal(onde, [pa, municipio("5200050", "GO", "", "", "true")])).toMatchObject({ fazendas: null, hectares: null })
  })
})
