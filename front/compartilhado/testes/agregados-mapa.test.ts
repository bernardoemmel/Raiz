import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { gzipSync, gunzipSync } from "node:zlib"
import { afterEach, describe, expect, it, vi } from "vitest"
import { lerAgregadosMapa } from "../dados/agregados"
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

  it("o build anuncia só o nacional sanitizado e o loader o busca uma única vez, sem geometria estadual", async () => {
    const geo = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-agregados-publicos-"))
    try {
      fs.writeFileSync(path.join(geo, "potencial_indice.json"), JSON.stringify({ potencial: {
        PA: { arquivo: "potencial_PA.geojson.gz" }, TO: { arquivo: "potencial_TO.geojson.gz" },
      } }))
      for (const uf of ["PA", "TO"]) fs.writeFileSync(path.join(geo, `potencial_${uf}.geojson.gz`), gzipSync(JSON.stringify(colecao(celula(a, 5, 10)))))
      const p = potencialPublicado(geo), nome = p.agregados!.arquivo
      const publicado = JSON.parse(gunzipSync(p.arquivos[nome]).toString())
      expect(p.agregados).toEqual({ arquivo: "agregados_brasil.geojson.gz", bytes: p.arquivos[nome].length })
      expect(p.agregados!.bytes).toBeLessThanOrEqual(560_000)
      expect(publicado.features).toHaveLength(1)
      const pedidos: string[] = []
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        pedidos.push(url)
        if (url === "/Raiz/geo/indice.json") return Response.json({ municipios: {}, agregados: p.agregados })
        if (url === `/Raiz/geo/${nome}`) return new Response(p.arquivos[nome], { headers: { "content-type": "application/gzip" } })
        throw new Error("Arquivo fora do contrato nacional")
      }))
      const fonte = fonteAmostra("/Raiz/")
      const [um, dois] = await Promise.all([fonte.geo.agregados!(), fonte.geo.agregados!()])
      expect(um).toEqual(dois)
      expect(um?.metadados.contagens.fazendas_no_agregado).toBe(5)
      expect(pedidos).toEqual(["/Raiz/geo/indice.json", `/Raiz/geo/${nome}`])
    } finally { fs.rmSync(geo, { recursive: true, force: true }) }
  })

  it("sem agregado anunciado, retorna ausência sem provocar 404", async () => {
    const fetch = vi.fn(async () => Response.json({ municipios: {} }))
    vi.stubGlobal("fetch", fetch)
    expect(await fonteAmostra("/Raiz/").geo.agregados!()).toBeNull()
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch).toHaveBeenCalledWith("/Raiz/geo/indice.json")
  })
})
