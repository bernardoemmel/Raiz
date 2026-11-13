import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { describe, expect, it } from "vitest"
// @ts-expect-error: script em JavaScript puro, sem tipos
import { verificar } from "../../scripts/verificar-design.mjs"

type Problema = { arquivo: string; linha: number; regra: string; trecho: string }

/** Uma exceção não pode desligar a regra no resto do arquivo. */
function conferir(arquivo: string, fonte: string): string[] {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-design-v2-"))
  try {
    const caminho = path.join(raiz, arquivo)
    fs.mkdirSync(path.dirname(caminho), { recursive: true })
    fs.writeFileSync(caminho, fonte)
    return (verificar(raiz) as Problema[]).map((p) => p.regra)
  } finally {
    fs.rmSync(raiz, { recursive: true })
  }
}

describe("escopos do visual v2", () => {
  it.each([
    ".rot { text-transform: uppercase; }",
    ".cartao .rot:hover { text-transform: uppercase; }",
    ".rot.ativo, .painel > span.rot { text-transform: uppercase; }",
    ".rot:not(.inativa) { text-transform: uppercase; }",
    "@media (max-width: 700px) { .rot { text-transform: uppercase; } }",
  ])("permite caixa alta no elemento .rot: %s", (css) => {
    expect(conferir("globo/src/rotulo.css", css)).toEqual([])
  })

  it.each([
    ".rotulo { text-transform: uppercase; }",
    ".rot + p { text-transform: uppercase; }",
    ".rot p { text-transform: uppercase; }",
    ".rot :not(p) { text-transform: uppercase; }",
    ".rot, p { text-transform: uppercase; }",
    ":is(.rot, p) { text-transform: uppercase; }",
    '.x[data-classe=".rot"] { text-transform: uppercase; }',
    ".rot { color: var(--tinta); } p { text-transform: uppercase; }",
  ])("não amplia a exceção de caixa alta: %s", (css) => {
    expect(conferir("globo/src/rotulo.css", css)).toContain("text-transform: uppercase")
  })

  it("preserva caixa normal no produtor", () => {
    expect(conferir("produtor/src/estilo.css", ".rot { text-transform: uppercase; }")).toEqual(["text-transform: uppercase"])
  })

  it.each([
    'const c = <span className="rot">Brasil · terra para restaurar</span>',
    'const c = <span className="rot extra">{pais} · {data}</span>',
    'const c = <span className={"rot"}>{"Brasil · terra"}</span>',
    'const c = <span className="rot"><b>Brasil</b> · {data}</span>',
    'const c = <span className="rot">{partes.join(" · ")}</span>',
    'const c = <RotuloMono partes={["Brasil", data]} />',
    'const c = <RotuloMono>{pais} · {data}</RotuloMono>',
  ])("aceita ponto médio apenas no rótulo mono: %s", (tsx) => {
    expect(conferir("globo/src/Rotulo.tsx", tsx)).toEqual([])
  })

  it.each([
    'const separador = " · "',
    'const c = <span className="rotulo">Brasil · terra</span>',
    'const c = <><span className="rot">Brasil · terra</span><p>Brasil · terra</p></>',
    'const c = <span className="rot">Brasil · terra</span>; const texto = "Brasil · terra"',
    'const c = <span className="rot" />; const texto = "Brasil · terra"',
    'const c = <><RotuloMono partes={[pais, data]} /><p>Brasil · terra</p></>',
    'const c = <p className={classe}>Brasil · terra</p>',
    `const c = '<span className="rot">Brasil · terra</span>'`,
  ])("rejeita ponto médio fora do elemento mono: %s", (tsx) => {
    expect(conferir("globo/src/Rotulo.tsx", tsx)).toContain('"A · B" com ponto médio')
  })

  it("não libera ponto médio, emoji ou travessão no produtor", () => {
    expect(conferir("produtor/src/Ficha.tsx", 'const c = <span className="rot">Brasil · terra — verde 🌳</span>')).toEqual(
      expect.arrayContaining(['"A · B" com ponto médio', "travessão em texto da interface", "emoji em texto da interface"]),
    )
  })

  it("o rótulo mono não libera outras proibições", () => {
    expect(conferir("globo/src/Rotulo.tsx", 'const c = <span className="rot">Brasil — terra 🌳</span>')).toEqual(
      expect.arrayContaining(["travessão em texto da interface", "emoji em texto da interface"]),
    )
    expect(conferir("globo/src/rotulo.css", '.rot::after { content: "Brasil · terra"; }')).toEqual([])
    expect(conferir("globo/src/rotulo.css", '.rot + p::after { content: "Brasil · terra"; }')).toContain('"A · B" com ponto médio')
  })

  it("limita a paleta do analista ao :root de raiz.css", () => {
    expect(conferir("globo/src/raiz.css", ":root { --chao: #0D1311; --vidro: #101714EB; }")).toEqual([])
    for (const [arquivo, css] of [
      ["globo/src/raiz.css", ":root { --chao: #0D1311; } .cartao { background: #101714EB; }"],
      ["globo/src/raiz.css", ".tema, :root { --chao: #0D1311; }"],
      ["globo/src/outro.css", ":root { --chao: #0D1311; }"],
      ["produtor/src/estilo.css", ":root { --chao: #0D1311; }"],
    ]) expect(conferir(arquivo, css)).toContain("cor fora das variáveis")
  })

  it("a paleta e .rot não abrem exceção para sombra e degradê", () => {
    const css = ":root { --chao: #0D1311; } .rot { box-shadow: 0 2px 3px var(--tinta); background: conic-gradient(var(--mata), var(--lima)); }"
    expect(conferir("globo/src/raiz.css", css)).toEqual(expect.arrayContaining(["box-shadow diferente de none", "degradê de enfeite"]))
  })

  it.each(["Familjen Grotesk", "Atkinson Hyperlegible Next"])("rejeita %s no analista e preserva no produtor", (fonte) => {
    const css = `.texto { font-family: "${fonte}", sans-serif; }`
    expect(conferir("globo/src/fontes.css", css)).toEqual(["fonte v1 no analista"])
    expect(conferir("produtor/src/fontes.css", css)).toEqual([])
    expect(conferir("compartilhado/base.css", css)).toEqual([])
    expect(conferir("globo/src/grafico.ts", `const estilo = { fontFamily: "${fonte}" }`)).toEqual(["fonte v1 no analista"])
  })

  it("verifica dependências antigas e aceita fontes V2", () => {
    expect(conferir("globo/package.json", '{"dependencies":{"@fontsource/atkinson-hyperlegible-next":"5"}}')).toEqual(["fonte v1 no analista"])
    expect(conferir("produtor/package.json", '{"dependencies":{"@fontsource/atkinson-hyperlegible-next":"5"}}')).toEqual([])
    expect(conferir("globo/src/fontes.css", '.texto { font-family: "Bricolage Grotesque", sans-serif; } .rot { font-family: "JetBrains Mono", monospace; }')).toEqual([])
  })

  it("autoriza apenas a cor correta da barra do navegador em cada aplicação", () => {
    expect(conferir("globo/index.html", '<meta name="theme-color" content="#0D1311">')).toEqual([])
    expect(conferir("produtor/index.html", '<meta name="theme-color" content="#1D6B44">')).toEqual([])
    expect(conferir("produtor/index.html", '<meta name="theme-color" content="#0D1311">')).toEqual(["cor fora das variáveis"])
  })
})
