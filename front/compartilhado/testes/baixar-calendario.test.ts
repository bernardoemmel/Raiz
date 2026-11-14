import fs from "node:fs"
import os from "node:os"
import { createServer } from "node:http"
import path from "node:path"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { baixarCalendario } from "../../scripts/baixar-calendario.mjs"
import { fonteCalendario, lerAgenda } from "../calendario"

let destino: string
beforeEach(() => { destino = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-calendario-")); vi.stubEnv("RAIZ_CALENDARIO_DADOS", ""); vi.stubEnv("RAIZ_SEM_DOWNLOAD", "0") })
afterEach(() => { vi.unstubAllEnvs(); fs.rmSync(destino, { recursive: true, force: true }) })
const arquivo = (nome = "eventos.json") => path.join(destino, nome)
const ausencia = { disponivel: false, coletado_em: null, eventos: [], total: 0, fontes: [] }
const json = JSON.stringify({ coletado_em: "2026-11-12T10:00:00Z", eventos: [{
  id: "a".repeat(24), tipo: "sbce", data: "2026-11-15", titulo: "Consulta pública",
  fonte_id: "sbce", fonte_url: "https://www.gov.br/fazenda/consulta", coletado_em: "2026-11-12T10:00:00Z", confianca: 1,
}], fontes: [{ id: "sbce", coletado_em: "2026-11-12T10:00:00Z", situacao: "ok" }] })
const ics = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"

it("gera o recurso indisponível no primeiro build, sem data nem eventos inventados", async () => {
  expect(await baixarCalendario({ destino, pedir: async () => new Response("", { status: 404 }) })).toBe("ausente")
  expect(JSON.parse(fs.readFileSync(arquivo(), "utf8"))).toEqual(ausencia)
  expect(fs.readFileSync(arquivo("eventos.ics"), "utf8")).toContain("BEGIN:VCALENDAR")
  expect(fs.readFileSync(arquivo("eventos.ics"), "utf8")).not.toContain("BEGIN:VEVENT")
  // Serve os próprios arquivos gerados sob o caminho do Pages, sem fallback de SPA.
  const respostas: number[] = []
  const servidor = createServer((req, res) => {
    const nome = req.url === "/Raiz/calendario/eventos.json" ? "eventos.json" : req.url === "/Raiz/calendario/eventos.ics" ? "eventos.ics" : null
    res.statusCode = nome && fs.existsSync(arquivo(nome)) ? 200 : 404
    respostas.push(res.statusCode)
    res.setHeader("Content-Type", nome?.endsWith("json") ? "application/json" : "text/calendar")
    res.end(nome ? fs.readFileSync(arquivo(nome)) : "")
  })
  await new Promise<void>((r) => servidor.listen(0, "127.0.0.1", r))
  try {
    const endereco = servidor.address()
    if (!endereco || typeof endereco === "string") throw new Error("servidor indisponível")
    const fonte = fonteCalendario({ base: `http://127.0.0.1:${endereco.port}/Raiz/` })
    expect(await fonte.listar()).toEqual(ausencia)
    expect((await fetch(fonte.feed())).status).toBe(200)
    expect(respostas).toEqual([200, 200])
  } finally {
    await new Promise<void>((r, rejeitar) => servidor.close((erro) => erro ? rejeitar(erro) : r()))
  }
})

it("também materializa a ausência quando downloads foram desabilitados", async () => {
  const pedir = vi.fn()
  expect(await baixarCalendario({ destino, semDownload: true, pedir })).toBe("ausente")
  expect(pedir).not.toHaveBeenCalled()
  expect(lerAgenda(JSON.parse(fs.readFileSync(arquivo(), "utf8")))).toEqual(ausencia)
})

it("revalida a última coleta e preserva a data em falha HTTP ou de rede", async () => {
  fs.writeFileSync(arquivo(), json)
  fs.writeFileSync(arquivo("eventos.ics"), ics)
  for (const pedir of [
    async () => new Response("", { status: 503 }),
    async () => { throw new Error("rede indisponível") },
  ]) {
    expect(await baixarCalendario({ destino, pedir })).toBe("preservado")
    expect(JSON.parse(fs.readFileSync(arquivo(), "utf8")).coletado_em).toBe("2026-11-12T10:00:00+00:00")
    expect(fs.readFileSync(arquivo("eventos.ics"), "utf8")).toContain("BEGIN:VEVENT")
  }
})

it("substitui a ausência pela coleta quando o Release fica disponível", async () => {
  await baixarCalendario({ destino, semDownload: true })
  expect(await baixarCalendario({ destino, pedir: async (url: string) => new Response(url.endsWith(".json") ? json : ics) })).toBe("atualizado")
  const agenda = lerAgenda(JSON.parse(fs.readFileSync(arquivo(), "utf8")))
  expect(agenda.disponivel).toBe(true)
  expect(agenda.coletado_em).toBe("2026-11-12T10:00:00+00:00")
  expect(agenda.eventos).toHaveLength(1)
})

it("snapshot local explícito continua falhando quando não existe", async () => {
  await expect(baixarCalendario({ destino, local: path.join(destino, "inexistente") })).rejects.toThrow()
  expect(fs.existsSync(arquivo())).toBe(false)
})


it("bloqueia conteúdo inválido recebido com HTTP 200 mesmo com cache", async () => {
  fs.writeFileSync(arquivo(), json)
  await expect(baixarCalendario({ destino, pedir: async () => new Response("formato inválido") })).rejects.toThrow("não passou na validação")
  expect(fs.readFileSync(arquivo(), "utf8")).toBe(json)
})
