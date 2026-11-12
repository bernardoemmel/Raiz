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
const servidor = http.createServer((req, res) => {
  pedidos.push(req.url ?? "")
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
  it("recusa manifesto legado e metadado desconhecido antes de pedir pacote", async () => {
    preparar(basicos)
    delete manifesto.escopo
    expect((await baixar(path.join(temp, "legado"))).sucesso).toBe(false)
    expect(pedidos).toEqual(["/estados.json"])
    preparar(basicos, { detalhe_privado: "não pode baixar" })
    expect((await baixar(path.join(temp, "desconhecido"))).sucesso).toBe(false)
    expect(pedidos).toEqual(["/estados.json"])
  })
  it("recusa metadados permitidos malformados e CAR de outra UF", async () => {
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
