import { execFile, execFileSync } from "node:child_process"
import fs from "node:fs"
import http from "node:http"
import os from "node:os"
import path from "node:path"
import { promisify } from "node:util"
import { afterAll, beforeAll, expect, it } from "vitest"

const executar = promisify(execFile)
const script = path.resolve(__dirname, "../../scripts/baixar-dados.mjs")
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-download-processamento-"))
const car = "PA-1504950-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
const observacao = () => ({
  versao: 1, escopo: "uf", unidade: "PA", municipios_total: 144,
  municipios: { prontos: 100, em_execucao: 1, com_erro: 2, pendentes: 40, desconhecidos: 1 },
  observado_em: "2026-11-13T10:00:00Z", ultima_mudanca_em: "2026-11-13T09:59:00Z", valido_ate: "2026-11-13T10:02:00Z",
})
let manifesto: Record<string, unknown>, base: string, pacote: Buffer
const pedidos: string[] = []
const servidor = http.createServer((req, res) => {
  pedidos.push(req.url ?? "")
  if (req.url === "/estados.json") res.end(JSON.stringify(manifesto))
  else if (req.url === "/raiz_PA.tar.gz") res.end(pacote)
  else { res.statusCode = 404; res.end() }
})
beforeAll(async () => {
  await new Promise<void>((resolve) => servidor.listen(0, "127.0.0.1", resolve))
  base = `http://127.0.0.1:${(servidor.address() as { port: number }).port}`
  const origem = path.join(temp, "origem")
  fs.mkdirSync(path.join(origem, "PA"), { recursive: true })
  fs.writeFileSync(path.join(origem, "PA", "imoveis_basicos_1504950.csv"),
    `cod_imovel,cod_ibge,municipio,uf,situacao_basica\n${car},1504950,Cumaru do Norte,PA,apto\n`)
  const arq = path.join(temp, "pacote.tar.gz")
  execFileSync("tar", ["-czf", arq, "-C", origem, "PA/imoveis_basicos_1504950.csv"])
  pacote = fs.readFileSync(arq)
})
afterAll(async () => {
  await new Promise<void>((resolve) => servidor.close(() => resolve()))
  fs.rmSync(temp, { recursive: true, force: true })
})
function preparar(processamento: unknown = observacao()) {
  manifesto = { versao_publicacao: 1, escopo: "publico_basico", estados: { PA: {
    versao_publicacao: 1, escopo: "publico_basico", municipios: 1, total_ibge: 144, completo: false,
    url: `${base}/raiz_PA.tar.gz`, versao: "mesmo-pacote", tamanho: pacote.length,
    ...(processamento !== null ? { processamento } : {}),
  } } }
  pedidos.length = 0
}
async function baixar(destino: string) {
  try {
    const r = await executar(process.execPath, [script, "--exigir"], {
      env: { ...process.env, RAIZ_SEM_DOWNLOAD: "", RAIZ_DADOS: destino, RAIZ_DADOS_URL: base },
    })
    return { sucesso: true, texto: r.stdout + r.stderr }
  } catch (erro) {
    const r = erro as { stdout: string; stderr: string }
    return { sucesso: false, texto: r.stdout + r.stderr }
  }
}
const ler = (destino: string) => JSON.parse(fs.readFileSync(path.join(destino, "estados.json"), "utf8"))

it("atualiza observação sem baixar novamente pacote idêntico e preserva os horários originais", async () => {
  preparar()
  const destino = path.join(temp, "atualizar")
  expect((await baixar(destino)).sucesso).toBe(true)
  expect(ler(destino).estados.PA.processamento).toEqual(observacao())
  const nova = { ...observacao(), observado_em: "2026-11-13T10:01:00Z", valido_ate: "2026-11-13T10:03:00Z" }
  preparar(nova)
  expect((await baixar(destino)).sucesso).toBe(true)
  expect(pedidos).toEqual(["/estados.json"])
  expect(ler(destino).estados.PA.processamento).toEqual(nova)
  preparar(null)
  expect((await baixar(destino)).sucesso).toBe(true)
  expect(pedidos).toEqual(["/estados.json"])
  expect(ler(destino).estados.PA.processamento).toBeUndefined()
})

it.each([
  { erro: "MENSAGEM_PRIVADA" },
  { cod_imovel: car },
  { municipios: { ...observacao().municipios, identificadores: [car] } },
  { municipios: { ...observacao().municipios, prontos: "100" } },
  { municipios: { ...observacao().municipios, prontos: 99 } },
  { unidade: car },
  { observado_em: "2026-11-13T10:00:00" },
  { valido_ate: "2026-11-13T11:01:00Z" },
])("recusa processamento fora da allowlist antes de baixar pacote: %j", async (extra) => {
  preparar({ ...observacao(), ...extra })
  const destino = fs.mkdtempSync(path.join(temp, "rejeitar-"))
  const resultado = await baixar(destino)
  expect(resultado.sucesso).toBe(false)
  expect(resultado.texto).not.toContain(car)
  expect(resultado.texto).not.toContain("MENSAGEM_PRIVADA")
  expect(pedidos).toEqual(["/estados.json"])
  expect(fs.existsSync(path.join(destino, "estados.json"))).toBe(false)
})

it("metadado anterior sem processamento permanece compatível", async () => {
  preparar(null)
  const destino = path.join(temp, "legado-sem-telemetria")
  expect((await baixar(destino)).sucesso).toBe(true)
  expect(ler(destino).estados.PA.processamento).toBeUndefined()
})
