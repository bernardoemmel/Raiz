#!/usr/bin/env node
/** Revalida a coleta do Release e refaz JSON/ICS públicos; nunca copia bytes remotos ao site. */
import fs from "node:fs"
import path from "node:path"
import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const destino = path.join(repo, "front/globo/public/calendario")
const origem = process.env.RAIZ_CALENDARIO_URL || "https://github.com/bernardoemmel/Raiz/releases/download/calendario"
function salvar(json) {
  let projetado
  try {
    if (Buffer.byteLength(json) > 16 * 1024 * 1024) throw new Error("limite")
    projetado = JSON.parse(execFileSync("python3", ["-m", "raiz.qualidade_calendario"], {
      cwd: repo, input: json, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"], maxBuffer: 32 * 1024 * 1024,
    }))
  } catch {
    throw new Error("A coleta do calendário não passou na validação de publicação; nenhum conteúdo novo foi copiado.")
  }
  fs.mkdirSync(destino, { recursive: true })
  for (const [nome, conteudo] of [["eventos.json", JSON.stringify(projetado.agenda)], ["eventos.ics", projetado.ics]]) {
    fs.writeFileSync(path.join(destino, `${nome}.tmp`), conteudo)
    fs.renameSync(path.join(destino, `${nome}.tmp`), path.join(destino, nome))
  }
  console.log(`[calendário] ${projetado.agenda.eventos.length} eventos validados; feed reconstruído dos mesmos dados.`)
}
function revalidarCopia() {
  const arquivo = path.join(destino, "eventos.json")
  if (fs.existsSync(arquivo)) salvar(fs.readFileSync(arquivo, "utf8"))
  else fs.rmSync(destino, { recursive: true, force: true })
}
if (process.env.RAIZ_CALENDARIO_DADOS) {
  const local = path.resolve(repo, process.env.RAIZ_CALENDARIO_DADOS)
  salvar(fs.readFileSync(path.join(local, "eventos.json"), "utf8"))
} else if (process.env.RAIZ_SEM_DOWNLOAD !== "1") {
  let json
  try {
    const resposta = await fetch(`${origem}/eventos.json`, { signal: AbortSignal.timeout(20000) })
    if (!resposta.ok) throw new Error("coleta indisponível")
    json = await resposta.text()
  } catch {
    console.warn("[calendário] A coleta não pôde ser baixada. A última cópia só será usada se passar novamente na validação.")
  }
  // Um arquivo recebido mas inválido interrompe o build. Não é tratado como indisponibilidade de rede.
  if (json !== undefined) salvar(json)
  else revalidarCopia()
} else revalidarCopia()
