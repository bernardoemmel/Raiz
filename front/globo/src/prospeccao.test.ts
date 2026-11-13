import { afterEach, describe, expect, it, vi } from "vitest"
import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { ErroProspeccao, filtrosDaBuscaSalva, fonteProspeccao, parametrosProspeccao, type MedidaTerra, type TerraComprometidaDados } from "../../compartilhado/prospeccao"
import { Medida } from "./telas/FichaTerra"
import { TerraComprometida } from "./partes/TerraComprometida"
import { MudancasTerra } from "./partes/VersoesFicha"
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
  it("comparação, busca salva e exclusão usam somente a sessão e nunca debitam créditos", async () => {
    const buscar = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}"))); vi.stubGlobal("fetch", buscar)
    const api = fonteProspeccao("/api", () => "sessao")
    await api.comparar(["CAR-A", "CAR-B"])
    await api.salvarBusca("Pará", { uf: "PA", area_min_ha: "0", credito_min: "" })
    await api.excluirBusca("id-da-busca")
    await api.lerAviso(7)
    expect(JSON.parse(buscar.mock.calls[0][1].body)).toEqual({ codigos_car: ["CAR-A", "CAR-B"] })
    expect(JSON.parse(buscar.mock.calls[1][1].body)).toEqual({ nome: "Pará", filtros: { uf: "PA", area_min_ha: "0" } })
    expect(buscar.mock.calls[2][1].method).toBe("DELETE")
    expect(buscar.mock.calls.every(([url, pedido]) => !url.includes("desbloquear") && pedido.headers.Authorization === "Bearer sessao" && pedido.cache === "no-store")).toBe(true)
  })
  it("recupera filtros numéricos salvos sem criar mínimo e respeita Retry-After", async () => {
    expect(filtrosDaBuscaSalva({ uf: "PA", area_min_ha: 0, credito_min: null })).toEqual({ uf: "PA", area_min_ha: "0" })
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 429, headers: { "Retry-After": "15" } })))
    const erro = await fonteProspeccao("/api", () => "sessao").avisos().catch((e) => e)
    expect(erro.retryAfter).toBe(15)
    expect(erro.message).toContain("15 segundos")
  })
  it("PDF exige autorização, mantém o bloqueio pago e recusa resposta que não seja PDF", async () => {
    const buscar = vi.fn().mockResolvedValueOnce(new Response("{}", { status: 402 }))
      .mockResolvedValueOnce(new Response("<html>erro</html>", { headers: { "Content-Type": "text/html" } }))
      .mockResolvedValueOnce(new Response("%PDF-1.4", { headers: { "Content-Type": "application/pdf" } }))
    vi.stubGlobal("fetch", buscar)
    const api = fonteProspeccao("/api", () => "sessao")
    await expect(api.pdf("CAR")).rejects.toMatchObject({ status: 402 })
    await expect(api.pdf("CAR")).rejects.toMatchObject({ status: 502 })
    expect(await (await api.pdf("CAR")).text()).toBe("%PDF-1.4")
    expect(buscar.mock.calls[2][0]).toBe("/api/prospeccao/fichas/CAR/pdf")
    expect(buscar.mock.calls[2][1]).toMatchObject({ cache: "no-store", headers: { Authorization: "Bearer sessao" } })
  })
  it("rotas antigas da fazenda continuam reconhecidas e há entrada nacional própria", () => {
    expect(lerRota(linkFazenda("PA-1507300-CAR"))).toEqual({ tela: "fazenda", car: "PA-1507300-CAR" })
    expect(lerRota(linkProspeccao)).toEqual({ tela: "prospeccao" })
  })
  it("histórico e exportações usam sessão e cancelamento sem consultar fonte pública ou debitar", async () => {
    const buscar = vi.fn().mockResolvedValueOnce(new Response('{"historico":[]}'))
      .mockResolvedValueOnce(new Response('{"protecao":{"marca":"conta-teste"}}', { headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response("marca,conta-teste\n", { headers: { "Content-Type": "text/csv; charset=utf-8" } }))
    vi.stubGlobal("fetch", buscar)
    const api = fonteProspeccao("/api", () => "sessao"), sinal = new AbortController().signal
    await api.historico("CAR/A", sinal)
    expect(await (await api.exportar("CAR/A", "json", sinal)).text()).toContain('"marca":"conta-teste"')
    expect(await (await api.exportar("CAR/A", "csv", sinal)).text()).toBe("marca,conta-teste\n")
    expect(buscar.mock.calls.map(([url]) => url)).toEqual(["/api/prospeccao/fichas/CAR%2FA/historico?limite=20", "/api/prospeccao/fichas/CAR%2FA/exportar?formato=json", "/api/prospeccao/fichas/CAR%2FA/exportar?formato=csv"])
    for (const [, opcoes] of buscar.mock.calls) expect(opcoes).toMatchObject({ headers: { Authorization: "Bearer sessao" }, cache: "no-store", method: "GET", signal: sinal })
  })
  it("exportações e histórico não contornam sessão, pagamento ou formato incorreto", async () => {
    const buscar = vi.fn().mockResolvedValueOnce(new Response("{}", { status: 402 })).mockResolvedValueOnce(new Response("<html/>", { headers: { "Content-Type": "text/html" } }))
    vi.stubGlobal("fetch", buscar)
    await expect(fonteProspeccao("/api", () => null).historico("CAR")).rejects.toMatchObject({ status: 401 })
    await expect(fonteProspeccao("/api", () => null).exportar("CAR", "json")).rejects.toMatchObject({ status: 401 })
    expect(buscar).not.toHaveBeenCalled()
    await expect(fonteProspeccao("/api", () => "sessao").exportar("CAR", "json")).rejects.toMatchObject({ status: 402 })
    await expect(fonteProspeccao("/api", () => "sessao").exportar("CAR", "csv")).rejects.toMatchObject({ status: 502 })
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
  it("compromissos distinguem certeza, fonte indisponível e ausência de comprovação", () => {
    const m: MedidaTerra = { valor: null, unidade: "ha", fonte: "Raíz", data_referencia: null, data_corte: "2026-11-12", estimado: true }
    const dado: TerraComprometidaDados = { versao: 1, situacao: "nao_verificado", area_confirmada: m, area_indicio: m, evidencias: [], contexto_jurisdicional: [], cobertura: [{ fonte_id: "verra", estado: "indisponivel", escopo: "brasil", recorte: "BR", bbox: null, url: null, licenca: "A conferir", data_referencia: null, consultado_em: "2026-11-12" }], aviso: "Ausência de sobreposição nas fontes consultadas não comprova terra livre." }
    const html = renderToStaticMarkup(createElement(TerraComprometida, { dado }))
    expect(html).toContain("Ainda não verificado")
    expect(html).toContain("Indisponível")
    expect(html).toContain("não comprova terra livre")
    expect(html).toContain("Data da fonte não informada")
    expect(html).not.toContain("0 ha")
  })
  it("mudança mantém antes/depois e metadados das medidas, sem transformar ausência em zero", () => {
    const medida: MedidaTerra = { valor: 0, unidade: "ha", fonte: "IBAMA", data_referencia: "2024", data_corte: "2026-11-12", estimado: false }
    const html = renderToStaticMarkup(createElement(MudancasTerra, { mudancas: [{ tipo: "embargos", campo: "embargos", antes: { area: { ...medida, valor: null } }, depois: { area: medida }, fonte: "IBAMA", data_referencia: "2024", data_corte: "2026-11-12" }] }))
    for (const texto of ["Antes", "Depois", "IBAMA", "2024", "12/11/2026", "Não informado", "0 ha"]) expect(html).toContain(texto)
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
