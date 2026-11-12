import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { describe, expect, it } from "vitest"
import { COR } from "../cores"
// @ts-expect-error: script em JavaScript puro, sem tipos
import { verificar } from "../../scripts/verificar-design.mjs"

type Problema = { arquivo: string; linha: number; regra: string; trecho: string }

describe("verificador de design (guia, item 1.4)", () => {
  it("o front inteiro passa", () => {
    const problemas = verificar() as Problema[]
    expect(problemas.map((p) => `${p.arquivo}:${p.linha} ${p.regra}`)).toEqual([])
  })

  it("pega cada coisa proibida", () => {
    const raiz = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-design-"))
    const escrever = (rel: string, texto: string) => {
      fs.mkdirSync(path.dirname(path.join(raiz, rel)), { recursive: true })
      fs.writeFileSync(path.join(raiz, rel), texto)
    }
    escrever(
      "globo/src/ruim.css",
      [
        ".a { box-shadow: 0 1px 2px var(--tinta); }",
        ".b { border-left: 4px solid var(--mata); }",
        ".c { background: linear-gradient(var(--papel), var(--nevoa)); }",
        ".d { text-transform: uppercase; }",
        ".e { color: #ff00aa; }",
        ".f { font-family: Inter, sans-serif; }",
        ".g { color: white; }",
        "/* comentário com — não conta */",
        ".ok { background: repeating-linear-gradient(135deg, var(--mata) 0 2px, transparent 2px 6px); box-shadow: none; }",
      ].join("\n"),
    )
    escrever(
      "produtor/src/Ruim.tsx",
      [
        'const a = "Pronto 🎉"',
        'const b = "isto — aquilo"',
        "const c = <a>Abrir ficha →</a>",
        'const d = "4.180 ha · 56 módulos"',
        'const e = { color: "#123456" }',
        "// comentário com — e → não conta",
        "const f = /\"/g",
        'const ok = "© OpenStreetMap"',
      ].join("\n"),
    )
    const regras = (verificar(raiz) as Problema[]).map((p) => `${p.arquivo}:${p.linha} ${p.regra}`)
    expect(regras).toEqual(
      expect.arrayContaining([
        "globo/src/ruim.css:1 box-shadow diferente de none",
        "globo/src/ruim.css:2 borda esquerda colorida",
        "globo/src/ruim.css:3 degradê de enfeite",
        "globo/src/ruim.css:4 text-transform: uppercase",
        "globo/src/ruim.css:5 cor fora das variáveis",
        "globo/src/ruim.css:6 fonte Inter",
        "globo/src/ruim.css:7 cor fora das variáveis",
        "produtor/src/Ruim.tsx:1 emoji em texto da interface",
        "produtor/src/Ruim.tsx:2 travessão em texto da interface",
        "produtor/src/Ruim.tsx:3 seta em texto da interface",
        'produtor/src/Ruim.tsx:4 "A · B" com ponto médio',
        "produtor/src/Ruim.tsx:5 cor fora das variáveis",
      ]),
    )
    expect(regras.filter((r) => r.includes(":8") || r.includes(":9") || r.includes(":6 ") && r.includes("Ruim"))).toEqual([])
    fs.rmSync(raiz, { recursive: true })
  })
})

describe("cores", () => {
  it("cores.ts espelha as variáveis de base.css", () => {
    const css = fs.readFileSync(path.resolve(__dirname, "../base.css"), "utf8")
    const vars = Object.fromEntries([...css.matchAll(/--([a-z-]+):\s*(#[0-9A-Fa-f]{6})/g)].map((m) => [m[1], m[2].toUpperCase()]))
    const camel = (s: string) => s.replace(/-([a-z])/g, (_, l: string) => l.toUpperCase())
    const espelho = Object.fromEntries(Object.entries(vars).map(([k, v]) => [camel(k), v]))
    expect(Object.fromEntries(Object.entries(COR).map(([k, v]) => [k, v.toUpperCase()]))).toEqual(espelho)
  })
})
