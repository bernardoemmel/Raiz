import { createHash } from "node:crypto"
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { afterEach, describe, expect, it } from "vitest"
import { extrairProgramasNacionais } from "../vite-maplibre-programas"

const temporarios: string[] = []
const pacote = fileURLToPath(new URL("../../globo/node_modules/maplibre-gl", import.meta.url))
afterEach(() => { for (const pasta of temporarios.splice(0)) rmSync(pasta, { recursive: true, force: true }) })
function copiaPacote() {
  const pasta = mkdtempSync(join(tmpdir(), "raiz-shaders-")); temporarios.push(pasta)
  cpSync(join(pacote, "src/shaders"), join(pasta, "src/shaders"), { recursive: true })
  cpSync(join(pacote, "src/webgl"), join(pasta, "src/webgl"), { recursive: true })
  cpSync(join(pacote, "package.json"), join(pasta, "package.json"))
  return pasta
}

describe("programas exatos da primeira vista nacional V2", () => {
  it("preserva os bytes dos quatro programas capturados no MapLibre 6.15", () => {
    // Hashes capturados do WebGL nativo na abertura real (projeção Mercator, H3 V2).
    // Não são snapshots do extrator: garantem também ordem de defines e expansão de pragmas.
    const esperados = [
      ["clippingMask", "b2d71c50f0343d8b4ca8c16800699ccf791c056b186b416ee5e8cc02cba97aa8", "2962bd3e6c419f253ba7edc873d9eb2dd71283495b99b403594bb737fd134db3"],
      ["fill", "72bae28fbed599ce2a5953c252107f2cd609086405521fd8174c71e0bec73f7b", "f64eac851563728a1ab0ea5a3accf5b2fbc881961d7588ced59ba646616bb645"],
      ["line", "c2e1b1d5233697db3d4449cbb45adac7b9f6956dacc70393512b318b1ee40e10", "9407ef43a1d35a09b9ea879d36fe189008500a7b3772c1c7fc45f5f4d32ceb34"],
      ["symbolSDF", "d7b693205a26fb5c260d2b068e5d4e6dbd34f6c7b28c993746379169b7485850", "c449e338d07d12ef2698cee01ab0cf94cfd89dbf16a74ea9844734e1b1e5afea"],
    ]
    const hash = (fonte: string) => createHash("sha256").update(fonte).digest("hex")
    const programas = extrairProgramasNacionais()
    expect(programas.slice(0, 4).map(p => [p.nome, hash(p.vertice), hash(p.fragmento)])).toEqual(esperados)
    expect(new Set(programas.map(p => p.nome))).toEqual(new Set(["clippingMask", "fill", "line", "symbolSDF"]))
  })
  it("recusa upgrade mesmo quando as fontes permanecem iguais", () => {
    const pasta = copiaPacote(), arquivo = join(pasta, "package.json")
    const dados = JSON.parse(readFileSync(arquivo, "utf8")); dados.version = "6.16.0"
    writeFileSync(arquivo, JSON.stringify(dados))
    expect(() => extrairProgramasNacionais(pasta)).toThrow("revise os programas nacionais")
  })
  it("recusa alteração no compilador GLSL ou num shader sob a mesma versão", () => {
    const pasta = copiaPacote(), arquivo = join(pasta, "src/shaders/glsl/fill.vertex.glsl.g.ts")
    writeFileSync(arquivo, readFileSync(arquivo, "utf8") + "\n// alteração\n")
    expect(() => extrairProgramasNacionais(pasta)).toThrow("revise os programas nacionais")
  })
})
