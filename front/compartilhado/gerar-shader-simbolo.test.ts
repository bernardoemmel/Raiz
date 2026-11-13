import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import { arquivoShaderSimbolo, gerarShaderSimbolo } from "./gerar-shader-simbolo"

const pacote = new URL("../globo/node_modules/maplibre-gl/", import.meta.url)
const original = readFileSync(new URL("dist/maplibre-gl.mjs", pacote), "utf8")
const { version } = JSON.parse(readFileSync(new URL("package.json", pacote), "utf8"))

describe("shader nacional gerado do fornecedor conferido", () => {
  it("mantém o arquivo do worker idêntico à geração a partir do MapLibre travado", () => {
    expect(readFileSync(new URL("../globo/src/mapa/shader-simbolo.generated.ts", import.meta.url), "utf8"))
      .toBe(arquivoShaderSimbolo(original, version))
  })
  it("recusa versão e bytes não revisados antes de executar o preparador de GLSL", () => {
    expect(() => gerarShaderSimbolo(original, "6.16.0")).toThrow(/revise/)
    expect(() => gerarShaderSimbolo(`${original}\n`, version)).toThrow(/revise/)
    expect(() => gerarShaderSimbolo("throw new Error('não executar')", version)).toThrow(/revise/)
  })
  it("reproduz os bytes observados no programa nacional real, incluindo defines e projeção", () => {
    const shader = gerarShaderSimbolo(original, version)
    const hash = (s: string) => createHash("sha256").update(s).digest("hex")
    expect(hash(shader.fragmento)).toBe("3cc8044beb3c42bdac74105917f0125ed32a9e3773c12be108fd8236f04af4bf")
    expect(hash(shader.vertice)).toBe("6f6019ae07a2e2c610c7f80ad95bd2a1dd8e8f4abb3db1c3845484e19039c283")
    const licenca = readFileSync(new URL("LICENSE.txt", pacote), "utf8")
    expect(licenca).toContain("Redistribution and use in source and binary forms")
    expect(readFileSync(new URL("../terceiros/maplibre-gl.LICENSE.txt", import.meta.url), "utf8")).toBe(licenca)
  })
})
