#!/usr/bin/env node
/** Baixa somente o contrato publico_basico v1. Pacotes legados e campos desconhecidos falham fechados. */
import { execFileSync } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const RAIZ_REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const DESTINO = path.resolve(RAIZ_REPO, process.env.RAIZ_DADOS || "dados/publicos")
const URL_BASE = process.env.RAIZ_DADOS_URL || "https://github.com/bernardoemmel/raiz/releases/download/dados"
const args = process.argv.slice(2)
const comGeo = args.includes("--geo")
const exigir = args.includes("--exigir")
const pedidos = args.filter((a) => /^[A-Z]{2}$/.test(a))
const UFS = new Set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(" "))
const BASICAS = ["cod_imovel", "cod_ibge", "municipio", "uf", "situacao_basica"]
const RESUMO = new Set(("cod_ibge municipio imoveis sem_problema def_RL aptas_carbono ha_carbono tco2_ano_aptas aptas_com_matricula ha_carbono_matricula cota_reserva redd_imoveis redd_ha app_imoveis app_ha frigorifico_imoveis frigorifico_ha compensacao_ha eudr_ok credito_rural_ok compra_arrendamento alerta_pos2020_imoveis frente_regularizar_antes frente_carbono frente_silvipastoril frente_desbloqueio frente_carbono_revisar_desm10anos frente_assentamento_agrupado frente_carbono_so_plantio frente_fora_TI frente_ja_tem_projeto").split(" "))
const SEM_IMOVEIS = new Set(["cod_ibge", "municipio", "verificado_em"])
const SITUACOES = new Set(["apto", "com_pendencia", "nao_apto"])
const CHAVES_ESTADO = new Set("versao_publicacao escopo municipios sem_imoveis total_ibge completo funil_completo tamanho versao atualizado_em motor_versao situacao faltam tabelas versoes url geo".split(" "))
const objeto = (v) => v !== null && typeof v === "object" && !Array.isArray(v)
const marcado = (v) => objeto(v) && v.versao_publicacao === 1 && v.escopo === "publico_basico"

function chaves(dado, permitidas, rotulo) {
  if (!objeto(dado) || Object.keys(dado).some((k) => !permitidas.has(k))) throw new Error(`${rotulo}: metadados fora do contrato público`)
}
function urlPacote(url, uf, geo = false) {
  const esperado = `raiz_${geo ? "geo_" : ""}${uf}.tar.gz`
  const u = new URL(url)
  const base = new URL(URL_BASE)
  if (!['https:', 'http:'].includes(u.protocol) || u.origin !== base.origin || u.username || u.password || path.posix.basename(u.pathname) !== esperado)
    throw new Error(`${uf}: endereço fora do pacote público esperado`)
  return u.href
}
function validarManifesto(m) {
  chaves(m, new Set(["versao_publicacao", "escopo", "gerado_em", "repo", "tag", "estados"]), "manifesto")
  if (!marcado(m) || !objeto(m.estados)) throw new Error("manifesto legado ou versão pública desconhecida")
  if ((m.repo !== undefined && (typeof m.repo !== "string" || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(m.repo))) ||
      (m.tag !== undefined && (typeof m.tag !== "string" || !/^[A-Za-z0-9_.-]+$/.test(m.tag))))
    throw new Error("manifesto: repositório ou tag inválidos")
  for (const [uf, estado] of Object.entries(m.estados)) {
    if (!UFS.has(uf) || !marcado(estado)) throw new Error("estado sem marca publico_basico v1")
    chaves(estado, CHAVES_ESTADO, uf)
    if (estado.url) urlPacote(estado.url, uf)
    else if (estado.municipios || estado.tamanho) throw new Error(`${uf}: pacote público sem endereço`)
    if (estado.geo) {
      chaves(estado.geo, new Set(["url", "versao", "tamanho", "municipios", "escopo", "versao_publicacao"]), `${uf}/geo`)
      if (estado.geo.escopo !== "publico_basico" || (estado.geo.versao_publicacao !== undefined && estado.geo.versao_publicacao !== 1))
        throw new Error(`${uf}: geometria sem marca pública`)
      if (estado.geo.municipios !== undefined && (!Number.isInteger(estado.geo.municipios) || estado.geo.municipios < 0))
        throw new Error(`${uf}: quantidade de municípios da geometria inválida`)
      urlPacote(estado.geo.url, uf, true)
    }
  }
  return m
}

function linhasCsv(texto) {
  const linhas = []
  let campos = [], campo = "", aspas = false
  const s = texto.replace(/^\uFEFF/, "")
  for (let i = 0; i < s.length; i++) {
    const c = s[i]
    if (c === '"') {
      if (aspas && s[i + 1] === '"') { campo += '"'; i++ }
      else aspas = !aspas
    } else if (!aspas && (c === "," || c === "\n" || c === "\r")) {
      campos.push(campo); campo = ""
      if (c !== ",") {
        if (campos.some(Boolean)) linhas.push(campos)
        campos = []
        if (c === "\r" && s[i + 1] === "\n") i++
      }
    } else campo += c
  }
  if (aspas) throw new Error("CSV com aspas sem fechamento")
  if (campo || campos.length) { campos.push(campo); linhas.push(campos) }
  return linhas
}
function validarCsv(nome, dado, uf) {
  const [colunas, ...linhas] = linhasCsv(dado.toString("utf8"))
  const basico = /^imoveis_basicos_\d{7}\.csv$/.test(nome)
  const permitidas = basico ? new Set(BASICAS) : nome === `resumo_${uf}.csv` ? RESUMO : nome === `sem_imoveis_${uf}.csv` ? SEM_IMOVEIS : new Set()
  if (!colunas?.length || new Set(colunas).size !== colunas.length || colunas.some((c) => !permitidas.has(c)) || (basico && colunas.join() !== BASICAS.join()))
    throw new Error(`${nome}: colunas fora do contrato público`)
  for (const campos of linhas) {
    if (campos.length !== colunas.length) throw new Error(`${nome}: CSV ambíguo`)
    const r = Object.fromEntries(colunas.map((c, i) => [c, campos[i]]))
    if (!/^\d{7}$/.test(r.cod_ibge)) throw new Error(`${nome}: município inválido`)
    if (basico && (!/^[A-Z]{2}-\d{7}-[0-9A-F]{32}$/.test(r.cod_imovel) || r.cod_imovel.slice(0, 2) !== uf || r.cod_ibge !== nome.slice(16, 23) || r.uf !== uf || !SITUACOES.has(r.situacao_basica)))
      throw new Error(`${nome}: identificação ou situação básica inválida`)
  }
}
function arquivoPermitido(nome, uf, geo) {
  return geo ? new RegExp(`^${uf}/geo_\\d{7}\\.parquet$`).test(nome)
    : new RegExp(`^${uf}/(resumo_${uf}|sem_imoveis_${uf}|imoveis_basicos_\\d{7})\\.csv$`).test(nome)
}
/** Repete somente a transferência GET; JSON, tar e o contrato são validados uma única vez depois. */
async function baixarBytes(url, rotulo) {
  const endereco = new URL(url)
  if (!["http:", "https:"].includes(endereco.protocol)) throw new Error(`${rotulo}: endereço de download inválido`)
  for (let tentativa = 1; tentativa <= 3; tentativa++) {
    let resposta, falha
    try {
      resposta = await fetch(endereco, { redirect: "follow" })
      if (resposta.ok) return Buffer.from(await resposta.arrayBuffer())
    } catch (erro) { falha = erro }
    if (resposta && !resposta.ok) {
      // Libera a conexão antes de tentar outra vez; o corpo de erro não é um pacote.
      await resposta.body?.cancel().catch(() => {})
      falha = new Error(`${rotulo}: HTTP ${resposta.status}`)
      if (![408, 429].includes(resposta.status) && !(resposta.status >= 500 && resposta.status <= 599)) throw falha
    }
    if (tentativa === 3) throw falha
    console.warn(`[dados] ${rotulo}: transferência interrompida; nova tentativa ${tentativa + 1}/3.`)
    await new Promise((resolver) => setTimeout(resolver, tentativa * 1000))
  }
}
async function baixarEExtrair(url, uf, destino, geo = false, permiteVazio = false) {
  const bytes = await baixarBytes(urlPacote(url, uf, geo), `pacote ${uf}`)
  const tmp = path.join(destino, `pacote${geo ? "-geo" : ""}.tar.gz`)
  fs.writeFileSync(tmp, bytes)
  try {
    const nomes = execFileSync("tar", ["-tzf", tmp], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 }).trim().split("\n").filter(Boolean)
    const detalhes = execFileSync("tar", ["-tvzf", tmp], { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 }).trim().split("\n").filter(Boolean)
    if ((!nomes.length && !permiteVazio) || new Set(nomes).size !== nomes.length || nomes.some((n) => !arquivoPermitido(n, uf, geo)) || detalhes.length !== nomes.length || detalhes.some((l) => !l.startsWith("-")))
      throw new Error(`${uf}: pacote contém caminho, link ou arquivo fora do contrato público`)
    // Extração apenas por stdout: nenhum caminho ou link contido no tar pode escrever no workspace.
    for (const nome of nomes) {
      const dado = execFileSync("tar", ["-xOzf", tmp, "--", nome], { maxBuffer: 512 * 1024 * 1024 })
      if (!geo) validarCsv(path.basename(nome), dado, uf)
      fs.writeFileSync(path.join(destino, path.basename(nome)), dado)
    }
  } finally { fs.rmSync(tmp, { force: true }) }
}
function pastaConforme(uf, info) {
  const dir = path.join(DESTINO, uf)
  if (!marcado(info) || !fs.existsSync(dir)) return false
  return fs.readdirSync(dir, { withFileTypes: true }).every((f) => f.isFile() && (
    arquivoPermitido(`${uf}/${f.name}`, uf, false) || (info.geo && arquivoPermitido(`${uf}/${f.name}`, uf, true))
  ))
}
async function main() {
  if (process.env.RAIZ_SEM_DOWNLOAD === "1") return
  let remoto
  try {
    const bytes = await baixarBytes(`${URL_BASE}/estados.json`, "manifesto público")
    remoto = validarManifesto(JSON.parse(new TextDecoder().decode(bytes)))
  } catch (e) {
    if (exigir) throw e
    console.warn(`[dados] não consegui ler o estados.json público (${e.message}); nenhum pacote legado será baixado.`)
    return
  }
  const arqLocal = path.join(DESTINO, "estados.json")
  let local = { versao_publicacao: 1, escopo: "publico_basico", estados: {} }
  try { local = validarManifesto(JSON.parse(fs.readFileSync(arqLocal, "utf8"))) } catch {}
  const falhas = []
  let mudou = false
  for (const uf of Object.keys(remoto.estados).filter((uf) => !pedidos.length || pedidos.includes(uf))) {
    const r = remoto.estados[uf], l = local.estados[uf]
    if (!r.url) {
      const atual = path.join(DESTINO, uf)
      if (fs.existsSync(atual) && fs.readdirSync(atual).length && !marcado(l)) {
        falhas.push(uf)
        console.warn(`[dados] falhou ${uf}: destino legado preservado; escolha uma pasta vazia para os dados públicos`)
        continue
      }
      // Zero municípios sem pacote também retira a cobertura antiga já marcada como pública.
      if (marcado(l)) fs.rmSync(atual, { recursive: true, force: true })
      local.estados[uf] = r; mudou = true; continue
    }
    if (pastaConforme(uf, l) && l.versao === r.versao && (!comGeo || l.geo?.versao === r.geo?.versao)) continue
    const staging = fs.mkdtempSync(path.join(os.tmpdir(), `raiz-publico-${uf}-`))
    try {
      const atual = path.join(DESTINO, uf)
      if (fs.existsSync(atual) && fs.readdirSync(atual).length && !marcado(l))
        throw new Error(`${uf}: destino legado preservado; escolha uma pasta vazia para os dados públicos`)
      console.log(`[dados] baixando pacote público de ${uf}`)
      // Pacote vazio só é legítimo quando o manifesto público declara zero municípios.
      await baixarEExtrair(r.url, uf, staging, false, r.municipios === 0)
      if (comGeo && r.geo) await baixarEExtrair(r.geo.url, uf, staging, true, r.geo.municipios === 0)
      fs.mkdirSync(DESTINO, { recursive: true })
      // A pasta do estado só é substituída depois de todos os arquivos passarem pelo contrato.
      const proximo = path.join(DESTINO, `.${uf}-${process.pid}`)
      fs.rmSync(proximo, { recursive: true, force: true })
      fs.cpSync(staging, proximo, { recursive: true })
      fs.rmSync(path.join(DESTINO, uf), { recursive: true, force: true })
      fs.renameSync(proximo, path.join(DESTINO, uf))
      const { geo: _geo, ...metadados } = r
      local.estados[uf] = { ...metadados, ...(comGeo && r.geo ? { geo: r.geo } : {}) }
      mudou = true
    } catch (e) {
      falhas.push(uf)
      console.warn(`[dados] falhou ${uf}: ${e.message}`)
    } finally { fs.rmSync(staging, { recursive: true, force: true }) }
  }
  if (mudou) {
    fs.mkdirSync(DESTINO, { recursive: true })
    fs.writeFileSync(arqLocal, JSON.stringify({ ...remoto, estados: local.estados }, null, 1))
  }
  if (exigir && falhas.length) throw new Error(`não consegui atualizar os estados: ${falhas.join(", ")}`)
  console.log(`[dados] pacotes públicos em ${path.relative(RAIZ_REPO, DESTINO) || DESTINO}: ${Object.keys(local.estados).join(", ")}`)
}
main().catch((e) => { console.error(`[dados] ${e.message}`); process.exitCode = 1 })
