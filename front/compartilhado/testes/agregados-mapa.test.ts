import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { gzipSync, gunzipSync } from "node:zlib"
import { createHash } from "node:crypto"
import { afterEach, describe, expect, it, vi } from "vitest"
import { lerAgregadosMapa, lerAgregadosMapaUrl, lerMetadadosAgregados, LIMITE_AGREGADOS_GZIP, LIMITE_AGREGADOS_NORMAL, LIMITE_AGREGADOS_TOTAL } from "../dados/agregados"
import { fonteAmostra } from "../dados/fonte-amostra"
import { potencialPublicado, projetarAgregados } from "../potencial-publico"

const celula = (h3: string, fazendas: number, potencial_ha: number | null) => ({ type: "Feature", properties: {
  h3, fazendas, potencial_ha, cod_imovel: "CAR-PRIVADO", nome_dono: "NOME-PRIVADO",
}, geometry: { type: "Polygon", coordinates: [[[1, 1], [2, 1], [1, 1]]] } })
const colecao = (...features: ReturnType<typeof celula>[]) => ({ type: "FeatureCollection", features, metadados: {
  contrato: "potencial_h3", versao: 1, resolucao: 5, metodo: "ponto_interior_estatistico", minimo_contribuintes: 5,
  cobertura: "parcial", atualizado_em: "2026-11-13T01:00:00Z", aviso: "TEXTO-PRIVADO",
} })
const a = "8581b16bfffffff", b = "8581b16ffffffff"

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe("pontos nacionais derivados somente do H3 público", () => {
  it("deduplica fronteiras, conserva valores conhecidos e não inventa zero para a célula sem medida", () => {
    const r = projetarAgregados([colecao(celula(a, 5, 10.5)), colecao(celula(a, 5, 10.5), celula(b, 7, null))])!
    expect(r.features).toHaveLength(2)
    expect(r.metadados.contagens).toEqual({ celulas: 2, celulas_sem_medida: 1, fazendas_no_agregado: 12 })
    expect(r.features.map(f => f.properties.potencial_ha)).toEqual([10.5, null])
    expect(r.features.every(f => f.geometry.type === "Point" && f.geometry.coordinates.length === 2)).toBe(true)
    expect(r.features[0].geometry.coordinates).not.toEqual([1, 1])
    expect(JSON.stringify(r)).not.toMatch(/PRIVAD|cod_imovel|nome_dono/)
    expect(lerAgregadosMapa(r)?.geo.features).toEqual(r.features)
  })

  it("recusa fronteira contraditória e mistura de retratos, em vez de escolher um valor silenciosamente", () => {
    expect(() => projetarAgregados([colecao(celula(a, 5, 10)), colecao(celula(a, 6, 10))])).toThrow("contraditória")
    expect(() => projetarAgregados([colecao(celula(a, 5, 10)), colecao(celula(a, 5, null))])).toThrow("contraditória")
    const outra = colecao(celula(b, 5, 10)); outra.metadados.atualizado_em = "2026-11-14T01:00:00Z"
    expect(() => projetarAgregados([colecao(celula(a, 5, 10)), outra])).toThrow("misturam execuções")
  })

  it("o parser público rejeita duplicatas, geometria individual e grupos pequenos", () => {
    const r = projetarAgregados([colecao(celula(a, 5, 10))])!
    expect(lerAgregadosMapa({ ...r, features: [...r.features, ...r.features] })).toBeNull()
    expect(lerAgregadosMapa({ ...r, features: [{ ...r.features[0], geometry: { type: "Polygon", coordinates: [] } }] })).toBeNull()
    expect(lerAgregadosMapa({ ...r, features: [{ ...r.features[0], properties: { ...r.features[0].properties, fazendas: 4 } }] })).toBeNull()
  })

  it("o build publica as duas representações sanitizadas e o loader deixa o corpo para o worker", async () => {
    const geo = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-agregados-publicos-"))
    try {
      fs.writeFileSync(path.join(geo, "potencial_indice.json"), JSON.stringify({ potencial: {
        PA: { arquivo: "potencial_PA.geojson.gz" }, TO: { arquivo: "potencial_TO.geojson.gz" },
      } }))
      for (const uf of ["PA", "TO"]) fs.writeFileSync(path.join(geo, `potencial_${uf}.geojson.gz`), gzipSync(JSON.stringify(colecao(celula(a, 5, 10)))))
      const p = potencialPublicado(geo), nome = p.agregados!.arquivo
      const publicado = JSON.parse(gunzipSync(p.arquivos[nome]).toString())
      const normal = p.arquivos[p.agregados!.normal.arquivo]
      expect(gunzipSync(p.arquivos[nome]).equals(normal)).toBe(true)
      expect(p.agregados!.metadados).toEqual(publicado.metadados)
      expect(p.agregados!.normal.arquivo).toBe("agregados_brasil.geojson")
      expect(p.agregados!.normal.bytes).toBe(normal.length)
      expect(p.agregados!.bytes).toBe(p.arquivos[nome].length)
      expect(p.agregados!.bytes_total).toBe(normal.length + p.arquivos[nome].length)
      expect(p.agregados!.sha256).toBe(createHash("sha256").update(p.arquivos[nome]).digest("hex"))
      expect(p.agregados!.normal.sha256).toBe(createHash("sha256").update(normal).digest("hex"))
      expect(p.agregados!.bytes).toBeLessThanOrEqual(LIMITE_AGREGADOS_GZIP)
      expect(normal.length).toBeLessThanOrEqual(LIMITE_AGREGADOS_NORMAL)
      expect(p.agregados!.bytes_total).toBeLessThanOrEqual(LIMITE_AGREGADOS_TOTAL)
      expect(publicado.features).toHaveLength(1)
      const pedidos: string[] = []
      vi.stubGlobal("location", { origin: "https://raiz.exemplo" })
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        pedidos.push(url)
        if (url === "/Raiz/geo/indice.json") return Response.json({ municipios: {}, agregados: p.agregados })
        throw new Error("A thread principal não deve baixar as feições")
      }))
      const fonte = fonteAmostra("/Raiz/")
      const [um, dois] = await Promise.all([fonte.geo.agregados!(), fonte.geo.agregados!()])
      expect(um).toEqual(dois)
      expect(um?.url).toBe("https://raiz.exemplo/Raiz/geo/agregados_brasil.geojson")
      expect(um?.geo).toBeUndefined()
      expect(um?.metadados.contagens.fazendas_no_agregado).toBe(5)
      expect(pedidos).toEqual(["/Raiz/geo/indice.json"])
    } finally { fs.rmSync(geo, { recursive: true, force: true }) }
  })

  it("mantém o gzip validado para índices antigos ou sem metadados normais válidos", async () => {
    const publicado = projetarAgregados([colecao(celula(a, 5, 10))])!
    const bytes = gzipSync(JSON.stringify(publicado)), pedidos: string[] = []
    vi.stubGlobal("location", { origin: "https://raiz.exemplo" })
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      pedidos.push(url)
      if (url === "/geo/indice.json") return Response.json({ municipios: {}, agregados: {
        arquivo: "agregados_brasil.geojson.gz", bytes: bytes.length,
        normal: { arquivo: "https://privado.exemplo/lotes.geojson", bytes: 100, sha256: "a".repeat(64) },
      } })
      if (url === "/geo/agregados_brasil.geojson.gz") return new Response(bytes, { headers: { "content-type": "application/gzip" } })
      throw new Error("Caminho privado não pode ser lido")
    }))
    const fonte = fonteAmostra("/")
    const [um, dois] = await Promise.all([fonte.geo.agregados!(), fonte.geo.agregados!()])
    expect(um).toEqual(dois)
    expect(um?.url).toBeUndefined()
    expect(um?.geo?.features).toEqual(publicado.features)
    expect(pedidos).toEqual(["/geo/indice.json", "/geo/agregados_brasil.geojson.gz"])
  })

  it("limita a URL a um arquivo público da mesma origem, na raiz ou base configurada", () => {
    const metadados = projetarAgregados([colecao(celula(a, 5, 10))])!.metadados
    const item = { arquivo: "agregados_brasil.geojson.gz", bytes: 100, sha256: "a".repeat(64), bytes_total: 400,
      normal: { arquivo: "agregados_brasil.geojson", bytes: 300, sha256: "b".repeat(64) }, metadados }
    for (const base of ["/", "/Raiz/", "/outra-base", "https://raiz.exemplo/Raiz/"]) {
      const r = lerAgregadosMapaUrl(item, base, "https://raiz.exemplo")!
      expect(r.url).toBe(new URL("geo/agregados_brasil.geojson", new URL(base.endsWith("/") ? base : base + "/", "https://raiz.exemplo")).href)
    }
    expect(lerAgregadosMapaUrl(item, "./", "https://raiz.exemplo", "https://raiz.exemplo/Raiz/index.html")?.url).toBe("https://raiz.exemplo/Raiz/geo/agregados_brasil.geojson")
    expect(lerAgregadosMapaUrl(item, "../", "https://raiz.exemplo", "https://raiz.exemplo/Raiz/telas/index.html")?.url).toBe("https://raiz.exemplo/Raiz/geo/agregados_brasil.geojson")
    for (const arquivo of ["../privado/lote.geojson", "https://privado.exemplo/lote.geojson", "//privado.exemplo/lote.geojson", "agregados_brasil.geojson?token=x", "agregados_brasil.geojson#x", "agregados_brasil.geojson\n"]) {
      expect(lerAgregadosMapaUrl({ ...item, normal: { ...item.normal, arquivo } }, "/", "https://raiz.exemplo")).toBeNull()
    }
    for (const base of ["https://privado.exemplo/", "//privado.exemplo/", "/Raiz/?token=x", "/Raiz/#x", "https://usuario:senha@raiz.exemplo/"]) {
      expect(lerAgregadosMapaUrl(item, base, "https://raiz.exemplo")).toBeNull()
    }
    expect(lerAgregadosMapaUrl({ ...item, bytes_total: 399 }, "/", "https://raiz.exemplo")).toBeNull()
    expect(lerAgregadosMapaUrl({ ...item, bytes: LIMITE_AGREGADOS_GZIP + 1 }, "/", "https://raiz.exemplo")).toBeNull()
    expect(lerAgregadosMapaUrl({ ...item, normal: { ...item.normal, bytes: LIMITE_AGREGADOS_NORMAL + 1 } }, "/", "https://raiz.exemplo")).toBeNull()
    expect(lerAgregadosMapaUrl({ ...item, normal: { ...item.normal, sha256: "não é um hash" } }, "/", "https://raiz.exemplo")).toBeNull()
    expect(lerAgregadosMapaUrl({ ...item, normal: { ...item.normal, sha256: "b".repeat(64) + "\n" } }, "/", "https://raiz.exemplo")).toBeNull()
    expect(lerAgregadosMapaUrl({ ...item, metadados: { ...metadados, minimo_contribuintes: 4 } }, "/", "https://raiz.exemplo")).toBeNull()
  })

  it("projeta metadados do índice sem textos ou contagens particulares e recusa totais contraditórios", () => {
    const m = projetarAgregados([colecao(celula(a, 5, 10))])!.metadados
    const r = lerMetadadosAgregados({ ...m, aviso: "TEXTO-PRIVADO", fonte: "URL-PRIVADA", cod_imovel: "CAR-PRIVADO",
      contagens: { ...m.contagens, car: "CAR-PRIVADO" } })
    expect(JSON.stringify(r)).not.toMatch(/PRIVAD|cod_imovel/)
    expect(lerMetadadosAgregados({ ...m, contagens: { ...m.contagens, fazendas_no_agregado: 4 } })).toBeNull()
    expect(lerMetadadosAgregados({ ...m, contagens: { ...m.contagens, celulas_sem_medida: 2 } })).toBeNull()
    expect(lerMetadadosAgregados({ ...m, contagens: { ...m.contagens, celulas: Number.NaN } })).toBeNull()
  })

  it("sem agregado anunciado, retorna ausência sem provocar 404", async () => {
    const fetch = vi.fn(async () => Response.json({ municipios: {} }))
    vi.stubGlobal("fetch", fetch)
    expect(await fonteAmostra("/Raiz/").geo.agregados!()).toBeNull()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith("/Raiz/geo/indice.json")
  })
})
