#!/usr/bin/env node
/** Conta humana: rede simulada, nenhum envio ou pagamento real. */
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import fs from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath } from "node:url"

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
const requireGlobo = createRequire(path.join(repo, "front/globo/package.json"))
let playwright
try { playwright = requireGlobo("playwright") } catch {
  const global = execFileSync("npm", ["root", "-g"], { encoding: "utf8" }).trim()
  playwright = createRequire(path.join(global, "resolver.js"))("playwright")
}
const localPython = path.join(repo, ".venv/bin/python")
const python = process.env.RAIZ_PYTHON || (fs.existsSync(localPython) ? localPython : "python")
const render = JSON.parse(execFileSync(python, ["-c", [
  "import json", "from raiz.publica.pagina_conta import pagina", "from raiz.publica.conta import premissas",
  "r=pagina(premissas())", "print(json.dumps({'html':r.body.decode(),'headers':dict(r.headers)}))",
].join("\n")], {cwd:repo, encoding:"utf8"}))
const origem="https://api.raiz.example", base="/v1/conta/gerenciar", chamadas=[], erros=[], externas=[]
let contrato=false, clique=false, invalido=false
const executablePath=process.env.RAIZ_CHROMIUM || (fs.existsSync("/usr/bin/chromium")?"/usr/bin/chromium":undefined)
const browser=await playwright.chromium.launch({headless:true,executablePath})
try {
 const contexto=await browser.newContext()
 await contexto.route("**/*",async route=>{
  const req=route.request(), u=new URL(req.url()), json=d=>route.fulfill({contentType:"application/json",body:JSON.stringify(d)})
  if(u.origin!==origem) {externas.push(req.url());return route.abort()}
  chamadas.push({rota:u.pathname,metodo:req.method()})
  if(u.pathname===base) return route.fulfill({headers:render.headers,body:render.html})
  if(u.pathname===base+"/entrar") return json({enviado:true})
  if(u.pathname==="/entrar/confirmar") return json({token:"sessao-sintetica"})
  assert.equal(req.headers().authorization,"Bearer sessao-sintetica")
  if(u.pathname==="/v1/conta") return json({saldo_rs:0,testes_restantes:0,liberada:false,contrato_aceito_em:contrato?"2026-11-13":null,sinal_pago_em:null})
  assert.ok(clique,"A página tentou autorizar sem clique da pessoa")
  if(u.pathname==="/v1/conta/contrato") {contrato=true;return json({})}
  if(["/v1/conta/recarga","/v1/conta/sinal"].includes(u.pathname)) {
   if(u.pathname.endsWith("recarga")) assert.equal(u.searchParams.get("valor_rs"),"750")
   return json({link_para_uma_pessoa:invalido?"https://externo.example/pagar":origem+"/v1/cobrancas/"+"a".repeat(32)})
  }
  externas.push(req.url());await route.abort()
 })
 let pagina=await contexto.newPage();pagina.on("pageerror",e=>erros.push(e.message))
 await pagina.goto(origem+base)
 assert.equal(chamadas.filter(c=>c.metodo==="POST").length,0)
 await pagina.locator("#email").fill("pessoa@empresa.example")
 await pagina.locator("#login button").click()
 await pagina.locator("#aviso").filter({hasText:"você receberá"}).waitFor()
 pagina=await contexto.newPage();pagina.on("pageerror",e=>erros.push(e.message))
 await pagina.goto(origem+base+"#/entrar/login-sintetico")
 await pagina.locator("#conta").waitFor({state:"visible"})
 assert.equal(new URL(pagina.url()).hash,"")
 assert.ok(await pagina.locator("#aceitar").isDisabled())
 assert.equal(chamadas.filter(c=>c.metodo==="POST" && ["/v1/conta/contrato","/v1/conta/recarga","/v1/conta/sinal"].includes(c.rota)).length,0)
 clique=true
 await pagina.locator("#aceito").check();await pagina.locator("#aceitar").click()
 await pagina.locator("#contrato").waitFor({state:"hidden"})
 await pagina.locator("#sinal").click();await pagina.locator("#pix").waitFor({state:"visible"})
 assert.match(await pagina.locator("#pix").getAttribute("href"),/\/v1\/cobrancas\//)
 await pagina.locator("#valor").fill("750");await pagina.locator("#recarga button").click()
 await pagina.waitForFunction(()=>!document.querySelector('#recarga button').disabled)
 assert.equal(chamadas.filter(c=>c.rota==="/v1/conta/recarga").length,1)
 invalido=true;await pagina.locator("#recarga button").click()
 await pagina.locator("#aviso").filter({hasText:"Link de pagamento inválido"}).waitFor()
 assert.deepEqual(externas,[]);assert.deepEqual(erros,[])
 console.log("Conta humana: login, contrato e Pix só após clique; link externo recusado; zero pagamento.")
} finally {await browser.close()}
