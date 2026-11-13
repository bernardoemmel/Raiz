#!/usr/bin/env node
/** Busca exclusivamente a projeção agregada, quando sua origem estiver configurada. */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")

export async function baixarAcerto({ origem = process.env.RAIZ_ACERTO_URL, destino = path.join(repo, "dados/acerto/placar.json"), pedir = fetch } = {}) {
  if (process.env.RAIZ_ACERTO_DADOS || process.env.RAIZ_SEM_DOWNLOAD === "1") return "local"
  // Sem servidor/arquivo publicado, o plugin entrega um JSON de ausência, sem tentar uma URL inexistente.
  if (!origem) { fs.rmSync(destino, { force: true }); return "ausente" }
  const url = new URL(origem)
  if (url.protocol !== "https:" || url.username || url.password) throw new Error("A origem do acerto precisa ser HTTPS e pública.")
  const resposta = await pedir(url, { signal: AbortSignal.timeout(20000) })
  if (!resposta.ok) throw new Error("Não foi possível atualizar o resumo de acerto.")
  const bruto = await resposta.json()
  if (bruto.schema !== "raiz.acerto.publico.v1") throw new Error("Só o resumo público do aprendizado pode ser usado.")
  // A allowlist completa é aplicada pelo plugin antes de qualquer byte ir ao site.
  fs.mkdirSync(path.dirname(destino), { recursive: true })
  fs.writeFileSync(`${destino}.tmp`, JSON.stringify(bruto))
  fs.renameSync(`${destino}.tmp`, destino)
  return "atualizado"
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await baixarAcerto()
