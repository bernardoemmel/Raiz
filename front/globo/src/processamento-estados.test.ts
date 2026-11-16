import { createElement } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { afterEach, describe, expect, it, vi } from "vitest"
import { UFS } from "../../compartilhado/formato"
import { buscarProcessamento, lerProcessamentoEstados, situacaoProcessamento, urlProcessamento, type ProcessamentoEstado, type ProcessamentoEstados } from "../../compartilhado/dados/processamento-estados"
import { acompanharProcessamento, type CargaProcessamento } from "./processamento-estados"
import { PainelProcessamentoEstados } from "./partes/PainelProcessamentoEstados"
import { PainelBrasil } from "./partes/PainelBrasil"

const AGORA = Date.parse("2026-11-13T12:05:00Z")
function estado(uf = "PA"): ProcessamentoEstado {
  return { uf, escopo: "uf", unidade: null, municipios_total: 144,
    municipios: { prontos: 10, em_execucao: 2, com_erro: 0, pendentes: 132, desconhecidos: 0 },
    observado_em: "2026-11-13T12:04:00Z", ultima_mudanca_em: "2026-11-13T11:00:00Z", valido_ate: "2026-11-13T12:10:00Z", situacao: "atual" }
}
function documento(): ProcessamentoEstados {
  return { versao: 1, gerado_em: "2026-11-13T12:05:00Z", estados: Object.keys(UFS).map((uf) => estado(uf)) }
}
function carga(e = estado()): CargaProcessamento {
  const dado = documento()
  dado.estados = dado.estados.map((item) => item.uf === e.uf ? e : item)
  return { dado, erro: false, carregando: false, agora: AGORA }
}
function painel(e = estado(), uf: string | null = "PA") {
  return renderToStaticMarkup(createElement(PainelProcessamentoEstados, { carga: carga(e), uf }))
}
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe("fonte pública do processamento", () => {
  it("escolhe URL explícita, API pública ou fonte pública ao vivo sem token", async () => {
    vi.useFakeTimers()
    vi.setSystemTime(AGORA)
    expect(urlProcessamento({ VITE_RAIZ_PROCESSAMENTO_URL: " https://exemplo.test/painel ", VITE_RAIZ_API: "https://api.test" })).toBe("https://exemplo.test/painel")
    expect(urlProcessamento({ VITE_RAIZ_API: "https://api.test/base/" })).toBe("https://api.test/base/processamento/publico")
    const publica = "https://raw.githubusercontent.com/bernardoemmel/Raiz/status-processamento/processamento.json"
    expect(urlProcessamento({ BASE_URL: "/Raiz/" })).toBe(publica)
    expect(urlProcessamento({})).toBe(publica)
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(documento()), { headers: { "content-type": "application/json" } }))
    vi.stubGlobal("fetch", fetch)
    const controle = new AbortController()
    await buscarProcessamento("https://api.test/processamento/publico", controle.signal)
    expect(fetch).toHaveBeenCalledWith(`https://api.test/processamento/publico?_raiz_t=${Math.floor(AGORA / 30_000)}`, { signal: controle.signal, credentials: "omit", cache: "no-store" })
  })
  it("preserva zero, transforma contagem inválida em desconhecida e descarta campos extras", () => {
    const dado = documento()
    const recebido = { ...dado, segredo: "NAO_PUBLICAR", estados: dado.estados.map((e) => ({ ...e, cod_imovel: "NAO_PUBLICAR", municipios: { ...e.municipios, com_erro: 0, prontos: -1, em_execucao: undefined } })) }
    const lido = lerProcessamentoEstados(recebido)
    expect(lido.estados[0].municipios).toMatchObject({ com_erro: 0, prontos: null, em_execucao: null })
    expect(JSON.stringify(lido)).not.toContain("NAO_PUBLICAR")
  })
  it("recusa UFs faltantes, repetidas, desconhecidas e versão incompatível", () => {
    const dado = documento()
    expect(() => lerProcessamentoEstados({ ...dado, estados: dado.estados.slice(1) })).toThrow()
    expect(() => lerProcessamentoEstados({ ...dado, estados: [...dado.estados.slice(1), dado.estados[1]] })).toThrow()
    expect(() => lerProcessamentoEstados({ ...dado, estados: [...dado.estados.slice(1), estado("ZZ")] })).toThrow()
    expect(() => lerProcessamentoEstados({ ...dado, versao: 2 })).toThrow()
  })
  it("não rejuvenesce a observação quando a publicação é recente", () => {
    const dado = documento()
    dado.estados[0].valido_ate = "2026-11-13T12:04:59Z"
    const lido = lerProcessamentoEstados(dado)
    expect(lido.estados[0].valido_ate).toBe(dado.estados[0].valido_ate)
    expect(situacaoProcessamento(lido.estados[0], AGORA)).toBe("desatualizado")
    expect(situacaoProcessamento({ ...estado(), valido_ate: "2026-11-13T12:05:00Z" }, AGORA)).toBe("desatualizado")
  })
  it("data sem fuso, inválida ou observação futura não sustenta o agora", () => {
    const dado = documento()
    dado.estados[0].observado_em = "2026-11-13T12:04:00"
    dado.estados[0].ultima_mudanca_em = "data inválida"
    expect(lerProcessamentoEstados(dado).estados[0]).toMatchObject({ observado_em: null, ultima_mudanca_em: null })
    expect(situacaoProcessamento({ ...estado(), observado_em: "2026-11-14T12:00:00Z" }, AGORA)).toBe("desatualizado")
  })
  it("não copia rótulo livre da unidade e só aceita a UF correspondente", () => {
    const dado = documento()
    dado.estados[0].unidade = "NAO_PUBLICAR"
    dado.estados[1].unidade = "PA-2"
    dado.estados[2].unidade = `${dado.estados[2].uf}-1`
    const lido = lerProcessamentoEstados(dado)
    expect(lido.estados.slice(0, 3).map((e) => e.unidade)).toEqual([null, null, null])
    dado.estados[0].escopo = "unidade"
    dado.estados[0].unidade = `${dado.estados[0].uf}-1001`
    expect(lerProcessamentoEstados(dado).estados[0].unidade).toBe(dado.estados[0].unidade)
  })
  it("recusa total excessivo ou soma divergente em observação atual", () => {
    const dado = documento()
    dado.estados[0].municipios_total = 6001
    expect(() => lerProcessamentoEstados(dado)).toThrow("Contagens")
    dado.estados[0].municipios_total = 143
    expect(() => lerProcessamentoEstados(dado)).toThrow("Contagens")
    dado.estados[0].situacao = "desatualizado"
    dado.estados[0].municipios.em_execucao = null
    expect(lerProcessamentoEstados(dado).estados[0].municipios.em_execucao).toBeNull()
  })
  it.each([
    { valido_ate: "2026-11-13T13:04:01Z" },
    { valido_ate: "2026-11-13T12:04:00Z" },
    { ultima_mudanca_em: "2026-11-13T12:04:01Z" },
  ])("recusa prazo excessivo ou cronologia invertida: %j", (alteracao) => {
    const dado = documento()
    Object.assign(dado.estados[0], alteracao)
    expect(() => lerProcessamentoEstados(dado)).toThrow("Prazo")
  })
  it("recusa HTML do fallback estático e respostas HTTP de erro", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { headers: { "content-type": "text/html" } })))
    await expect(buscarProcessamento("/amostra/processamento.json", new AbortController().signal)).rejects.toThrow()
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })))
    await expect(buscarProcessamento("/amostra/processamento.json", new AbortController().signal)).rejects.toThrow()
  })
})

describe("painel por estado", () => {
  it("lista os 27 estados e filtra a UF sem depender da cobertura antiga", () => {
    const html = painel(estado(), null)
    expect(html.match(/class="processamento-estado"/g)).toHaveLength(27)
    expect(painel()).toContain("Pará")
    expect(painel()).not.toContain("São Paulo")
    const andamento = createElement(PainelProcessamentoEstados, { carga: carga(), uf: "PA" })
    const antigo = renderToStaticMarkup(createElement(PainelBrasil, { municipios: undefined, comLista: new Set<string>(), estados: undefined, uf: null, pontos: undefined, carregando: true, andamento }))
    expect(antigo).toContain("Processamento dos municípios")
  })
  it("encerra as reservas ao receber vazio ou erro, sem esconder a telemetria", () => {
    const props = { municipios: undefined, comLista: new Set<string>(), estados: undefined, uf: null, pontos: undefined,
      carregando: true, carregandoResumo: true, carregandoCobertura: true,
      andamento: createElement(PainelProcessamentoEstados, { carga: carga() }) }
    const pendente = renderToStaticMarkup(createElement(PainelBrasil, props))
    expect(pendente).toContain("resumo-brasil-carregando")
    expect(pendente).toContain("cobertura-carregando")
    expect(pendente.indexOf("Cobertura do mapa")).toBeLessThan(pendente.indexOf("Processamento dos municípios"))
    const erro = renderToStaticMarkup(createElement(PainelBrasil, { ...props, carregandoResumo: false, carregandoCobertura: false }))
    expect(erro).toContain("Não foi possível ler o resumo dos municípios")
    expect(erro).toContain("a data de atualização ainda não foram informadas")
    expect(erro).not.toContain("resumo-brasil-carregando")
    expect(erro).not.toContain("cobertura-carregando")
    const vazio = renderToStaticMarkup(createElement(PainelBrasil, { ...props, municipios: [], carregandoResumo: false, carregandoCobertura: false }))
    expect(vazio).toContain("Nenhum município processado ainda.")
    expect(vazio).not.toContain("resumo-brasil-carregando")
    expect(vazio).toContain("Processamento dos municípios")
  })
  it("mostra zero real e mantém desconhecido como não informado", () => {
    const e = estado()
    e.municipios.prontos = null
    const html = painel(e)
    expect(html).toMatch(/Municípios prontos<\/dt><dd>Não informado/)
    expect(html).toMatch(/Com erro<\/dt><dd>0/)
    expect(html).toMatch(/Rodando agora<\/dt><dd>2/)
  })
  it("esconde a contagem de agora vencida e identifica as demais como antigas", () => {
    const html = painel({ ...estado(), valido_ate: "2026-11-13T12:04:59Z" })
    expect(html).toContain("Sem atualização recente")
    expect(html).toContain("Contagens da última observação")
    expect(html).toMatch(/Rodando agora<\/dt><dd>Não informado/)
    expect(html).toMatch(/Municípios prontos<\/dt><dd>10/)
  })
  it("não apresenta uma unidade como total do estado", () => {
    const html = painel({ ...estado(), escopo: "unidade", unidade: "PA-2" })
    expect(html).toContain("Cobertura parcial: unidade PA-2")
    expect(html).not.toContain("144 municípios no estado")
  })
  it("distingue última mudança e observação em Brasília sem Invalid Date", () => {
    const html = painel()
    expect(html).toContain("Última mudança:")
    expect(html).toContain("08:00")
    expect(html).toContain("Observado em:")
    expect(html).toContain("09:04")
    const sem = painel({ ...estado(), ultima_mudanca_em: "inválida", observado_em: null, situacao: "sem_telemetria" })
    expect(sem).toContain("não informada")
    expect(sem).not.toContain("Invalid Date")
    expect(sem).toMatch(/Rodando agora<\/dt><dd>Não informado/)
  })
  it("comunica consulta inicial e indisponibilidade sem inventar contagens", () => {
    const inicial = { erro: false, carregando: true, agora: AGORA }
    expect(renderToStaticMarkup(createElement(PainelProcessamentoEstados, { carga: inicial }))).toContain("Consultando o processamento")
    const erro = renderToStaticMarkup(createElement(PainelProcessamentoEstados, { carga: { ...inicial, erro: true, carregando: false } }))
    expect(erro).toContain("Não foi possível atualizar")
    expect(erro).not.toContain("<dd>0</dd>")
  })
})

function visibilidade() {
  const alvo = Object.assign(new EventTarget(), { visibilityState: "visible" as DocumentVisibilityState })
  return { alvo, mudar(valor: DocumentVisibilityState) { alvo.visibilityState = valor; alvo.dispatchEvent(new Event("visibilitychange")) } }
}

describe("atualização periódica", () => {
  it("consulta a cada 30 segundos, pausa oculta e retoma sem credenciais", async () => {
    vi.useFakeTimers()
    const d = visibilidade()
    const ler = vi.fn().mockResolvedValue(documento())
    const notificar = vi.fn()
    const parar = acompanharProcessamento("/publico", notificar, d.alvo, ler)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(29_999)
    expect(ler).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(ler).toHaveBeenCalledTimes(2)
    d.mudar("hidden")
    await vi.advanceTimersByTimeAsync(90_000)
    expect(ler).toHaveBeenCalledTimes(2)
    d.mudar("visible")
    await vi.advanceTimersByTimeAsync(0)
    expect(ler).toHaveBeenCalledTimes(3)
    parar()
    await vi.advanceTimersByTimeAsync(90_000)
    expect(ler).toHaveBeenCalledTimes(3)
  })
  it("não sobrepõe consultas e descarta a resposta abortada ao ocultar", async () => {
    vi.useFakeTimers()
    const d = visibilidade()
    let concluir!: (dado: ProcessamentoEstados) => void
    const ler = vi.fn().mockImplementationOnce(() => new Promise<ProcessamentoEstados>((r) => { concluir = r })).mockResolvedValue(documento())
    const notificar = vi.fn()
    const parar = acompanharProcessamento("/publico", notificar, d.alvo, ler)
    await vi.advanceTimersByTimeAsync(10_000)
    d.mudar("hidden")
    expect(ler.mock.calls[0][1].aborted).toBe(true)
    d.mudar("visible")
    expect(ler).toHaveBeenCalledTimes(1)
    concluir(documento())
    await vi.advanceTimersByTimeAsync(0)
    expect(ler).toHaveBeenCalledTimes(2)
    expect(notificar.mock.calls.filter(([c]) => (c as CargaProcessamento).dado)).toHaveLength(1)
    parar()
  })
  it("preserva a última observação numa falha e ignora respostas após desmontar", async () => {
    vi.useFakeTimers()
    const d = visibilidade()
    const primeiro = documento()
    const ler = vi.fn().mockResolvedValueOnce(primeiro).mockRejectedValueOnce(new Error("indisponível"))
    const notificar = vi.fn()
    const parar = acompanharProcessamento("/publico", notificar, d.alvo, ler)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(notificar).toHaveBeenLastCalledWith(expect.objectContaining({ dado: primeiro, erro: true, carregando: false }))
    parar()
    let concluir!: (dado: ProcessamentoEstados) => void
    const pendente = vi.fn().mockImplementation(() => new Promise<ProcessamentoEstados>((r) => { concluir = r }))
    const observar = vi.fn()
    const limpar = acompanharProcessamento("/publico", observar, d.alvo, pendente)
    limpar()
    concluir(documento())
    await vi.advanceTimersByTimeAsync(0)
    expect(observar).toHaveBeenCalledTimes(1)
    expect(pendente.mock.calls[0][1].aborted).toBe(true)
  })
})
