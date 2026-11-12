import fs from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { afterEach, beforeEach, expect, it } from "vitest"
import { baixarLotes } from "../../scripts/baixar-lotes.mjs"

let destino
beforeEach(async () => { destino = await fs.mkdtemp(path.join(os.tmpdir(), "raiz-lotes-")) })
afterEach(async () => { await fs.rm(destino, { recursive: true, force: true }) })
const arquivo = () => path.join(destino, "lote_PA_central_r11.json")
const agora = () => new Date("2026-11-12T20:00:00Z")

it("ausência confirmada substitui snapshot antigo e não fabrica resultados", async () => {
  await fs.writeFile(arquivo(), JSON.stringify({ resumos: { antiga: {} } }))
  expect(await baixarLotes({ destino, agora, pedir: async () => new Response("", { status: 404 }) })).toBe("ausente")
  expect(JSON.parse(await fs.readFile(arquivo(), "utf8"))).toEqual({ situacao: "ausente", verificado_em: agora().toISOString() })
})

it("preserva data da publicação separada da conferência e não baixa pacotes individuais", async () => {
  const pedidos = []
  await baixarLotes({ destino, agora, pedir: async (url) => {
    pedidos.push(url)
    return new Response(JSON.stringify({ uf: "PA", cenario: "central_r11", opcoes: ["barata", "segura", "compacta"], resumos: {}, arquivos: { privado: { url: "https://exemplo.invalid/individual.tar.gz" } } }),
      { headers: { "last-modified": "Thu, 12 Nov 2026 19:00:00 GMT" } })
  } })
  const dado = JSON.parse(await fs.readFile(arquivo(), "utf8"))
  expect(dado.publicado_em).toBe("2026-11-12T19:00:00.000Z")
  expect(dado.verificado_em).toBe(agora().toISOString())
  expect(pedidos).toHaveLength(1)
  expect(pedidos[0]).toMatch(/\/lote_PA_central_r11\.json$/)
})

it("falha de rede e contrato quebrado interrompem a publicação sem apagar a cópia anterior", async () => {
  await fs.writeFile(arquivo(), "anterior")
  for (const resposta of [new Response("", { status: 503 }), new Response('{"uf":"PA"}')])
    await expect(baixarLotes({ destino, pedir: async () => resposta })).rejects.toThrow()
  expect(await fs.readFile(arquivo(), "utf8")).toBe("anterior")
})
