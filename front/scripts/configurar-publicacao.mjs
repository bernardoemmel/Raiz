#!/usr/bin/env node
/** Um contrato para o caminho, a URL canônica e o CNAME da publicação. */
import fs from "node:fs"
import { isIP } from "node:net"
import { domainToASCII, pathToFileURL } from "node:url"

export function configurarPublicacao(env = process.env) {
  const informado = (env.RAIZ_DOMINIO || "").trim().toLowerCase()
  const dominio = domainToASCII(informado)
  if (informado && (!dominio || dominio.length > 253 || isIP(dominio)
    || !dominio.includes(".") || !/[a-z]/i.test(dominio.split(".").at(-1))
    || dominio.split(".").some((parte) => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(parte))
    || /[/:@?#\\\s]/.test(informado))) {
    throw new Error("RAIZ_DOMINIO precisa conter só o nome do domínio, sem https://, caminho, porta ou endereço IP.")
  }
  const repositorio = env.GITHUB_REPOSITORY || ""
  if (repositorio && !/^[a-zA-Z0-9-]+\/[a-zA-Z0-9_.-]+$/.test(repositorio))
    throw new Error("GITHUB_REPOSITORY precisa ter o formato conta/repositorio.")
  const [conta, projeto] = repositorio.split("/")
  const basePages = projeto && projeto.toLowerCase() !== `${conta.toLowerCase()}.github.io` ? `/${projeto}/` : "/"
  let base = (env.RAIZ_BASE || (dominio ? "/" : basePages)).trim()
  if (!base.endsWith("/")) base += "/"
  if (!/^\/(?:[a-zA-Z0-9._~-]+\/)*$/.test(base) || base.split("/").some((parte) => parte === "." || parte === ".."))
    throw new Error("RAIZ_BASE precisa ser um caminho absoluto, sem consulta, fragmento ou segmentos . e ...")
  if (dominio && base !== "/")
    throw new Error("Com RAIZ_DOMINIO, RAIZ_BASE precisa ser / para publicar robots.txt e llms.txt na raiz.")
  const padrao = dominio ? `https://${dominio}/` : conta ? `https://${conta.toLowerCase()}.github.io${base}` : `http://localhost${base}`
  const url = new URL(env.RAIZ_SITE_URL || padrao)
  if (!url.pathname.endsWith("/")) url.pathname += "/"
  if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== base)
    throw new Error("RAIZ_SITE_URL precisa ser uma URL HTTP(S) sem credenciais, consulta ou fragmento, com o mesmo caminho de RAIZ_BASE.")
  if (dominio && url.href !== `https://${dominio}/`)
    throw new Error("RAIZ_SITE_URL precisa corresponder a https://RAIZ_DOMINIO/.")
  return { base, siteUrl: url.href, dominio }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const config = configurarPublicacao()
    if (process.argv[2] === "--ambiente") console.log([config.base, config.siteUrl, config.dominio].join("\n"))
    else if (process.argv[2] === "--cname" && process.argv[3]) {
      if (config.dominio) fs.writeFileSync(process.argv[3], config.dominio + "\n")
      else fs.rmSync(process.argv[3], { force: true })
    } else console.log(JSON.stringify(config))
  } catch (erro) {
    console.error(`Configuração da publicação: ${erro.message}`)
    process.exitCode = 1
  }
}
