#!/usr/bin/env node
/** Publica no site a última coleta do Release calendario, sem inventar uma agenda quando ela ainda não existe. */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const destino = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../globo/public/calendario")
const origem = process.env.RAIZ_CALENDARIO_URL || "https://github.com/bernardoemmel/Raiz/releases/download/calendario"
if (process.env.RAIZ_SEM_DOWNLOAD !== "1") {
  try {
    const respostas = await Promise.all(["eventos.json", "eventos.ics"].map((nome) => fetch(`${origem}/${nome}`, { signal: AbortSignal.timeout(20000) })))
    if (respostas.some((r) => !r.ok)) throw new Error("coleta ainda não publicada ou fonte indisponível")
    const [json, ics] = await Promise.all(respostas.map((r) => r.text()))
    const agenda = JSON.parse(json)
    if (!Array.isArray(agenda.eventos) || !Array.isArray(agenda.fontes) || !ics.startsWith("BEGIN:VCALENDAR")) throw new Error("formato da coleta inválido")
    fs.mkdirSync(destino, { recursive: true })
    for (const [nome, conteudo] of [["eventos.json", json], ["eventos.ics", ics]]) {
      fs.writeFileSync(path.join(destino, `${nome}.tmp`), conteudo)
      fs.renameSync(path.join(destino, `${nome}.tmp`), path.join(destino, nome))
    }
    console.log(`[calendário] ${agenda.eventos.length} eventos da última coleta disponíveis no site.`)
  } catch {
    console.warn("[calendário] A coleta não pôde ser baixada. O site mostra a última cópia, se existir, com a data da coleta.")
  }
}
