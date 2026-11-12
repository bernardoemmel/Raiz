#!/usr/bin/env node
/** Publica no site a última coleta do Release calendario, sem inventar uma agenda quando ela ainda não existe. */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const destino = path.join(repo, "front/globo/public/calendario")
const origem = process.env.RAIZ_CALENDARIO_URL || "https://github.com/bernardoemmel/Raiz/releases/download/calendario"
function salvar(json, ics) {
  const agenda = JSON.parse(json)
  if (!Array.isArray(agenda.eventos) || !Array.isArray(agenda.fontes) || !ics.startsWith("BEGIN:VCALENDAR")) throw new Error("formato da coleta inválido")
  fs.mkdirSync(destino, { recursive: true })
  for (const [nome, conteudo] of [["eventos.json", json], ["eventos.ics", ics]]) {
    fs.writeFileSync(path.join(destino, `${nome}.tmp`), conteudo)
    fs.renameSync(path.join(destino, `${nome}.tmp`), path.join(destino, nome))
  }
  console.log(`[calendário] ${agenda.eventos.length} eventos da última coleta disponíveis no site.`)
}
if (process.env.RAIZ_CALENDARIO_DADOS) {
  // Um snapshot local explícito permite testar o mesmo build sem buscar dados reais na internet.
  // Arquivo ausente ou inválido é erro: não substituir a fixture por uma coleta pública ou antiga.
  const local = path.resolve(repo, process.env.RAIZ_CALENDARIO_DADOS)
  salvar(fs.readFileSync(path.join(local, "eventos.json"), "utf8"), fs.readFileSync(path.join(local, "eventos.ics"), "utf8"))
} else if (process.env.RAIZ_SEM_DOWNLOAD !== "1") {
  try {
    const respostas = await Promise.all(["eventos.json", "eventos.ics"].map((nome) => fetch(`${origem}/${nome}`, { signal: AbortSignal.timeout(20000) })))
    if (respostas.some((r) => !r.ok)) throw new Error("coleta ainda não publicada ou fonte indisponível")
    const [json, ics] = await Promise.all(respostas.map((r) => r.text()))
    salvar(json, ics)
  } catch {
    console.warn("[calendário] A coleta não pôde ser baixada. O site mostra a última cópia, se existir, com a data da coleta.")
  }
}
