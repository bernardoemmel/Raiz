import { afterEach, describe, expect, it, vi } from "vitest"
import { FonteGeojsonBlob } from "./fonte-geojson-blob"

afterEach(() => { vi.restoreAllMocks() })

describe("transporte GeoJSON sem serializar polígonos na interface", () => {
  it("fornece URL ao mapa e mantém os bytes legíveis até a conclusão do worker", async () => {
    const dados = new Blob(['{"type":"FeatureCollection","features":[]}'], { type: "application/geo+json" })
    const revogar = vi.spyOn(URL, "revokeObjectURL")
    const fonte = new FonteGeojsonBlob()
    let concluir!: () => void
    let url = ""
    const aplicacao = fonte.aplicar({ setData: endereco => {
      url = endereco
      return new Promise<void>(resolve => { concluir = resolve })
    } }, dados)
    expect(url).toMatch(/^blob:/)
    expect(await (await fetch(url)).text()).toBe(await dados.text())
    expect(revogar).not.toHaveBeenCalled()
    concluir()
    await aplicacao
    expect(revogar).toHaveBeenCalledExactlyOnceWith(url)
  })

  it("libera URLs pendentes na desmontagem sem revogar a próxima geração", async () => {
    const revogar = vi.spyOn(URL, "revokeObjectURL")
    const fonte = new FonteGeojsonBlob()
    const pendentes: { url: string; concluir: () => void }[] = []
    const destino = { setData: (url: string) => new Promise<void>(concluir => { pendentes.push({ url, concluir }) }) }
    const anterior = fonte.aplicar(destino, new Blob(["{} "]))
    fonte.encerrar()
    expect(revogar).toHaveBeenCalledExactlyOnceWith(pendentes[0].url)
    const seguinte = fonte.aplicar(destino, new Blob(["{} "]))
    pendentes[0].concluir()
    await anterior
    expect(revogar).toHaveBeenCalledTimes(1)
    expect(await (await fetch(pendentes[1].url)).text()).toBe("{} ")
    pendentes[1].concluir()
    await seguinte
    expect(revogar).toHaveBeenCalledTimes(2)
  })

  it("libera também quando o mapa recusa os dados", async () => {
    const revogar = vi.spyOn(URL, "revokeObjectURL")
    const fonte = new FonteGeojsonBlob()
    await expect(fonte.aplicar({ setData: async () => { throw new Error("fonte removida") } }, new Blob(["{} "])))
      .rejects.toThrow("fonte removida")
    expect(revogar).toHaveBeenCalledOnce()
    fonte.encerrar()
    expect(revogar).toHaveBeenCalledOnce()
  })
})
