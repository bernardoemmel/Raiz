#!/usr/bin/env node
/** Publica no site a última coleta do Release calendario, sem inventar uma agenda quando ela ainda não existe. */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const PADRAO = path.join(repo, "front/globo/public/calendario")
const AUSENTE = { disponivel: false, coletado_em: null, eventos: [], total: 0, fontes: [] }
const FEED_VAZIO = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Raiz//Calendario//PT-BR\r\nEND:VCALENDAR\r\n"

function salvar(destino, json, ics) {
  const agenda = JSON.parse(json)
  if (!Array.isArray(agenda.eventos) || !Array.isArray(agenda.fontes) || !ics.startsWith("BEGIN:VCALENDAR")) throw new Error("formato da coleta inválido")
  fs.mkdirSync(destino, { recursive: true })
  for (const [nome, conteudo] of [["eventos.json", json], ["eventos.ics", ics]]) {
    fs.writeFileSync(path.join(destino, `${nome}.tmp`), conteudo)
    fs.renameSync(path.join(destino, `${nome}.tmp`), path.join(destino, nome))
  }
  return agenda
}

/** A ausência é um recurso HTTP válido; uma falha nunca apaga a última coleta conhecida. */
export async function baixarCalendario({
  destino = PADRAO,
  origem = process.env.RAIZ_CALENDARIO_URL || "https://github.com/bernardoemmel/Raiz/releases/download/calendario",
  local = process.env.RAIZ_CALENDARIO_DADOS,
  semDownload = process.env.RAIZ_SEM_DOWNLOAD === "1",
  pedir = fetch,
} = {}) {
  if (local) {
    // Snapshot explícito ausente ou inválido é erro, sem substituição por coleta pública ou antiga.
    const pasta = path.resolve(repo, local)
    salvar(destino, fs.readFileSync(path.join(pasta, "eventos.json"), "utf8"), fs.readFileSync(path.join(pasta, "eventos.ics"), "utf8"))
    return "local"
  }
  if (!semDownload) {
    try {
      const respostas = await Promise.all(["eventos.json", "eventos.ics"].map((nome) => pedir(`${origem}/${nome}`, { signal: AbortSignal.timeout(20000) })))
      if (respostas.some((r) => !r.ok)) throw new Error("coleta ainda não publicada ou fonte indisponível")
      const [json, ics] = await Promise.all(respostas.map((r) => r.text()))
      const agenda = salvar(destino, json, ics)
      console.log(`[calendário] ${agenda.eventos.length} eventos da última coleta disponíveis no site.`)
      return "atualizado"
    } catch {
      console.warn("[calendário] A coleta não pôde ser baixada. A última cópia será preservada; sem cópia, o site informa a indisponibilidade.")
    }
  }
  if (fs.existsSync(path.join(destino, "eventos.json"))) return "preservado"
  salvar(destino, JSON.stringify(AUSENTE), FEED_VAZIO)
  return "ausente"
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await baixarCalendario()
