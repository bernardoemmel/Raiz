import fs from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { baixarLotes } from "../../scripts/baixar-lotes.mjs"

let destino
beforeEach(async () => { destino = await fs.mkdtemp(path.join(os.tmpdir(), "raiz-lotes-")) })
afterEach(async () => { vi.restoreAllMocks(); await fs.rm(destino, { recursive: true, force: true }) })
const arquivo = () => path.join(destino, "lote_PA_central_r11.json")

it("preserva snapshot financeiro privado sem lê-lo nem publicá-lo", async () => {
  const snapshot = JSON.stringify({ resumos: { credito_p50: 1000000, tir: 11, valor_rs: 50000 } })
  await fs.writeFile(arquivo(), snapshot)
  const leitura = vi.spyOn(fs, "readFile")
  expect(await baixarLotes({ destino })).toBe("ausente")
  expect(leitura).not.toHaveBeenCalled()
  expect(await fs.readFile(arquivo(), "utf8")).toBe(snapshot)
  expect(await fs.readdir(destino)).toEqual(["lote_PA_central_r11.json"])
})

it("ignora origem e payload financeiro de chamadores antigos sem nenhuma chamada de rede", async () => {
  const rede = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("rede proibida"))
  const pedir = vi.fn(async () => new Response(JSON.stringify({ uf: "PA", cenario: "central_r11", opcoes: ["barata", "segura", "compacta"], resumos: { credito_p50: 1000000 }, arquivos: { privado: { url: "https://exemplo.invalid/individual.tar.gz" } } })))
  expect(await baixarLotes({ destino, origem: "https://exemplo.invalid", pedir })).toBe("ausente")
  expect(rede).not.toHaveBeenCalled()
  expect(pedir).not.toHaveBeenCalled()
  expect(await fs.readdir(destino)).toEqual([])
})

it("funciona sem rede mesmo com cópia anterior inválida", async () => {
  const pedir = vi.fn(async () => { throw new Error("sem rede") })
  await fs.writeFile(arquivo(), "snapshot antigo inválido")
  expect(await baixarLotes({ destino, pedir })).toBe("ausente")
  expect(pedir).not.toHaveBeenCalled()
  expect(await fs.readFile(arquivo(), "utf8")).toBe("snapshot antigo inválido")
})
