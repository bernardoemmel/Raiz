#!/usr/bin/env node
/** Compara só o artefato atual com a última publicação efetiva, nunca com cache de uma rodada incompleta. */
import fs from "node:fs"
import path from "node:path"
import { pathToFileURL } from "node:url"
import { configurarPublicacao } from "./configurar-publicacao.mjs"

function coberturaValida(indice) {
  const c = indice?.cobertura
  if (!c || !Array.isArray(c.com_desenho) || !Array.isArray(c.sem_desenho)
    || !c.com_desenho.every((cod) => typeof cod === "string" && /^\d{7}$/.test(cod)) || !c.sem_desenho.every((cod) => typeof cod === "string" && /^\d{7}$/.test(cod))
    || typeof c.gerado_em !== "string" || !Number.isFinite(Date.parse(c.gerado_em))) return null
  return c
}

export function compararCobertura(atual, anterior) {
  const a = coberturaValida(atual), b = coberturaValida(anterior)
  if (!a || !b || Date.parse(b.gerado_em) > Date.parse(a.gerado_em)) return null
  const antes = new Set([...b.com_desenho, ...b.sem_desenho])
  const agora = new Set([...a.com_desenho, ...a.sem_desenho])
  return { anterior_em: b.gerado_em, atual_em: a.gerado_em, municipios: [...agora].filter((cod) => !antes.has(cod)).sort() }
}

export async function registrarNovosMunicipios({ site = "site", siteUrl = configurarPublicacao().siteUrl, buscar = fetch } = {}) {
  const arquivo = path.join(site, "geo/indice.json")
  const atual = JSON.parse(fs.readFileSync(arquivo, "utf8"))
  if (!coberturaValida(atual)) throw new Error("O artefato atual não tem um manifesto de cobertura válido.")
  // Ausência, rede ou índice antigo sem cobertura não transformam todo o Brasil em municípios novos.
  let anterior = null
  try {
    const resposta = await buscar(new URL("geo/indice.json", siteUrl), { headers: { "Cache-Control": "no-cache" }, signal: AbortSignal.timeout(20_000) })
    if (resposta.ok && /json/.test(resposta.headers.get("content-type") || "")) anterior = await resposta.json()
  } catch { /* a comparação é informativa; não oculta os dados atuais */ }
  atual.cobertura.novos_desde = compararCobertura(atual, anterior)
  fs.writeFileSync(arquivo, JSON.stringify(atual) + "\n")
  const comparacao = atual.cobertura.novos_desde
  console.log(comparacao ? `${comparacao.municipios.length} municípios novos desde a publicação de ${comparacao.anterior_em}.` : "Comparação com a publicação anterior indisponível; contador de novos permanece desconhecido.")
  return comparacao
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await registrarNovosMunicipios()
