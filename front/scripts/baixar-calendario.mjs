#!/usr/bin/env node
/** Revalida a coleta do Release e refaz JSON/ICS públicos; nunca copia bytes remotos ao site. */
import fs from "node:fs"
import path from "node:path"
import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const PADRAO = path.join(repo, "front/globo/public/calendario")
const AUSENTE = { disponivel: false, coletado_em: null, eventos: [], total: 0, fontes: [] }

function salvar(destino, json) {
  let projetado
  try {
    if (Buffer.byteLength(json) > 16 * 1024 * 1024) throw new Error("limite")
    projetado = JSON.parse(execFileSync("python3", ["-m", "raiz.qualidade_calendario"], {
      cwd: repo, input: json, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"], maxBuffer: 32 * 1024 * 1024,
    }))
    if (JSON.parse(json).disponivel === false) {
      if (projetado.agenda.eventos.length || projetado.agenda.fontes.length) throw new Error("ausência contraditória")
      projetado.agenda.disponivel = false
    }
  } catch {
    throw new Error("A coleta do calendário não passou na validação de publicação; nenhum conteúdo novo foi copiado.")
  }
  fs.mkdirSync(destino, { recursive: true })
  for (const [nome, conteudo] of [["eventos.json", JSON.stringify(projetado.agenda)], ["eventos.ics", projetado.ics]]) {
    fs.writeFileSync(path.join(destino, `${nome}.tmp`), conteudo)
    fs.renameSync(path.join(destino, `${nome}.tmp`), path.join(destino, nome))
  }
  return projetado.agenda
}

/** A ausência é um recurso HTTP válido. Cache e coleta passam pelo mesmo portão. */
export async function baixarCalendario({
  destino = PADRAO,
  origem = process.env.RAIZ_CALENDARIO_URL || "https://github.com/bernardoemmel/Raiz/releases/download/calendario",
  local = process.env.RAIZ_CALENDARIO_DADOS,
  semDownload = process.env.RAIZ_SEM_DOWNLOAD === "1",
  pedir = fetch,
} = {}) {
  if (local) {
    const pasta = path.resolve(repo, local)
    salvar(destino, fs.readFileSync(path.join(pasta, "eventos.json"), "utf8"))
    return "local"
  }
  if (!semDownload) {
    let json
    try {
      const resposta = await pedir(`${origem}/eventos.json`, { signal: AbortSignal.timeout(20000) })
      if (!resposta.ok) throw new Error("coleta indisponível")
      json = await resposta.text()
    } catch {
      console.warn("[calendário] A coleta não pôde ser baixada. A última cópia só será usada se passar novamente na validação; sem cópia, o site informa a indisponibilidade.")
    }
    // HTTP 200 com conteúdo inválido bloqueia o build; não é indisponibilidade da fonte.
    if (json !== undefined) {
      const agenda = salvar(destino, json)
      console.log(`[calendário] ${agenda.eventos.length} eventos validados; feed reconstruído dos mesmos dados.`)
      return "atualizado"
    }
  }
  const arquivo = path.join(destino, "eventos.json")
  if (fs.existsSync(arquivo)) {
    salvar(destino, fs.readFileSync(arquivo, "utf8"))
    return "preservado"
  }
  salvar(destino, JSON.stringify(AUSENTE))
  return "ausente"
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await baixarCalendario()
