#!/usr/bin/env node
/**
 * Teste do pedido de lote no navegador (front/globo, cena-alvo): sobe o Vite com a amostra e, com a resposta de
 * exemplo (sem back-end), confere de ponta a ponta:
 *
 *   1. sem sessão, a área logada pede para entrar; o link do e-mail entra sem senha;
 *   2. "Novo pedido" já vem com 1 milhão de créditos, ProFloresta+, Amazônia e interesse "qualquer"; dá para desenhar
 *      a área no mapa;
 *   3. ao enviar: "Quanto existe na nossa base", as 3 opções em abas, o lote no mapa com as reservas listradas;
 *   4. tocar numa fazenda abre a ficha e deixa trocar por uma reserva;
 *   5. "Solicitar interesse dos donos": andamento com a barra da meta, ondas e recusas, o mapa na cor do interesse,
 *      até "Grupo pronto";
 *   6. o grupo: "Reservar este grupo" com valor, prazo e abatimento; Pix com QR e copia e cola; pago, "Reservado até"
 *      com a contagem regressiva, e "Meus pedidos" com o status;
 *   7. fazenda reservada por outro cliente some da ficha e da busca;
 *   8. nada de CPF ou contato de dono na tela; no celular, nada passa da largura da tela.
 *
 * Uso (de front/globo): npm run test:e2e (roda depois do teste da entrada).
 */
import { execSync } from "node:child_process"
import fs from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const GLOBO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../globo")
const REPO = path.resolve(GLOBO, "../..")
const doGlobo = createRequire(path.join(GLOBO, "package.json"))
function playwright() {
  try {
    return doGlobo("playwright")
  } catch {
    return createRequire(path.join(execSync("npm root -g").toString().trim(), "x.js"))("playwright")
  }
}
const { createServer } = await import(pathToFileURL(doGlobo.resolve("vite")).href)
const { chromium } = playwright()
const ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]

let falhas = 0
const conferir = (ok, frase) => {
  console.log(`${ok ? "ok  " : "FALHOU"} ${frase}`)
  if (!ok) falhas++
}

// a mesma conta de pedidos/exemplo.ts: fazenda que o exemplo trata como reservada por outro cliente
const sorteio = (t) => {
  let h = 0x811c9dc5
  for (let i = 0; i < t.length; i++) {
    h ^= t.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0) / 4294967296
}
const RESERVADA = fs
  .readFileSync(path.join(REPO, "dados/amostra/imoveis_1507300.csv"), "utf8")
  .split("\n")
  .slice(1)
  .map((l) => l.split(",")[0])
  .find((c) => c && sorteio("reserva:" + c) < 0.015)

// a amostra, sempre: números que o teste conhece
process.env.RAIZ_DADOS = "dados/amostra"
const servidor = await createServer({ root: GLOBO, configFile: path.join(GLOBO, "vite.config.ts"), server: { port: 0 }, logLevel: "error" })
await servidor.listen()
const URL_BASE = servidor.resolvedUrls.local[0]
const navegador = await chromium.launch({ args: ARGS })

async function pagina(opcoes) {
  const ctx = await navegador.newContext(opcoes)
  // ondas de contato a cada 300 ms (no back-end são dias)
  await ctx.addInitScript(() => localStorage.setItem("raiz.exemplo.onda_ms", "300"))
  const p = await ctx.newPage()
  const erros = []
  p.on("pageerror", (e) => erros.push(e.message))
  return { p, erros }
}
const semDadoPessoal = async (p, onde) => {
  const texto = await p.locator("body").innerText()
  const cpf = /\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b/.test(texto)
  const emails = (texto.match(/[^\s@]+@[^\s@]+\.[^\s@]+/g) ?? []).filter((e) => !e.startsWith("compras@exemplo"))
  conferir(!cpf && !emails.length, `${onde}: nenhum CPF nem contato de dono na tela`)
}

try {
  const { p, erros } = await pagina({ viewport: { width: 1440, height: 900 } })

  // 1. entrar sem senha
  await p.goto(URL_BASE + "#/pedidos")
  await p.getByRole("heading", { name: "Entrar na Raíz" }).waitFor({ timeout: 30000 })
  conferir(true, "sem sessão, Meus pedidos pede para entrar")
  await p.locator("input[type=email]").fill("compras@exemplo.com.br")
  await p.getByRole("button", { name: "Mandar o link" }).click()
  await p.getByText("Mandamos um link para").waitFor()
  await p.getByRole("link", { name: "Abrir o link de entrada" }).click()
  await p.waitForURL(/#\/pedidos$/, { timeout: 20000 })
  await p.getByText("Nenhum pedido ainda.").waitFor()
  conferir((await p.getByText("Entrou como compras@exemplo.com.br").count()) === 1, "o link entra e volta para Meus pedidos")

  // 2. novo pedido com os padrões
  await p.getByRole("link", { name: "Novo pedido" }).first().click()
  await p.waitForURL(/#\/pedidos\/novo$/)
  const meta = await p.getByLabel("Quantidade (créditos)").inputValue()
  const profloresta = await p.getByLabel(/ProFloresta\+/).isChecked()
  const amazonia = await p.getByLabel("Amazônia").isChecked()
  const qualquer = await p.getByRole("radio", { name: /^Qualquer/ }).isChecked()
  conferir(meta === "1.000.000" && profloresta && amazonia && qualquer, "o novo pedido já vem com 1 milhão de créditos, ProFloresta+, Amazônia e qualquer interesse")
  await p.getByLabel("Desenhar a área no mapa").check()
  await p.locator(".mapa-desenho canvas").waitFor({ timeout: 30000 })
  await p.waitForFunction(() => document.querySelector(".mapa-desenho")?.__mapa?.getSource("desenho"), null, { timeout: 30000 })
  const caixa = await p.locator(".mapa-desenho canvas").boundingBox()
  for (const [x, y] of [[0.3, 0.3], [0.6, 0.35], [0.5, 0.65]]) await p.mouse.click(caixa.x + caixa.width * x, caixa.y + caixa.height * y)
  await p.getByText("3 cantos", { exact: true }).waitFor()
  conferir(true, "dá para desenhar a área do pedido no mapa (3 cantos)")
  await p.getByRole("button", { name: "Apagar o desenho" }).click()
  await p.getByLabel("Desenhar a área no mapa").uncheck()

  // 3. enviar: base e as 3 opções
  await p.getByRole("button", { name: "Ver o que existe e montar o lote" }).click()
  await p.waitForURL(/#\/pedidos\/[a-z0-9]+$/, { timeout: 60000 })
  await p.getByRole("heading", { name: "Quanto existe na nossa base" }).waitFor({ timeout: 60000 })
  const frase = await p.locator(".quadro-base .frase").textContent()
  conferir(/fazendas aptas atendem o pedido: [\d.]+ ha e cerca de [\d,]+ milh(ão|ões) de créditos \(de/.test(frase ?? ""), `quadro da base em palavras ("${frase?.slice(0, 90)}…")`)
  conferir((await p.locator(".quadro-base table").count()) === 2, "a base por caminho da terra e por interesse do dono")
  const abas = await p.getByRole("tab").allTextContents()
  conferir(abas.join("|") === "Mais barata|Mais segura|Mais compacta", "as 3 opções em abas")
  await p.waitForFunction(() => document.querySelector(".mapa-lote")?.__mapa?.querySourceFeatures("lote").length > 0, null, { timeout: 60000 })
  const listras = await p.evaluate(() => JSON.stringify(document.querySelector(".mapa-lote").__mapa.getPaintProperty("lote-listras", "fill-opacity")))
  conferir(listras.includes('"papel"'), "fazendas do lote pintadas e as de reserva com listras no mapa")
  const custoBarata = await p.locator(".aba-conteudo[data-state=active] .ficha-numeros dd").nth(3).textContent()
  await p.getByRole("tab", { name: "Mais segura" }).click()
  const custoSegura = await p.locator(".aba-conteudo[data-state=active] .ficha-numeros dd").nth(3).textContent()
  conferir(custoBarata !== custoSegura && (await p.locator(".aba-conteudo[data-state=active] .faixa-pedido").count()) === 1, "cada opção com os seus números e a faixa P10 a P90")
  await p.getByRole("tab", { name: "Mais barata" }).click()

  // 4. ficha e troca
  await p.locator(".aba-conteudo[data-state=active] .tabela-lote tbody tr").first().locator("button.link").click()
  await p.locator(".fazenda-escolhida").waitFor()
  const ficha = await p.locator(".fazenda-escolhida a", { hasText: "Abrir a ficha" }).getAttribute("href")
  conferir(/^#\/fazenda\/PA-/.test(ficha ?? ""), "tocar numa fazenda mostra a ficha, com o link da ficha completa")
  await p.getByRole("button", { name: "Trocar", exact: true }).click()
  await p.getByRole("button", { name: "Trocar por esta" }).first().click()
  await p.locator(".aba-conteudo[data-state=active] .tabela-lote", { hasText: "Lote (troca)" }).waitFor({ timeout: 20000 })
  conferir(true, "trocar põe uma fazenda de reserva no lote, marcada como troca")
  await semDadoPessoal(p, "resultado do pedido")

  // 5. busca de interesse
  await p.getByRole("button", { name: "Solicitar interesse dos donos" }).click()
  await p.getByRole("heading", { name: "Busca de interesse dos donos" }).waitFor({ timeout: 20000 })
  await p.locator(".barra-meta").waitFor()
  await p.getByText(/Onda 1,/).waitFor({ timeout: 20000 })
  conferir(true, "o andamento mostra a barra da meta e as ondas de contato")
  await p.getByRole("link", { name: "Ver o grupo e reservar" }).first().waitFor({ timeout: 60000 })
  const cor = await p.evaluate(() => JSON.stringify(document.querySelector(".mapa-lote").__mapa.getPaintProperty("lote-area", "fill-color")))
  conferir(cor.startsWith('["match",["get","nivel"]'), "no andamento, cada fazenda na cor do nível de interesse do dono")
  const recusas = await p.locator(".andamento").innerText()
  conferir(/\d+ donos contatados, \d+ recusas? e \d+ sem resposta/.test(recusas), "contatados, recusas e sem resposta escritos")
  conferir(/Grupo pronto\./.test(recusas), "o aviso de grupo pronto aparece no painel")
  await semDadoPessoal(p, "andamento")

  // 6. grupo, reserva e Pix
  await p.getByRole("link", { name: "Ver o grupo e reservar" }).first().click()
  await p.waitForURL(/\/grupo$/)
  await p.getByRole("heading", { name: "Reservar este grupo" }).waitFor({ timeout: 30000 })
  const reservar = await p.locator(".reservar").innerText()
  conferir(/R\$\s?[\d.]+,\d\d/.test(reservar) && /60 dias/.test(reservar) && /abatida da conexão por hectare/.test(reservar), "o grupo mostra o valor, o prazo de exclusividade e o abatimento")
  await p.getByRole("button", { name: "Reservar este grupo" }).click()
  await p.locator(".pix-qr svg").waitFor({ timeout: 20000 })
  const copia = await p.getByLabel("Pix copia e cola").inputValue()
  conferir(copia.length > 10 && !copia.startsWith("000201"), "o Pix abre com o QR e o copia e cola (de exemplo, que não paga nada)")
  await p.getByRole("button", { name: "Simular o pagamento (exemplo)" }).click()
  await p.getByText("Pagamento recebido").waitFor({ timeout: 20000 })
  await p.getByRole("button", { name: "Ver o grupo reservado" }).click()
  await p.getByText(/Reservado até \d\d\/\d\d: faltam 5\d dias/).waitFor({ timeout: 20000 })
  conferir((await p.locator(".selo", { hasText: /Reservado até \d\d\/\d\d/ }).count()) === 1, "pago: selo Reservado até dd/mm e a contagem regressiva")
  await semDadoPessoal(p, "grupo")
  await p.goto(URL_BASE + "#/pedidos")
  await p.locator(".lista-pedidos .selo", { hasText: /Reservado até/ }).waitFor({ timeout: 20000 })
  conferir(true, "Meus pedidos mostra o status do pedido (reservado até tal dia)")

  // 7. exclusividade
  conferir(!!RESERVADA, `achou na amostra uma fazenda que o exemplo trata como reservada por outro cliente (${RESERVADA?.slice(0, 18)}…)`)
  await p.goto(URL_BASE + "#/fazenda/" + encodeURIComponent(RESERVADA))
  await p.getByText("Imóvel não encontrado.").waitFor({ timeout: 30000 })
  conferir(true, "a fazenda reservada por outro cliente não abre a ficha")
  const busca = p.locator(".topo .busca input")
  await busca.fill(RESERVADA)
  await p.getByText(/Nenhum imóvel disponível com este código/).waitFor({ timeout: 20000 })
  conferir(true, "nem aparece na busca")
  conferir(erros.length === 0, `sem erro de JavaScript${erros.length ? ": " + erros[0] : ""}`)

  // 8. celular
  const cel = await pagina({ viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true })
  await cel.p.goto(URL_BASE + "#/entrar")
  await cel.p.locator("input[type=email]").fill("compras@exemplo.com.br")
  await cel.p.getByRole("button", { name: "Mandar o link" }).click()
  await cel.p.getByRole("link", { name: "Abrir o link de entrada" }).click()
  await cel.p.waitForURL(/#\/pedidos$/, { timeout: 20000 })
  await cel.p.goto(URL_BASE + "#/pedidos/novo")
  await cel.p.getByRole("button", { name: "Ver o que existe e montar o lote" }).click()
  await cel.p.getByRole("heading", { name: "Quanto existe na nossa base" }).waitFor({ timeout: 60000 })
  await cel.p.waitForTimeout(1500)
  const largura = await cel.p.evaluate(() => document.documentElement.scrollWidth)
  conferir(largura <= 360, `celular: o pedido não passa da largura da tela (${largura} px)`)
  const mapa = await cel.p.locator(".pedido-mapa").boundingBox()
  conferir(mapa.y < 200 && mapa.height > 250, "celular: o mapa do lote em cima, o painel embaixo")
  conferir(cel.erros.length === 0, `celular: sem erro de JavaScript${cel.erros.length ? ": " + cel.erros[0] : ""}`)
} catch (e) {
  falhas++
  console.error("FALHOU", e.message.split("\n").slice(0, 4).join(" | "))
} finally {
  await navegador.close()
  await servidor.close()
}
console.log(falhas ? `\n${falhas} conferência(s) falharam.` : "\nTudo certo.")
process.exit(falhas ? 1 : 0)
