import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { spawnSync } from "node:child_process"
import { test } from "node:test"
import { fileURLToPath } from "node:url"
import { configurarPublicacao } from "./configurar-publicacao.mjs"

test("Pages deriva caminho e URL do repositório, inclusive se ele mudar de nome", () => {
  assert.deepEqual(configurarPublicacao({ GITHUB_REPOSITORY: "Conta/OutroProjeto" }), {
    base: "/OutroProjeto/", siteUrl: "https://conta.github.io/OutroProjeto/", dominio: "",
  })
})
test("site da conta usa a raiz", () => {
  assert.equal(configurarPublicacao({ GITHUB_REPOSITORY: "Conta/conta.github.io" }).base, "/")
})
test("build local sem configuração usa a raiz", () => {
  assert.deepEqual(configurarPublicacao({}), { base: "/", siteUrl: "http://localhost/", dominio: "" })
})
test("domínio próprio troca base e URL, mesmo no Pages de projeto", () => {
  assert.deepEqual(configurarPublicacao({ GITHUB_REPOSITORY: "Conta/Projeto", RAIZ_DOMINIO: " MAPA.Example " }), {
    base: "/", siteUrl: "https://mapa.example/", dominio: "mapa.example",
  })
})
test("nomes internacionais são normalizados para CNAME", () => {
  assert.equal(configurarPublicacao({ RAIZ_DOMINIO: "raízes.example" }).dominio, "xn--razes-0sa.example")
})
test("outro subcaminho pode ser testado sem domínio", () => {
  assert.deepEqual(configurarPublicacao({ RAIZ_BASE: "/outro", RAIZ_SITE_URL: "https://site.example/outro" }), {
    base: "/outro/", siteUrl: "https://site.example/outro/", dominio: "",
  })
})
test("CNAME recusa protocolo, caminho, porta, credenciais, IP e nomes inválidos", () => {
  for (const RAIZ_DOMINIO of ["https://mapa.example", "mapa.example/caminho", "mapa.example:443", "usuario@mapa.example",
    "127.0.0.1", "localhost", "-mapa.example", "mapa..example", "mapa.example.", "mapa.example?x=1", "mapa.example#x",
    "mapa.example\nOUTRA=variavel", "a".repeat(64) + ".example"]) {
    assert.throws(() => configurarPublicacao({ RAIZ_DOMINIO }), /RAIZ_DOMINIO/, RAIZ_DOMINIO)
  }
})
test("domínio nunca publica em subcaminho nem anuncia outro host", () => {
  assert.throws(() => configurarPublicacao({ RAIZ_DOMINIO: "mapa.example", RAIZ_BASE: "/projeto/" }), /RAIZ_BASE/)
  for (const RAIZ_SITE_URL of ["https://outro.example/", "http://mapa.example/", "https://mapa.example/pasta/"])
    assert.throws(() => configurarPublicacao({ RAIZ_DOMINIO: "mapa.example", RAIZ_SITE_URL }), /RAIZ_SITE_URL/)
})
test("base e URL canônica não aceitam caminhos inconsistentes ou elementos injetados", () => {
  for (const RAIZ_BASE of ["//outro.example/", "relativo/", "/../", "/pasta/./", "/?x=1", "/#x", "/a\nb/"])
    assert.throws(() => configurarPublicacao({ RAIZ_BASE }), /RAIZ_BASE/)
  for (const RAIZ_SITE_URL of ["javascript:alert(1)", "https://user:senha@mapa.example/", "https://mapa.example/?q=1", "https://mapa.example/#x"])
    assert.throws(() => configurarPublicacao({ RAIZ_SITE_URL }), /RAIZ_SITE_URL/)
})
test("CLI escreve somente o hostname no CNAME e remove arquivo antigo sem domínio", () => {
  const pasta = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-dominio-"))
  try {
    const arquivo = path.join(pasta, "CNAME")
    const script = fileURLToPath(new URL("./configurar-publicacao.mjs", import.meta.url))
    const executar = (RAIZ_DOMINIO) => spawnSync(process.execPath, [script, "--cname", arquivo], {
      env: { RAIZ_DOMINIO }, encoding: "utf8",
    })
    const comDominio = executar("Mapa.Example")
    assert.equal(comDominio.status, 0, comDominio.stderr)
    assert.equal(fs.readFileSync(arquivo, "utf8"), "mapa.example\n")
    const semDominio = executar("")
    assert.equal(semDominio.status, 0, semDominio.stderr)
    assert.equal(fs.existsSync(arquivo), false)
  } finally {
    fs.rmSync(pasta, { recursive: true, force: true })
  }
})
