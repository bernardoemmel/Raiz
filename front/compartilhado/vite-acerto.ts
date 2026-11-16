import fs from "node:fs"
import path from "node:path"
import type { Plugin } from "../globo/node_modules/vite/dist/node/index"
import { ACERTO_AUSENTE, lerResumoAcerto } from "./acerto"

/** Reprojeta o JSON no servidor de desenvolvimento e no build; nunca copia o bruto. */
export function acertoRaiz({ repo }: { repo: string }): Plugin {
  const arquivo = path.resolve(repo, process.env.RAIZ_ACERTO_DADOS || "dados/acerto/placar.json")
  if (process.env.RAIZ_ACERTO_DADOS && !fs.existsSync(arquivo)) throw new Error("Resumo de acerto configurado não encontrado.")
  const conteudo = () => JSON.stringify(fs.existsSync(arquivo) ? lerResumoAcerto(JSON.parse(fs.readFileSync(arquivo, "utf8"))) : ACERTO_AUSENTE)
  let base = "/"
  return {
    name: "raiz-acerto-publico",
    configResolved(config) { base = config.base },
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if ((req.url || "").split("?")[0] !== `${base}acerto/placar.json`) return next()
        try { res.setHeader("Content-Type", "application/json"); res.end(conteudo()) }
        catch { res.statusCode = 503; res.end("Resumo de acerto indisponível.") }
      })
    },
    generateBundle() { this.emitFile({ type: "asset", fileName: "acerto/placar.json", source: conteudo() }) },
  }
}
