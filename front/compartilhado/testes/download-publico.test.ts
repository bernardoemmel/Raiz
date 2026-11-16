import { execFile, execFileSync } from "node:child_process"
import fs from "node:fs"
import http from "node:http"
import os from "node:os"
import path from "node:path"
import { promisify } from "node:util"
import { afterAll, beforeAll, describe, expect, it } from "vitest"

const executar = promisify(execFile)
const script = path.resolve(__dirname, "../../scripts/baixar-dados.mjs")
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-download-publico-"))
const car = "PA-1504950-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
const header = "cod_imovel,cod_ibge,municipio,uf,situacao_basica\n"
let manifesto: Record<string, unknown>
let pacote: Buffer
let base: string
const pedidos: string[] = []
let responder: ((req: http.IncomingMessage, res: http.ServerResponse) => boolean) | null = null
const servidor = http.createServer((req, res) => {
  pedidos.push(req.url ?? "")
  if (responder?.(req, res)) return
  if (req.url === "/estados.json") { res.setHeader("content-type", "application/json"); res.end(JSON.stringify(manifesto)) }
  else if (req.url === "/raiz_PA.tar.gz") res.end(pacote)
  else { res.statusCode = 404; res.end() }
})
beforeAll(async () => {
  await new Promise<void>((resolve) => servidor.listen(0, "127.0.0.1", resolve))
  base = `http://127.0.0.1:${(servidor.address() as { port: number }).port}`
})
afterAll(async () => {
  await new Promise<void>((resolve, reject) => servidor.close((e) => e ? reject(e) : resolve()))
  fs.rmSync(temp, { recursive: true, force: true })
})
function preparar(arquivos: Record<string, string>, extras: Record<string, unknown> = {}) {
  const origem = fs.mkdtempSync(path.join(temp, "pacote-"))
  fs.mkdirSync(path.join(origem, "PA"))
  for (const [nome, texto] of Object.entries(arquivos)) fs.writeFileSync(path.join(origem, "PA", nome), texto)
  const tar = path.join(origem, "pacote.tar.gz")
  execFileSync("tar", ["-czf", tar, "-C", origem, ...Object.keys(arquivos).map((n) => `PA/${n}`)])
  pacote = fs.readFileSync(tar)
  manifesto = { versao_publicacao: 1, escopo: "publico_basico", estados: { PA: {
    versao_publicacao: 1, escopo: "publico_basico", municipios: 1, total_ibge: 144, completo: false,
    url: `${base}/raiz_PA.tar.gz`, versao: "nova", tamanho: pacote.length, ...extras,
  } } }
  pedidos.length = 0
  responder = null
}
async function baixar(destino: string) {
  try {
    const r = await executar(process.execPath, [script, "--exigir"], { env: { ...process.env, RAIZ_SEM_DOWNLOAD: "", RAIZ_DADOS: destino, RAIZ_DADOS_URL: base } })
    return { sucesso: true, texto: r.stdout + r.stderr }
  } catch (e) {
    const r = e as { stdout: string; stderr: string }
    return { sucesso: false, texto: r.stdout + r.stderr }
  }
}
const basicos = { "imoveis_basicos_1504950.csv": `${header}${car},1504950,Cumaru do Norte,PA,apto\n` }
const processamento = () => ({
  versao: 1, escopo: "uf", unidade: "PA", municipios_total: 144,
  municipios: { prontos: 100, em_execucao: 1, com_erro: 2, pendentes: 40, desconhecidos: 1 },
  observado_em: "2026-11-13T10:00:00+00:00", ultima_mudanca_em: "2026-11-13T09:59:00+00:00", valido_ate: "2026-11-13T10:02:00+00:00",
})

describe("download fechado ao contrato público", () => {
  it("baixa somente básicos e mantém todos os portes sem medidas privadas", async () => {
    preparar(basicos)
    const destino = path.join(temp, "valido")
    expect((await baixar(destino)).sucesso).toBe(true)
    expect(fs.readdirSync(path.join(destino, "PA"))).toEqual(["imoveis_basicos_1504950.csv"])
    expect(fs.readFileSync(path.join(destino, "PA", "imoveis_basicos_1504950.csv"), "utf8")).toContain(car)
    expect(JSON.parse(fs.readFileSync(path.join(destino, "estados.json"), "utf8")).escopo).toBe("publico_basico")
  })
  it("aceita metadados do Release público e CAR cadastrado no município vizinho", async () => {
    const vizinho = "PA-1504802-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    preparar({ "imoveis_basicos_1504950.csv": `${header}${vizinho},1504950,Cumaru do Norte,PA,com_pendencia\n` }, {
      geo: { escopo: "publico_basico", municipios: 1, versao: "geo-v1", tamanho: 123, url: `${base}/raiz_geo_PA.tar.gz` },
    })
    manifesto.repo = "bernardoemmel/Raiz"
    manifesto.tag = "dados"
    const destino = path.join(temp, "contrato-release")
    expect((await baixar(destino)).sucesso).toBe(true)
    expect(fs.readFileSync(path.join(destino, "PA", "imoveis_basicos_1504950.csv"), "utf8")).toContain(vizinho)
  })
  it("preserva CAR de outra UF quando origem cadastral e recorte são coerentes", async () => {
    const fronteira = "MT-5100201-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
    const conteudo = `${header}${fronteira},1504950,Cumaru do Norte,PA,apto\n`
    preparar({ "imoveis_basicos_1504950.csv": conteudo })
    const destino = path.join(temp, "fronteira-uf")
    expect((await baixar(destino)).sucesso).toBe(true)
    expect(fs.readFileSync(path.join(destino, "PA", "imoveis_basicos_1504950.csv"), "utf8")).toBe(conteudo)
    preparar({ "imoveis_basicos_1504950.csv": `${header}${fronteira},1504950,Cumaru do Norte,MT,apto\n` })
    expect((await baixar(path.join(temp, "recorte-uf-divergente"))).sucesso).toBe(false)
  })
  it("recusa origem cadastral desconhecida e município de outra UF dentro do pacote", async () => {
    preparar({ "imoveis_basicos_1504950.csv": `${header}${car.replace("PA-", "ZZ-")},1504950,Cumaru do Norte,PA,apto\n` })
    expect((await baixar(path.join(temp, "car-uf-desconhecida"))).sucesso).toBe(false)
    preparar({ "imoveis_basicos_2413409.csv": `${header}${car},2413409,Serra Negra do Norte,PA,apto\n` })
    expect((await baixar(path.join(temp, "pacote-municipio-divergente"))).sucesso).toBe(false)
  })
  it("recusa manifesto legado e metadado desconhecido antes de pedir pacote", async () => {
    preparar(basicos)
    delete manifesto.escopo
    expect((await baixar(path.join(temp, "legado"))).sucesso).toBe(false)
    expect(pedidos).toEqual(["/estados.json"])
    preparar(basicos, { detalhe_privado: "não pode baixar" })
    expect((await baixar(path.join(temp, "desconhecido"))).sucesso).toBe(false)
    expect(pedidos).toEqual(["/estados.json"])
  })
  it("recusa metadados permitidos malformados e origem cadastral incoerente", async () => {
    preparar(basicos)
    manifesto.repo = "empresa/repo/privado"
    expect((await baixar(path.join(temp, "repo-invalido"))).sucesso).toBe(false)
    expect(pedidos).toEqual(["/estados.json"])
    preparar(basicos, { geo: { escopo: "publico_basico", municipios: "detalhe privado", url: `${base}/raiz_geo_PA.tar.gz` } })
    expect((await baixar(path.join(temp, "geo-invalido"))).sucesso).toBe(false)
    expect(pedidos).toEqual(["/estados.json"])
    preparar({ "imoveis_basicos_1504950.csv": `${header}${car.replace("PA-", "MT-")},1504950,Cumaru do Norte,PA,apto\n` })
    expect((await baixar(path.join(temp, "uf-divergente"))).sucesso).toBe(false)
  })
  it("recusa complementos e coluna extra sem substituir a última publicação válida", async () => {
    const destino = path.join(temp, "preservado")
    preparar(basicos)
    expect((await baixar(destino)).sucesso).toBe(true)
    preparar({ ...basicos, "filtros_1504950.csv": "cod_imovel,risco\n" })
    ;(manifesto.estados as Record<string, Record<string, unknown>>).PA.versao = "invalida"
    expect((await baixar(destino)).sucesso).toBe(false)
    expect(fs.readdirSync(path.join(destino, "PA"))).toEqual(["imoveis_basicos_1504950.csv"])
    preparar({ "imoveis_basicos_1504950.csv": header.trim() + ",credito_p50\n" })
    expect((await baixar(path.join(temp, "coluna-privada"))).sucesso).toBe(false)
  })
  it("não apaga dados legados de um RAIZ_DADOS apontado para a saída do motor", async () => {
    preparar(basicos)
    const destino = path.join(temp, "motor-saida")
    fs.mkdirSync(path.join(destino, "PA"), { recursive: true })
    fs.writeFileSync(path.join(destino, "PA", "imoveis_1504950.csv"), "arquivo privado local")
    const r = await baixar(destino)
    expect(r.sucesso).toBe(false)
    expect(r.texto).toContain("destino legado preservado")
    expect(fs.readFileSync(path.join(destino, "PA", "imoveis_1504950.csv"), "utf8")).toBe("arquivo privado local")
  })
})

describe("compatibilidade estrita com a telemetria pública municipal", () => {
  it.each([
    processamento(),
    { ...processamento(), escopo: "unidade", unidade: "PA-2" },
    { ...processamento(), observado_em: "2020-01-01T08:00:00-03:00", ultima_mudanca_em: "2020-01-01T07:59:00-03:00", valido_ate: "2020-01-01T09:00:00-03:00" },
  ])("preserva a observação pública validada e seus horários, inclusive quando vencida: %j", async (observacao) => {
    preparar(basicos, { processamento: observacao })
    const destino = fs.mkdtempSync(path.join(temp, "telemetria-valida-"))
    expect((await baixar(destino)).sucesso).toBe(true)
    const salvo = JSON.parse(fs.readFileSync(path.join(destino, "estados.json"), "utf8"))
    expect(salvo.estados.PA.processamento).toEqual(observacao)
    expect(salvo.estados.PA.municipios).toBe(1)
    expect(fs.readdirSync(path.join(destino, "PA"))).toEqual(["imoveis_basicos_1504950.csv"])
  })

  it("preserva telemetria válida do cache existente sem baixar de novo o mesmo pacote", async () => {
    preparar(basicos)
    const destino = path.join(temp, "telemetria-no-cache")
    expect((await baixar(destino)).sucesso).toBe(true)
    const arq = path.join(destino, "estados.json")
    const local = JSON.parse(fs.readFileSync(arq, "utf8"))
    local.estados.PA.processamento = processamento()
    fs.writeFileSync(arq, JSON.stringify(local))
    preparar(basicos, { processamento: processamento() })
    expect((await baixar(destino)).sucesso).toBe(true)
    expect(pedidos).toEqual(["/estados.json"])
    expect(JSON.parse(fs.readFileSync(arq, "utf8")).estados.PA.processamento).toEqual(processamento())
  })

  it("mantém zero cobertura sem URL e preserva separadamente a observação operacional", async () => {
    preparar(basicos, { processamento: processamento(), municipios: 0, tamanho: 0, url: undefined })
    const destino = path.join(temp, "telemetria-sem-pacote")
    expect((await baixar(destino)).sucesso).toBe(true)
    expect(pedidos).toEqual(["/estados.json"])
    const salvo = JSON.parse(fs.readFileSync(path.join(destino, "estados.json"), "utf8"))
    expect(salvo.estados.PA.municipios).toBe(0)
    expect(salvo.estados.PA.processamento).toEqual(processamento())
  })

  it("recusa cache inválido mesmo quando o manifesto remoto não oferece estados", async () => {
    preparar(basicos)
    const destino = path.join(temp, "cache-invalido-remoto-vazio")
    expect((await baixar(destino)).sucesso).toBe(true)
    const arq = path.join(destino, "estados.json")
    const local = JSON.parse(fs.readFileSync(arq, "utf8"))
    local.estados.PA.processamento = { ...processamento(), erro: "MENSAGEM_PRIVADA" }
    const anterior = JSON.stringify(local)
    fs.writeFileSync(arq, anterior)
    manifesto.estados = {}
    pedidos.length = 0
    const resultado = await baixar(destino)
    expect(resultado.sucesso).toBe(false)
    expect(resultado.texto).toContain("manifesto local fora do contrato público")
    expect(resultado.texto).not.toContain("MENSAGEM_PRIVADA")
    expect(pedidos).toEqual(["/estados.json"])
    expect(fs.readFileSync(arq, "utf8")).toBe(anterior)
  })

  it.each([
    null,
    [],
    { ...processamento(), versao: 2 },
    { ...processamento(), erro: "MENSAGEM_PRIVADA" },
    { ...processamento(), cod_imovel: car },
    { ...processamento(), municipios: { ...processamento().municipios, identificadores: [car] } },
    { ...processamento(), municipios: { ...processamento().municipios, prontos: "100" } },
    { ...processamento(), municipios: { ...processamento().municipios, em_execucao: true } },
    { ...processamento(), municipios: { ...processamento().municipios, prontos: -1 } },
    { ...processamento(), municipios: { ...processamento().municipios, prontos: 0.5 } },
    { ...processamento(), municipios: { ...processamento().municipios, prontos: 99 } },
    { ...processamento(), municipios_total: 6001 },
    { ...processamento(), unidade: "GO" },
    { ...processamento(), unidade: car },
    { ...processamento(), unidade: "PA-2" },
    { ...processamento(), escopo: "unidade", unidade: "PA-0" },
    { ...processamento(), observado_em: "2026-11-13T10:00:00" },
    { ...processamento(), observado_em: "2026-02-30T10:00:00Z" },
    { ...processamento(), ultima_mudanca_em: "2026-11-13T10:01:00Z" },
    { ...processamento(), valido_ate: "2026-11-13T10:00:00Z" },
    { ...processamento(), valido_ate: "2026-11-13T11:00:01Z" },
    { ...processamento(), valido_ate: undefined },
  ])("recusa bloco inválido antes de baixar pacotes e não ecoa seus valores: %j", async (observacao) => {
    preparar(basicos, { processamento: observacao })
    const destino = fs.mkdtempSync(path.join(temp, "telemetria-invalida-"))
    const resultado = await baixar(destino)
    expect(resultado.sucesso).toBe(false)
    expect(resultado.texto).not.toContain(car)
    expect(resultado.texto).not.toContain("MENSAGEM_PRIVADA")
    expect(pedidos).toEqual(["/estados.json"])
    expect(fs.existsSync(path.join(destino, "estados.json"))).toBe(false)
  })
})

describe("novas tentativas apenas para transporte e HTTP transitório", () => {
  it("aceita manifesto UTF-8 com BOM sem repetir a leitura", async () => {
    preparar(basicos)
    responder = (req, res) => {
      if (req.url !== "/estados.json") return false
      res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" }).end(Buffer.concat([
        Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from(JSON.stringify(manifesto)),
      ]))
      return true
    }
    const destino = path.join(temp, "manifesto-com-bom")
    expect((await baixar(destino)).sucesso).toBe(true)
    expect(pedidos).toEqual(["/estados.json", "/raiz_PA.tar.gz"])
    expect(fs.readFileSync(path.join(destino, "PA", "imoveis_basicos_1504950.csv"), "utf8")).toContain(car)
  }, 8000)

  it("repete a leitura do manifesto quando a conexão fecha antes dos cabeçalhos", async () => {
    preparar(basicos)
    let tentativas = 0
    responder = (req) => {
      if (req.url !== "/estados.json" || ++tentativas !== 1) return false
      req.socket.destroy()
      return true
    }
    const destino = path.join(temp, "conexao-interrompida")
    expect((await baixar(destino)).sucesso).toBe(true)
    expect(pedidos).toEqual(["/estados.json", "/estados.json", "/raiz_PA.tar.gz"])
    expect(fs.readFileSync(path.join(destino, "PA", "imoveis_basicos_1504950.csv"), "utf8")).toContain(car)
  }, 8000)

  it("repete o pacote com corpo HTTP 200 truncado antes de extrair", async () => {
    preparar(basicos)
    let tentativas = 0
    responder = (req, res) => {
      if (req.url !== "/raiz_PA.tar.gz" || ++tentativas !== 1) return false
      res.writeHead(200, { "Content-Length": pacote.length, Connection: "close" })
      res.end(pacote.subarray(0, Math.floor(pacote.length / 2)))
      return true
    }
    const destino = path.join(temp, "corpo-interrompido")
    expect((await baixar(destino)).sucesso).toBe(true)
    expect(pedidos).toEqual(["/estados.json", "/raiz_PA.tar.gz", "/raiz_PA.tar.gz"])
    expect(fs.readFileSync(path.join(destino, "PA", "imoveis_basicos_1504950.csv"), "utf8")).toContain(car)
  }, 8000)

  it.each([408, 429, 503])("repete HTTP %s e publica somente o pacote válido da nova tentativa", async (status) => {
    preparar(basicos)
    let tentativas = 0
    responder = (req, res) => {
      if (req.url !== "/raiz_PA.tar.gz" || ++tentativas !== 1) return false
      res.writeHead(status).end("indisponível temporariamente")
      return true
    }
    expect((await baixar(path.join(temp, `http-${status}`))).sucesso).toBe(true)
    expect(pedidos).toEqual(["/estados.json", "/raiz_PA.tar.gz", "/raiz_PA.tar.gz"])
  }, 8000)

  it.each(["/estados.json", "/raiz_PA.tar.gz"])("não repete HTTP 404 em %s", async (alvo) => {
    preparar(basicos)
    responder = (req, res) => {
      if (req.url !== alvo) return false
      res.writeHead(404).end("não publicado")
      return true
    }
    const destino = path.join(temp, `http-404-${alvo === "/estados.json" ? "manifesto" : "pacote"}`)
    expect((await baixar(destino)).sucesso).toBe(false)
    expect(pedidos.filter((url) => url === alvo)).toHaveLength(1)
    expect(fs.existsSync(path.join(destino, "estados.json"))).toBe(false)
  }, 8000)

  it("encerra uma falha transitória persistente após exatamente três tentativas", async () => {
    preparar(basicos)
    responder = (req, res) => {
      if (req.url !== "/raiz_PA.tar.gz") return false
      res.writeHead(503).end("indisponível temporariamente")
      return true
    }
    const destino = path.join(temp, "http-503-persistente")
    expect((await baixar(destino)).sucesso).toBe(false)
    expect(pedidos).toEqual(["/estados.json", "/raiz_PA.tar.gz", "/raiz_PA.tar.gz", "/raiz_PA.tar.gz"])
    expect(fs.existsSync(path.join(destino, "PA"))).toBe(false)
  }, 8000)

  it("não repete JSON malformado recebido por inteiro", async () => {
    preparar(basicos)
    responder = (req, res) => {
      if (req.url !== "/estados.json") return false
      res.writeHead(200, { "Content-Type": "application/json" }).end("{json inválido")
      return true
    }
    expect((await baixar(path.join(temp, "json-malformado"))).sucesso).toBe(false)
    expect(pedidos).toEqual(["/estados.json"])
  }, 8000)

  it("não repete manifesto recebido com campo fora do contrato público", async () => {
    preparar(basicos)
    manifesto.detalhe_privado = "campo proibido"
    expect((await baixar(path.join(temp, "manifesto-fechado"))).sucesso).toBe(false)
    expect(pedidos).toEqual(["/estados.json"])
  }, 8000)

  it("não repete um arquivo completo que não é um pacote tar válido", async () => {
    preparar(basicos)
    pacote = Buffer.from("arquivo completo, mas não é um tar gzip")
    const destino = path.join(temp, "tar-malformado")
    expect((await baixar(destino)).sucesso).toBe(false)
    expect(pedidos).toEqual(["/estados.json", "/raiz_PA.tar.gz"])
    expect(fs.existsSync(path.join(destino, "PA"))).toBe(false)
  }, 8000)

  it("não repete pacote íntegro com coluna fora do contrato público", async () => {
    preparar({ "imoveis_basicos_1504950.csv": header.trim() + ",credito_p50\n" })
    const destino = path.join(temp, "csv-fechado")
    expect((await baixar(destino)).sucesso).toBe(false)
    expect(pedidos).toEqual(["/estados.json", "/raiz_PA.tar.gz"])
    expect(fs.existsSync(path.join(destino, "PA"))).toBe(false)
  }, 8000)
})
