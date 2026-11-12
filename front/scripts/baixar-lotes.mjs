#!/usr/bin/env node
/** Compatibilidade do site estático: lotes financeiros exigem a API autenticada. */
import fs from "node:fs/promises"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const NOME = "lote_PA_central_r11.json"

export async function baixarLotes({ destino, agora = () => new Date() }) {
  // Não ler o Release, mesmo se um chamador antigo fornecer origem/pedir.
  // Substituir também o snapshot legado: ele pode conter crédito, TIR e preço.
  const dado = {
    situacao: "ausente",
    acesso: "privado",
    motivo: "api_autenticada",
    verificado_em: agora().toISOString(),
  }
  await fs.mkdir(destino, { recursive: true })
  const arquivo = path.join(destino, NOME)
  const temporario = `${arquivo}.${process.pid}.tmp`
  try {
    await fs.writeFile(temporario, JSON.stringify(dado))
    await fs.rename(temporario, arquivo)
  } finally {
    await fs.rm(temporario, { force: true })
  }
  return "ausente"
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const situacao = await baixarLotes({
      destino: path.resolve(REPO, process.env.RAIZ_LOTES || "dados/lotes"),
    })
    console.log(`[lotes] Cópia pública: ${situacao}. Lotes financeiros estão disponíveis somente pela API autenticada; nenhum download foi feito.`)
  } catch (erro) {
    console.error(`[lotes] ${erro.message}`)
    process.exitCode = 1
  }
}
