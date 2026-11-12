import fs from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { baixarLotes } from "../../scripts/baixar-lotes.mjs"

let destino
beforeEach(async () => { destino = await fs.mkdtemp(path.join(os.tmpdir(), "raiz-lotes-")) })
afterEach(async () => { vi.restoreAllMocks(); await fs.rm(destino, { recursive: true, force: true }) })
const arquivo = () => path.join(destino, "lote_PA_central_r11.json")
const agora = () => new Date("2026-11-12T20:00:00Z")

const marcador = () => ({ situacao: "ausente", acesso: "privado", motivo: "api_autenticada", verificado_em: agora().toISOString() })

it("substitui snapshot financeiro legado por marcador de acesso privado", async () => {
  await fs.writeFile(arquivo(), JSON.stringify({ resumos: { credito_p50: 1000000, tir: 11, valor_rs: 50000 } }))
  expect(await baixarLotes({ destino, agora })).toBe("ausente")
  expect(JSON.parse(await fs.readFile(arquivo(), "utf8"))).toEqual(marcador())
  expect(await fs.readdir(destino)).toEqual(["lote_PA_central_r11.json"])
})

it("ignora origem e payload financeiro de chamadores antigos sem nenhuma chamada de rede", async () => {
  const rede = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("rede proibida"))
  const pedir = vi.fn(async () => new Response(JSON.stringify({ uf: "PA", cenario: "central_r11", opcoes: ["barata", "segura", "compacta"], resumos: { credito_p50: 1000000 }, arquivos: { privado: { url: "https://exemplo.invalid/individual.tar.gz" } } })))
  expect(await baixarLotes({ destino, agora, origem: "https://exemplo.invalid", pedir })).toBe("ausente")
  expect(rede).not.toHaveBeenCalled()
  expect(pedir).not.toHaveBeenCalled()
  expect(JSON.parse(await fs.readFile(arquivo(), "utf8"))).toEqual(marcador())
})

it("funciona sem rede mesmo com cópia anterior inválida", async () => {
  const pedir = vi.fn(async () => { throw new Error("sem rede") })
  await fs.writeFile(arquivo(), "snapshot antigo inválido")
  expect(await baixarLotes({ destino, agora, pedir })).toBe("ausente")
  expect(pedir).not.toHaveBeenCalled()
  expect(JSON.parse(await fs.readFile(arquivo(), "utf8"))).toEqual(marcador())
})
