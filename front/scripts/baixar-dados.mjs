#!/usr/bin/env node
/**
 * Baixa sozinho os dados do motor publicados no Release `dados` do GitHub para dados/estados/<UF>/.
 * Roda antes do `npm run dev` (predev) e pode rodar no deploy. Só baixa o estado que mudou: compara a versão
 * de cada estado no estados.json publicado com a cópia local (dados/estados/estados.json).
 *
 * Uso (da pasta front/globo ou front/produtor, ou de qualquer lugar):
 *   node ../scripts/baixar-dados.mjs              # todos os estados publicados, só CSV
 *   node ../scripts/baixar-dados.mjs PA RO        # só alguns
 *   node ../scripts/baixar-dados.mjs --geo        # também os polígonos (geo_<cod>.parquet)
 *   node ../scripts/baixar-dados.mjs --geo --exigir # publicação: erro no download interrompe o build
 * Variáveis: RAIZ_DADOS (pasta de destino; padrão dados/estados na raiz do repositório),
 *            RAIZ_DADOS_URL (onde está o estados.json; padrão o Release `dados` do repositório),
 *            RAIZ_SEM_DOWNLOAD=1 (pula tudo, ex.: sem internet).
 * Sem internet ou com erro, avisa e segue: o front cai na amostra (dados/amostra).
 * Precisa só do Node 18+ e do `tar` (vem no Linux, no macOS e no Windows 10+). Sem dependências.
 */
import { execFileSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const RAIZ_REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const DESTINO = path.resolve(RAIZ_REPO, process.env.RAIZ_DADOS || "dados/estados")
const URL_BASE = process.env.RAIZ_DADOS_URL || "https://github.com/bernardoemmel/raiz/releases/download/dados"
const args = process.argv.slice(2)
const comGeo = args.includes("--geo")
const exigir = args.includes("--exigir")
const pedidos = args.filter((a) => /^[A-Z]{2}$/.test(a))

async function baixarJson(url) {
  const r = await fetch(url, { redirect: "follow" })
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`)
  return r.json()
}

async function baixarEExtrair(url, uf) {
  const r = await fetch(url, { redirect: "follow" })
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`)
  const tmp = path.join(os.tmpdir(), `raiz_${uf}_${process.pid}.tar.gz`)
  fs.writeFileSync(tmp, Buffer.from(await r.arrayBuffer()))
  try {
    fs.mkdirSync(DESTINO, { recursive: true })
    execFileSync("tar", ["-xzf", tmp, "-C", DESTINO], { stdio: "inherit" })
  } finally {
    fs.rmSync(tmp, { force: true })
  }
}

async function main() {
  if (process.env.RAIZ_SEM_DOWNLOAD === "1") return
  let remoto
  try {
    remoto = await baixarJson(`${URL_BASE}/estados.json`)
  } catch (e) {
    if (exigir) throw e
    console.warn(`[dados] não consegui ler o estados.json publicado (${e.message}); sigo com o que já tenho.`)
    return
  }
  const arqLocal = path.join(DESTINO, "estados.json")
  let local = { estados: {} }
  try {
    local = JSON.parse(fs.readFileSync(arqLocal, "utf8"))
  } catch {}

  const ufs = Object.keys(remoto.estados).filter((uf) => !pedidos.length || pedidos.includes(uf))
  const falhas = []
  for (const uf of ufs) {
    const r = remoto.estados[uf]
    const l = local.estados[uf] || {}
    const rotulo = `${uf} (${r.municipios}/${r.total_ibge ?? "?"} municípios${r.completo ? "" : ", incompleto"})`
    // O executor anuncia estados em andamento antes de criar o primeiro pacote. Não pedir um arquivo inexistente.
    if (!r.municipios && !r.tamanho) {
      local.estados[uf] = r
      continue
    }
    try {
      if (l.versao !== r.versao || !fs.existsSync(path.join(DESTINO, uf))) {
        console.log(`[dados] baixando ${rotulo}, ${((r.tamanho || 0) / 1e6).toFixed(0)} MB`)
        await baixarEExtrair(r.url, uf)
        l.versao = r.versao
      }
      if (comGeo && r.geo && l.geo?.versao !== r.geo.versao) {
        console.log(`[dados] baixando polígonos de ${uf}, ${(r.geo.tamanho / 1e6).toFixed(0)} MB`)
        await baixarEExtrair(r.geo.url, uf)
        l.geo = r.geo
      }
      local.estados[uf] = { ...r, versao: l.versao, geo: l.geo }
      fs.writeFileSync(arqLocal, JSON.stringify({ ...remoto, estados: local.estados }, null, 1))
    } catch (e) {
      falhas.push(uf)
      console.warn(`[dados] falhou ${uf}: ${e.message}`)
    }
  }
  fs.mkdirSync(DESTINO, { recursive: true })
  fs.writeFileSync(arqLocal, JSON.stringify({ ...remoto, estados: local.estados }, null, 1))
  if (exigir && falhas.length) throw new Error(`não consegui atualizar os estados: ${falhas.join(", ")}`)
  console.log(`[dados] pronto em ${path.relative(RAIZ_REPO, DESTINO) || DESTINO}: ${Object.keys(local.estados).join(", ")}`)
}

main().catch((e) => {
  console.error(`[dados] ${e.message}`)
  process.exitCode = 1
})
