import { execFileSync } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath } from "node:url"

const repo = fileURLToPath(new URL("../..", import.meta.url))
const { test, expect } = createRequire(path.join(repo, "front/globo/package.json"))("@playwright/test")
const API = "http://127.0.0.1:8765"

function cnpjSintetico() {
  // Documento calculado apenas para o teste; nenhum CNPJ completo entra no repositório.
  let base = "12" + "0".repeat(9) + "1"
  for (const pesos of [[5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]]) {
    const resto = [...base].reduce((soma, digito, i) => soma + Number(digito) * pesos[i], 0) % 11
    base += String(resto < 2 ? 0 : 11 - resto)
  }
  return base
}

async function confirmarPixLocal(request, cobranca) {
  expect(cobranca.modo_teste).toBe(true)
  const link = new URL(cobranca.link_para_uma_pessoa, API)
  expect(link.origin).toBe(API)
  const pagina = await request.get(link.href)
  expect(pagina.ok()).toBeTruthy()
  const codigo = (await pagina.text()).match(/RAIZ-TESTE-PIX-(teste_[a-f0-9]+)-NAO-E-CODIGO-DE-BANCO/)
  expect(Boolean(codigo)).toBe(true)
  const negado = await request.post(`${API}/pagamentos/teste/${codigo[1]}/pagar`)
  expect(negado.status()).toBe(401)
  const pago = await request.post(`${API}/pagamentos/teste/${codigo[1]}/pagar`, {
    headers: { Authorization: `Bearer ${process.env.RAIZ_API_TOKEN}` },
  })
  expect(pago.ok()).toBeTruthy()
  expect(await pago.json()).toEqual({ reserva: "paga" })
}

async function lerComLimite(page, caminhos, abrir) {
  const aguardar = () => Promise.all(caminhos.map((caminho) => page.waitForResponse(
    (r) => r.url() === `${API}/v1/${caminho}` && r.request().method() === "GET",
  )))
  const inicial = aguardar()
  await abrir()
  let respostas = await inicial
  const limitadas = respostas.filter((r) => r.status() === 429)
  if (limitadas.length) {
    // A automação comprime etapas humanas; continua respeitando o limite real por empresa.
    const esperas = limitadas.map((r) => Number(r.headers()["retry-after"]))
    for (const espera of esperas) {
      expect(espera).toBeGreaterThan(0)
      expect(espera).toBeLessThanOrEqual(60)
    }
    await page.waitForTimeout(Math.max(...esperas) * 1000)
    const repetidas = aguardar()
    await page.reload()
    respostas = await repetidas
  }
  for (const resposta of respostas) expect(resposta.status()).toBe(200)
}

test("login e conta paga → milhão no Pará → contato bloqueado na tela → reserva Pix no servidor de teste", async ({ page, request }) => {
  const erros = []
  const contatosPelaTela = []
  expect(existsSync(path.join(process.env.RAIZ_E2E_ESTADO, "pronto"))).toBe(true)
  page.on("pageerror", (erro) => erros.push(erro.message))
  page.on("request", (r) => { if (r.url().endsWith("/solicitar-interesse")) contatosPelaTela.push(r.url()) })
  await page.goto("/#/pedidos")
  await expect(page.getByRole("heading", { name: "Entrar na Raíz" })).toBeVisible()
  await page.getByRole("textbox", { name: "E-mail" }).fill("compras@cliente.example")
  const envio = page.waitForResponse((r) => r.url() === `${API}/entrar` && r.request().method() === "POST")
  await page.getByRole("button", { name: "Mandar o link" }).click()
  const respostaEntrada = await (await envio).json()
  expect(Object.keys(respostaEntrada)).toEqual(["enviado"])
  expect(respostaEntrada.enviado).toBe(true)
  await expect(page.getByText("Mandamos um link para")).toBeVisible()
  await expect(page.getByRole("link", { name: "Abrir o link de entrada" })).toHaveCount(0)
  await expect.poll(() => existsSync(path.join(process.env.RAIZ_E2E_ESTADO, "entrada.json"))).toBe(true)
  const entrega = JSON.parse(readFileSync(path.join(process.env.RAIZ_E2E_ESTADO, "entrada.json"), "utf8"))
  expect(entrega.email).toBe("compras@cliente.example")
  await page.goto(entrega.link)
  await expect(page.getByRole("heading", { name: "Meus pedidos" })).toBeVisible()
  const sessao = await page.evaluate(() => JSON.parse(localStorage.getItem("raiz.sessao")))
  const credencial = { Authorization: `Bearer ${sessao.token}` }
  // A sessão identifica a pessoa, mas a empresa ainda precisa abrir a conta paga.
  const abertura = await request.post(`${API}/v1/conta`, {
    headers: credencial, data: { cnpj: cnpjSintetico(), aceito_termos: true },
  })
  expect(abertura.ok()).toBeTruthy()
  expect(await abertura.json()).toMatchObject({ testes_restantes: 3, saldo_rs: 0, liberada: false })
  await page.reload()
  await expect(page.getByText("Nenhum pedido ainda.")).toBeVisible()
  const reutilizado = await request.post(`${API}/entrar/confirmar`, { data: { token: entrega.link.split("/").at(-1) } })
  expect(reutilizado.status()).toBe(401)

  await page.getByRole("link", { name: "Novo pedido" }).first().click()
  await expect(page.getByLabel("Quantidade (créditos)")).toHaveValue("1.000.000")
  await expect(page.getByRole("list", { name: "Lugares escolhidos" })).toContainText("Pará")
  await expect(page.getByLabel("Estados (sem nenhum: todos)").getByRole("option", { name: "Pará", exact: true })).toBeDisabled()
  // O alias antigo deve passar pela política paga, mesmo com sessão humana e três créditos de teste.
  const alias = page.waitForResponse((r) => r.url() === `${API}/pedidos` && r.request().method() === "POST")
  const bloqueada = page.waitForResponse((r) => r.url() === `${API}/v1/pedidos` && r.request().method() === "POST")
  await page.getByRole("button", { name: "Ver o que existe e montar o lote" }).click()
  expect((await alias).status()).toBe(307)
  expect((await bloqueada).status()).toBe(403)
  await expect(page.getByText("403 em pedidos")).toBeVisible()
  const contrato = await request.post(`${API}/v1/conta/contrato`, { headers: credencial })
  expect(contrato.ok()).toBeTruthy()
  const sinal = await request.post(`${API}/v1/conta/sinal`, { headers: credencial })
  expect(sinal.ok()).toBeTruthy()
  await confirmarPixLocal(request, await sinal.json())
  const recarga = await request.post(`${API}/v1/conta/recarga?valor_rs=5000`, { headers: credencial })
  expect(recarga.ok()).toBeTruthy()
  await confirmarPixLocal(request, await recarga.json())

  const criada = page.waitForResponse((r) => r.url() === `${API}/v1/pedidos` && r.request().method() === "POST")
  await page.getByRole("button", { name: "Ver o que existe e montar o lote" }).click()
  const resposta = await criada
  expect(resposta.ok()).toBeTruthy()
  const pedido = await resposta.json()
  expect(pedido.campos.meta.valor).toBe(1_000_000)
  expect(pedido.campos.onde.ufs).toEqual(["PA"])
  expect(pedido.base.alcanca_meta).toBe(true)
  expect(pedido.opcoes).toHaveLength(3)
  await expect(page.getByRole("heading", { name: "Quanto existe na nossa base" })).toBeVisible()
  await expect(page.getByRole("tab")).toHaveText(["Mais barata", "Mais segura", "Mais compacta"])
  for (const nome of ["Mais barata", "Mais segura", "Mais compacta"]) {
    await page.getByRole("tab", { name: nome }).click()
    await expect(page.locator(".aba-conteudo[data-state=active] .tabela-lote tbody tr").first()).toBeVisible()
  }
  // Nenhum valor pessoal ou campo do dono é exposto pelas respostas do pedido.
  expect(JSON.stringify(pedido)).not.toMatch(/"(?:cpf|cnpj|nome_dono|nome_proprietario|telefone|email)"/i)

  await expect(page.getByRole("heading", { name: "Contato somente na fase final" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Solicitar interesse dos donos" })).toBeDisabled()
  expect(contatosPelaTela).toEqual([])
  // A tela atual não inicia contato. As etapas posteriores continuam cobertas pela API real deste banco
  // descartável, sem envio externo: servidor.py substitui o correio e as respostas e só aceita banco local _e2e.
  const tokenSessao = await page.evaluate(() => JSON.parse(localStorage.getItem("raiz.sessao") ?? "null")?.token)
  if (!tokenSessao) throw new Error("A sessão local do cliente não foi criada.")
  const solicitacao = await request.post(`${API}/pedidos/${pedido.id}/solicitar-interesse`, {
    headers: { Authorization: `Bearer ${tokenSessao}` }, data: { opcao: "compacta" },
  })
  expect(solicitacao.ok()).toBeTruthy()
  expect((await solicitacao.json()).status).toBe("buscando_interesse")
  await page.reload()
  await expect(page.getByRole("heading", { name: "Busca de interesse dos donos" })).toBeVisible()
  await expect(page.locator(".barra-meta")).toBeVisible()
  execFileSync("uv", ["run", "--frozen", "python", "-m", "testes.e2e.servidor", "--interesses", pedido.id], {
    cwd: repo, env: process.env, stdio: "pipe", timeout: 90_000,
  })
  await expect(page.getByRole("link", { name: "Ver o grupo e reservar" }).first()).toBeVisible({ timeout: 30_000 })
  await page.getByRole("link", { name: "Ver o grupo e reservar" }).first().click()
  await expect(page.getByRole("heading", { name: "Reservar este grupo" })).toBeVisible()
  await page.getByRole("button", { name: "Reservar este grupo" }).click()
  await expect(page.getByRole("img", { name: "Código QR do Pix" })).toBeVisible()
  const pix = await page.getByLabel("Pix copia e cola").inputValue()
  expect(pix).toMatch(/^RAIZ-TESTE-PIX-teste_[a-f0-9]+-NAO-E-CODIGO-DE-BANCO$/)
  await expect(page.getByText("Pix de teste: este código não paga nada.")).toBeVisible()
  await expect(page.getByRole("button", { name: "Simular o pagamento (exemplo)" })).toHaveCount(0)
  await expect(page.getByText(/O código vale até/)).toHaveCount(0)
  const externo = pix.match(/teste_[a-f0-9]+/)[0]
  const negado = await request.post(`${API}/pagamentos/teste/${externo}/pagar`)
  expect(negado.status()).toBe(401)
  const pago = await request.post(`${API}/pagamentos/teste/${externo}/pagar`, {
    headers: { Authorization: `Bearer ${process.env.RAIZ_API_TOKEN}` },
  })
  expect(pago.ok()).toBeTruthy()
  expect(await pago.json()).toEqual({ reserva: "ativa" })
  await expect(page.getByText(/Pagamento recebido\./)).toBeVisible()
  await page.getByRole("button", { name: "Ver o grupo reservado" }).click()
  await expect(page.getByRole("heading", { name: "Grupo reservado" })).toBeVisible()
  await expect(page.getByRole("timer")).toContainText("Reservado até")
  await lerComLimite(page, [`pedidos/${pedido.id}`, `pedidos/${pedido.id}/andamento`, `pedidos/${pedido.id}/reserva`], () => page.reload())
  await expect(page.getByRole("heading", { name: "Grupo reservado" })).toBeVisible()
  await lerComLimite(page, ["pedidos"], () => page.goto("/#/pedidos"))
  await expect(page.locator(".lista-pedidos .selo", { hasText: /Reservado até/ })).toBeVisible()
  expect(contatosPelaTela).toEqual([])
  expect(erros).toEqual([])
})
