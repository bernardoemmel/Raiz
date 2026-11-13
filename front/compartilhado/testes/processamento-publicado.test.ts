import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { lerProcessamentoPublicado } from "../dados/processamento-publicado"
import { situacaoProcessamento } from "../dados/processamento-estados"
import { abrirPasta } from "../pasta-dados"
import { dadosRaiz } from "../vite-dados"

const AGORA = Date.parse("2026-11-13T10:01:00Z")
const observacao = () => ({
  versao: 1, escopo: "unidade", unidade: "PA-1001", municipios_total: 10,
  municipios: { prontos: 4, em_execucao: 1, com_erro: 2, pendentes: 2, desconhecidos: 1 },
  observado_em: "2026-11-13T10:00:00Z", ultima_mudanca_em: "2026-11-13T09:59:30Z", valido_ate: "2026-11-13T10:02:00Z",
})

describe("contrato estrito da observação publicada", () => {
  it("aceita UF e unidade com contagens exclusivas e preserva os instantes literais", () => {
    const origem = observacao()
    const estado = lerProcessamentoPublicado(origem, "PA")!
    expect(estado).toEqual({ uf: "PA", ...origem, versao: undefined, situacao: "atual" })
    expect(estado.observado_em).toBe(origem.observado_em)
    expect(lerProcessamentoPublicado({ ...origem, escopo: "uf", unidade: "PA" }, "PA")?.escopo).toBe("uf")
    expect(lerProcessamentoPublicado({ ...origem, unidade: "PA" }, "PA")?.escopo).toBe("unidade")
    expect(lerProcessamentoPublicado({ ...origem, valido_ate: "2026-11-13T11:00:00Z" }, "PA")).not.toBeNull()
  })

  it.each([
    { detalhe_privado: "CAR-NAO-PUBLICAR" },
    { erro: "Mensagem privada" },
    { versao: 2 },
    { escopo: "job" },
    { unidade: "MT-2" },
    { unidade: "PA-0" },
    { unidade: "PA-999999" },
    { unidade: "PA-1504950-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" },
    { unidade: "PA-2\n" },
    { municipios_total: 9 },
    { municipios_total: 10.5 },
    { municipios_total: true },
    { municipios_total: 6001, municipios: { prontos: 6001, em_execucao: 0, com_erro: 0, pendentes: 0, desconhecidos: 0 } },
    { municipios: { ...observacao().municipios, cod_imovel: "CAR-NAO-PUBLICAR" } },
    { municipios: { ...observacao().municipios, em_execucao: -1 } },
    { municipios: { ...observacao().municipios, prontos: "4" } },
    { municipios: { ...observacao().municipios, prontos: null } },
    { observado_em: "2026-11-13T10:00:00" },
    { observado_em: "2026-02-30T10:00:00Z" },
    { observado_em: "2026-11-13T24:00:00Z" },
    { observado_em: "2026-11-13T10:00:00Z\n" },
    { ultima_mudanca_em: "2026-11-13T10:01:00Z" },
    { valido_ate: "2026-11-13T11:00:01Z" },
    { valido_ate: "2026-11-13T09:59:00Z" },
  ])("recusa integralmente observação fora do contrato: %j", (alteracao) => {
    expect(lerProcessamentoPublicado({ ...observacao(), ...alteracao }, "PA")).toBeNull()
  })

  it("aceita outros fusos explícitos e não ajusta sua representação no DTO", () => {
    const origem = { ...observacao(), observado_em: "2026-11-13T07:00:00.123456-03:00", valido_ate: "2026-11-13T07:02:00-03:00" }
    expect(lerProcessamentoPublicado(origem, "PA")?.observado_em).toBe(origem.observado_em)
  })
})

describe("ponte pública do painel em desenvolvimento e build", () => {
  let repo: string
  beforeEach(() => {
    repo = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-ponte-processamento-"))
    fs.mkdirSync(path.join(repo, "dados", "publicos"), { recursive: true })
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(AGORA)
    vi.spyOn(console, "log").mockImplementation(() => {})
    vi.stubEnv("RAIZ_BUILD_DADOS", "1")
    vi.stubEnv("RAIZ_GEO", path.join(repo, "geo"))
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
    vi.unstubAllEnvs()
    fs.rmSync(repo, { recursive: true, force: true })
  })

  function manifesto(processamento: unknown = observacao(), publico = true) {
    const m = { versao_publicacao: 1, escopo: publico ? "publico_basico" : "privado", gerado_em: "2026-11-13T09:00:00Z", estados: {
      PA: { versao_publicacao: 1, escopo: "publico_basico", municipios: 144, completo: true, feito: 144, running: true,
        processamento, detalhe_privado: "NAO_PUBLICAR" },
    } }
    fs.writeFileSync(path.join(repo, "dados", "publicos", "estados.json"), JSON.stringify(m))
  }
  const pasta = () => abrirPasta({ repo, raizDados: "dados/publicos" })
  const estado = (dados: ReturnType<ReturnType<typeof pasta>["processamento"]>) => dados.estados.find((e) => e.uf === "PA")!

  it("gera 27 UFs sem depender de CSVs e nunca usa completo, feito ou job como telemetria", () => {
    manifesto()
    const dados = pasta().processamento(AGORA)
    expect(dados.estados).toHaveLength(27)
    expect(dados.gerado_em).toBe("2026-11-13T10:01:00.000Z")
    expect(estado(dados).municipios.prontos).toBe(4)
    expect(estado(dados).situacao).toBe("atual")
    const outros = dados.estados.filter((e) => e.uf !== "PA")
    expect(outros.every((e) => e.situacao === "sem_telemetria" && e.municipios_total === null &&
      Object.values(e.municipios).every((n) => n === null))).toBe(true)
    expect(JSON.stringify(dados)).not.toMatch(/NAO_PUBLICAR|running|completo|feito|detalhe_privado/)
  })

  it.each([undefined, null, { ...observacao(), cod_imovel: "NAO_PUBLICAR" }])("campos ausentes ou inválidos ficam indisponíveis", (origem) => {
    manifesto(origem === undefined ? null : origem)
    if (origem === undefined) {
      const arq = path.join(repo, "dados", "publicos", "estados.json")
      const m = JSON.parse(fs.readFileSync(arq, "utf8"))
      delete m.estados.PA.processamento
      fs.writeFileSync(arq, JSON.stringify(m))
    }
    const dados = pasta().processamento(AGORA)
    expect(dados.estados.every((e) => e.situacao === "sem_telemetria")).toBe(true)
    expect(estado(dados).municipios.prontos).toBeNull()
    expect(JSON.stringify(dados)).not.toContain("NAO_PUBLICAR")
  })

  it("não projeta manifesto privado ou amostra antiga como processamento público", () => {
    manifesto(observacao(), false)
    expect(pasta().processamento(AGORA).estados.every((e) => e.situacao === "sem_telemetria")).toBe(true)
    fs.rmSync(path.join(repo, "dados", "publicos", "estados.json"))
    expect(pasta().processamento(AGORA).estados.every((e) => e.observado_em === null)).toBe(true)
  })

  it("reavalia a validade no cache sem renovar nenhum timestamp da observação", () => {
    manifesto()
    const p = pasta()
    const antes = estado(p.processamento(AGORA))
    const depois = estado(p.processamento(AGORA + 120_000))
    expect(antes.situacao).toBe("atual")
    expect(depois.situacao).toBe("desatualizado")
    for (const campo of ["observado_em", "ultima_mudanca_em", "valido_ate"] as const) expect(depois[campo]).toBe(antes[campo])
    expect(situacaoProcessamento(antes, AGORA + 120_000)).toBe("desatualizado")
  })

  it("serve o JSON em dev com cache revalidável, sem devolver metadados privados", async () => {
    manifesto()
    const plugin = dadosRaiz({ repo, raizDados: "dados/publicos" })
    let chamada: (req: unknown, res: unknown, next: () => void) => void
    plugin.configureServer({ middlewares: { use: (fn: typeof chamada) => { chamada = fn } } } as never)
    const cabecalhos: Record<string, unknown> = {}
    const resposta = await new Promise<string>((resolve) => {
      chamada({ url: "/amostra/processamento.json", headers: {} }, {
        statusCode: 200, setHeader: (nome: string, valor: unknown) => { cabecalhos[nome] = valor },
        end: (dado: string) => resolve(dado),
      }, () => resolve("NAO_ENCONTRADO"))
    })
    expect(JSON.parse(resposta).estados).toHaveLength(27)
    expect(cabecalhos["Cache-Control"]).toBe("no-cache")
    expect(resposta).not.toContain("NAO_PUBLICAR")
  })

  it.each(["1", "0"])("build gera o fallback inclusive com RAIZ_BUILD_DADOS=%s, sem renovar lease", async (comDados) => {
    manifesto()
    vi.stubEnv("RAIZ_BUILD_DADOS", comDados)
    vi.setSystemTime(AGORA + 120_000)
    const plugin = dadosRaiz({ repo, raizDados: "dados/publicos" })
    const saida = path.join(repo, "dist")
    fs.mkdirSync(saida)
    plugin.configResolved({ root: repo, command: "build", build: { outDir: saida } })
    await plugin.closeBundle()
    const dados = JSON.parse(fs.readFileSync(path.join(saida, "amostra", "processamento.json"), "utf8"))
    const pa = dados.estados.find((e: { uf: string }) => e.uf === "PA")
    expect(dados.estados).toHaveLength(27)
    expect(pa.situacao).toBe("desatualizado")
    expect(pa.observado_em).toBe(observacao().observado_em)
    expect(pa.ultima_mudanca_em).toBe(observacao().ultima_mudanca_em)
    expect(pa.valido_ate).toBe(observacao().valido_ate)
    expect(JSON.stringify(dados)).not.toContain("NAO_PUBLICAR")
  })
})
