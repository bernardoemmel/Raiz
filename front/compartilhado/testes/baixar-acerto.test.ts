import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { afterEach, describe, expect, it, vi } from "vitest"
// @ts-expect-error: script de publicação em JavaScript
import { baixarAcerto } from "../../scripts/baixar-acerto.mjs"
import { ACERTO_AUSENTE } from "../acerto"
const pastas: string[] = []
const destino = () => { const p = fs.mkdtempSync(path.join(os.tmpdir(), "acerto-download-")); pastas.push(p); return path.join(p, "placar.json") }
afterEach(() => { for (const p of pastas.splice(0)) fs.rmSync(p, { recursive: true, force: true }); vi.unstubAllEnvs() })
describe("publicação do acerto", () => {
  it("sem origem remove a cópia antiga e não tenta uma URL inexistente", async () => {
    const d = destino(); fs.writeFileSync(d, "antigo")
    const pedir = vi.fn()
    await baixarAcerto({ destino: d, origem: "", pedir })
    expect(pedir).not.toHaveBeenCalled()
    expect(fs.existsSync(d)).toBe(false)
  })
  it("não usa token na URL nem origem sem HTTPS", async () => {
    for (const origem of ["http://api.example/acerto", "https://token@api.example/acerto"]) await expect(baixarAcerto({ destino: destino(), origem, pedir: vi.fn() })).rejects.toThrow(/HTTPS e pública/)
  })
  it("falha remota não sobrescreve a última cópia nem vira nota zero", async () => {
    const d = destino(); fs.writeFileSync(d, "anterior")
    await expect(baixarAcerto({ destino: d, origem: "https://api.example/acerto", pedir: async () => new Response("", { status: 503 }) })).rejects.toThrow(/atualizar/)
    expect(fs.readFileSync(d, "utf8")).toBe("anterior")
  })
  it("aceita só envelope público e deixa a projeção final para o build", async () => {
    const d = destino()
    const opcoes = { destino: d, origem: "https://api.example/acerto" }
    await expect(baixarAcerto({ ...opcoes, pedir: async () => new Response(JSON.stringify({ previsoes: [] })) })).rejects.toThrow(/resumo público/)
    await baixarAcerto({ ...opcoes, pedir: async () => new Response(JSON.stringify(ACERTO_AUSENTE)) })
    expect(JSON.parse(fs.readFileSync(d, "utf8"))).toEqual(ACERTO_AUSENTE)
  })
})
