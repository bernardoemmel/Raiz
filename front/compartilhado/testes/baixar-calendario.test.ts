import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { baixarCalendario } from "../../scripts/baixar-calendario.mjs"
import { fonteCalendario, lerAgenda } from "../calendario"

let destino: string
beforeEach(() => { destino = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-calendario-")) })
afterEach(() => { fs.rmSync(destino, { recursive: true, force: true }) })
const arquivo = (nome = "eventos.json") => path.join(destino, nome)
const ausencia = { disponivel: false, coletado_em: null, eventos: [], total: 0, fontes: [] }
const json = JSON.stringify({ coletado_em: "2026-11-12T10:00:00Z", eventos: [{ id: "coleta-real", tipo: "sbce", data: "2026-11-15", titulo: "Consulta pública" }], fontes: [] })
const ics = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"

it("gera o recurso indisponível no primeiro build, sem data nem eventos inventados", async () => {
  expect(await baixarCalendario({ destino, pedir: async () => new Response("", { status: 404 }) })).toBe("ausente")
  expect(JSON.parse(fs.readFileSync(arquivo(), "utf8"))).toEqual(ausencia)
  expect(fs.readFileSync(arquivo("eventos.ics"), "utf8")).toContain("BEGIN:VCALENDAR")
  expect(fs.readFileSync(arquivo("eventos.ics"), "utf8")).not.toContain("BEGIN:VEVENT")
  // O mesmo recurso gerado é lido com HTTP 200; não se mascara um 404 no consumidor.
  const pedir = vi.fn(async (_url: string) => new Response(fs.readFileSync(arquivo()), { headers: { "content-type": "application/json" } }))
  const fonte = fonteCalendario({ base: "/Raiz/" }, pedir)
  expect(await fonte.listar()).toEqual(ausencia)
  expect(pedir.mock.calls[0][0]).toBe("/Raiz/calendario/eventos.json")
})

it("também materializa a ausência quando downloads foram desabilitados", async () => {
  const pedir = vi.fn()
  expect(await baixarCalendario({ destino, semDownload: true, pedir })).toBe("ausente")
  expect(pedir).not.toHaveBeenCalled()
  expect(lerAgenda(JSON.parse(fs.readFileSync(arquivo(), "utf8")))).toEqual(ausencia)
})

it("preserva os bytes e a data da última coleta em falha HTTP, rede ou formato", async () => {
  fs.writeFileSync(arquivo(), json)
  fs.writeFileSync(arquivo("eventos.ics"), ics)
  for (const pedir of [
    async () => new Response("", { status: 503 }),
    async () => { throw new Error("rede indisponível") },
    async () => new Response("formato inválido"),
  ]) {
    expect(await baixarCalendario({ destino, pedir })).toBe("preservado")
    expect(fs.readFileSync(arquivo(), "utf8")).toBe(json)
    expect(fs.readFileSync(arquivo("eventos.ics"), "utf8")).toBe(ics)
  }
})

it("substitui a ausência pela coleta quando o Release fica disponível", async () => {
  await baixarCalendario({ destino, semDownload: true })
  expect(await baixarCalendario({ destino, pedir: async (url: string) => new Response(url.endsWith(".json") ? json : ics) })).toBe("atualizado")
  const agenda = lerAgenda(JSON.parse(fs.readFileSync(arquivo(), "utf8")))
  expect(agenda.disponivel).toBe(true)
  expect(agenda.coletado_em).toBe("2026-11-12T10:00:00Z")
  expect(agenda.eventos).toHaveLength(1)
})

it("snapshot local explícito continua falhando quando não existe", async () => {
  await expect(baixarCalendario({ destino, local: path.join(destino, "inexistente") })).rejects.toThrow()
  expect(fs.existsSync(arquivo())).toBe(false)
})
