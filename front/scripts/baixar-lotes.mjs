#!/usr/bin/env node
/** Ponteiro publicado por restauracao_rodada: somente o resumo, nunca os pacotes por fazenda. */
import fs from "node:fs/promises"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const NOME = "lote_PA_central_r11.json"
const ORIGEM = "https://github.com/bernardoemmel/Raiz/releases/download/dados"

export async function baixarLotes({ destino, origem = ORIGEM, pedir = fetch, agora = () => new Date() }) {
  const resposta = await pedir(`${origem.replace(/\/$/, "")}/${NOME}`, {
    redirect: "follow", signal: AbortSignal.timeout(30_000),
  })
  let dado
  if (resposta.status === 404) {
    dado = { situacao: "ausente", verificado_em: agora().toISOString() }
  } else {
    if (!resposta.ok) throw new Error(`Não consegui conferir o lote do Pará: HTTP ${resposta.status}`)
    const texto = await resposta.text()
    if (Buffer.byteLength(texto) > 5_000_000) throw new Error("O resumo do lote excedeu 5 MB.")
    dado = JSON.parse(texto)
    if (dado.uf !== "PA" || dado.cenario !== "central_r11" || !dado.resumos || !Array.isArray(dado.opcoes))
      throw new Error("O ponteiro do lote não segue o contrato de central_r11 do Pará.")
    const modificacao = resposta.headers.get("last-modified")
    const data = modificacao ? new Date(modificacao) : null
    dado.publicado_em = data && Number.isFinite(data.getTime()) ? data.toISOString() : null
    dado.verificado_em = agora().toISOString()
  }
  await fs.mkdir(destino, { recursive: true })
  const arquivo = path.join(destino, NOME)
  const temporario = `${arquivo}.${process.pid}.tmp`
  await fs.writeFile(temporario, JSON.stringify(dado))
  await fs.rename(temporario, arquivo)
  return dado.situacao === "ausente" ? "ausente" : "publicado"
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const situacao = await baixarLotes({
      destino: path.resolve(REPO, process.env.RAIZ_LOTES || "dados/lotes"),
      origem: process.env.RAIZ_DADOS_URL || ORIGEM,
    })
    console.log(`[lotes] Pará central_r11: ${situacao}. O site publica somente os agregados.`)
  } catch (erro) {
    console.error(`[lotes] ${erro.message}`)
    process.exitCode = 1
  }
}
