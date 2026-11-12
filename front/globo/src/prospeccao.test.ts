import { afterEach, describe, expect, it, vi } from "vitest"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { ErroProspeccao, fonteProspeccao, parametrosProspeccao, type MedidaTerra } from "../../compartilhado/prospeccao"
import { Medida } from "./telas/FichaTerra"
import { lerRota, linkFazenda, linkProspeccao } from "./rota"

afterEach(() => vi.unstubAllGlobals())

describe("acesso à ficha da terra", () => {
  it("sem API ou sem sessão não busca dados privados nem simula desbloqueio", async () => {
    const buscar = vi.fn(); vi.stubGlobal("fetch", buscar)
    await expect(fonteProspeccao(undefined, () => "exemplo").desbloquear("CAR")).rejects.toMatchObject({ status: 503 })
    await expect(fonteProspeccao("/api", () => null).ficha("CAR")).rejects.toMatchObject({ status: 401 })
    expect(buscar).not.toHaveBeenCalled()
  })
  it("ficha usa somente token de sessão, sem cache, e preserva o bloqueio por pagamento", async () => {
    const buscar = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Crédito pago necessário" }), { status: 402 }))
    vi.stubGlobal("fetch", buscar)
    await expect(fonteProspeccao("/api/", () => "sessao-cliente").ficha("PA-1507300-CAR")).rejects.toMatchObject({ status: 402 })
    expect(buscar).toHaveBeenCalledWith("/api/prospeccao/fichas/PA-1507300-CAR", expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer sessao-cliente" }), cache: "no-store", method: "GET" }))
  })
  it("o agregado não envia token de cliente nem parâmetros de paginação privados", async () => {
    const buscar = vi.fn().mockResolvedValue(new Response("{}")); vi.stubGlobal("fetch", buscar)
    await fonteProspeccao("/api", () => "segredo").agregado({ uf: "PA" })
    expect(buscar).toHaveBeenCalledWith("/api/prospeccao/agregado?uf=PA", expect.objectContaining({ headers: { "Content-Type": "application/json" } }))
  })
  it("compra preserva a chave contra duplicidade e contato manda somente o CAR", async () => {
    const buscar = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}"))); vi.stubGlobal("fetch", buscar)
    const api = fonteProspeccao("/api", () => "sessao")
    await api.comprar("pesquisa", "mesma-chave-123")
    await api.contato("PA-1507300-CAR")
    expect(JSON.parse(buscar.mock.calls[0][1].body)).toEqual({ plano: "pesquisa", chave_idempotencia: "mesma-chave-123" })
    expect(JSON.parse(buscar.mock.calls[1][1].body)).toEqual({ codigo_car: "PA-1507300-CAR" })
  })
  it("limite de consultas produz mensagem útil sem exigir texto interno do servidor", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 429 })))
    const erro = await fonteProspeccao("/api", () => "sessao").ficha("CAR").catch((e) => e)
    expect(erro).toBeInstanceOf(ErroProspeccao)
    expect(erro.message).toContain("Aguarde")
  })
  it("não acrescenta área mínima à consulta e conserva zero quando escolhido", () => {
    expect(parametrosProspeccao({})).toBe("pagina=1&limite=20")
    expect(parametrosProspeccao({ area_min_ha: "0", uf: " PA " }, 2)).toBe("area_min_ha=0&uf=PA&pagina=2&limite=20")
  })
  it("rotas antigas da fazenda continuam reconhecidas e há entrada nacional própria", () => {
    expect(lerRota(linkFazenda("PA-1507300-CAR"))).toEqual({ tela: "fazenda", car: "PA-1507300-CAR" })
    expect(lerRota(linkProspeccao)).toEqual({ tela: "prospeccao" })
  })
})

describe("fonte e data dos números", () => {
  it("distingue informação ausente de zero e data da fonte de corte da base", () => {
    const dado: MedidaTerra = { valor: null, unidade: "ha", fonte: "INPE", data_referencia: null, data_corte: "2026-11-12", estimado: false }
    const sem = renderToStaticMarkup(createElement(Medida, { dado }))
    expect(sem).toContain("Não informado")
    expect(sem).toContain("Data da fonte não informada")
    expect(sem).toContain("Corte da base: 12/11/2026")
    const zero = renderToStaticMarkup(createElement(Medida, { dado: { ...dado, valor: 0 } }))
    expect(zero).toContain("0 ha")
  })
})

describe("mapa e imagem privados", () => {
  it("mantém token e no-store nas três leituras visuais, sem pôr a sessão na URL", async () => {
    const buscar = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}")))
    vi.stubGlobal("fetch", buscar)
    const api = fonteProspeccao("/api", () => "sessao-privada")
    await api.visual("CAR")
    await api.satelite("CAR")
    const imagem = await api.imagemSatelite("CAR")
    expect(imagem).toBeInstanceOf(Blob)
    expect(buscar.mock.calls.map((c) => c[0])).toEqual(["/api/prospeccao/fichas/CAR/visual", "/api/prospeccao/fichas/CAR/visual/satelite", "/api/prospeccao/fichas/CAR/visual/satelite.webp"])
    for (const [, opcoes] of buscar.mock.calls) expect(opcoes).toMatchObject({ headers: { Authorization: "Bearer sessao-privada" }, cache: "no-store" })
  })
})
