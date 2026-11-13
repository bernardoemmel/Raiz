/** Exercita o componente real com respostas explícitas da API: nenhuma fixture entra na publicação. */
import assert from "node:assert/strict"
import path from "node:path"
import { conferirPaginaAcessivel } from "./conferir-acessibilidade.mjs"

export async function conferirSensibilidade(pagina, AxeBuilder, resultado, pedido) {
  const chamadas = []
  let revisao = pedido.revisao_lote
  await pagina.route("**/api/pedidos/fixture/sensibilidade", (rota) => {
    assert.equal(rota.request().headers().authorization, "Bearer sessao-fixture-cliente")
    assert.equal(rota.request().headers()["if-match"], `"${revisao}"`)
    const parametros = rota.request().postDataJSON()
    chamadas.push(parametros)
    return rota.fulfill({ json: {
      estado: parametros.pessimista ? "indisponivel" : "disponivel", exemplo: false, parametros,
      fonte: "API sintética do teste", atualizado_em: "2026-11-12T12:00:00Z", modelo_versao: "fixture-sensibilidade-v1", revisao_lote: revisao,
      aviso: parametros.pessimista ? "O motor ainda não publicou estas premissas em conjunto." : "Resultado sintético do teste de sensibilidade.",
      opcoes: parametros.pessimista ? [] : ["barata", "segura", "compacta"].map((id, i) => ({
        id, creditos: { p10: 700_000 + i * 10_000, p50: 1_000_000 + i * 10_000, p90: 1_200_000 + i * 10_000 },
        hectares: 4_000, fazendas: 40 + i, vpl_usd: parametros.preco_credito_usd * 1_000, tir_projeto: i === 0 ? null : 0.1,
        alcanca_meta: true,
      })),
    } })
  })
  const secao = pagina.locator(".sensibilidade-lote")
  await secao.getByRole("heading", { name: "Sensibilidade dos três lotes" }).waitFor()
  await secao.getByRole("button", { name: "Consultar os três lotes", exact: true }).click()
  await secao.getByText("Resultado sintético do teste de sensibilidade.", { exact: true }).waitFor()
  assert.equal(await secao.locator("thead th").count(), 4)
  assert.equal(await secao.getByText("Não definida", { exact: true }).count(), 1, "TIR ausente não pode virar zero ou -100%.")
  assert.match(await secao.innerText(), /fixture-sensibilidade-v1/)
  await secao.getByLabel("Preço do crédito (US$)", { exact: true }).fill("70")
  assert.equal(await secao.locator("table").count(), 0, "Resultados anteriores devem sumir ao alterar premissas.")
  await secao.getByRole("button", { name: "Consultar os três lotes", exact: true }).click()
  await secao.getByText("Premissas aplicadas:", { exact: false }).waitFor()
  assert.equal(chamadas.at(-1).preco_credito_usd, 70)
  await secao.getByLabel("Reserva contra reversão (%)", { exact: true }).fill("19")
  await secao.getByRole("button", { name: "Consultar os três lotes", exact: true }).click()
  assert.equal(chamadas.length, 2, "Valor abaixo do piso não pode chegar ao servidor.")
  await secao.getByLabel("Reserva contra reversão (%)", { exact: true }).fill("35")
  await secao.getByLabel("Taxa de desconto (% ao ano)", { exact: true }).fill("12.5")
  await secao.getByLabel("Cenário pessimista", { exact: true }).focus()
  await pagina.keyboard.press("Space")
  await secao.getByRole("button", { name: "Consultar os três lotes", exact: true }).click()
  await secao.getByText("O motor ainda não publicou estas premissas em conjunto.", { exact: true }).waitFor()
  assert.deepEqual(chamadas.at(-1), { preco_credito_usd: 70, reserva_reversao: 0.35, taxa_desconto: 0.125, pessimista: true })
  assert.equal(await secao.locator("table").count(), 0, "Ausência de grade não apresenta resultados antigos.")
  await secao.getByRole("button", { name: "Restaurar premissas iniciais", exact: true }).click()
  await secao.getByText("Resultado sintético do teste de sensibilidade.", { exact: true }).waitFor()
  await pagina.setViewportSize({ width: 360, height: 800 })
  await secao.scrollIntoViewIfNeeded()
  assert(await pagina.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Sensibilidade ultrapassou360px.")
  await conferirPaginaAcessivel(pagina, AxeBuilder, "sensibilidade-360", resultado)
  await pagina.screenshot({ path: path.join(resultado, "sensibilidade-360.png"), fullPage: true })
  await pagina.setViewportSize({ width: 1440, height: 960 })
  // A mesma conta altera o lote enquanto o cenário anterior ainda está em voo.
  let avisarInicio, liberar, avisarFim
  const inicio = new Promise((r) => { avisarInicio = r })
  const espera = new Promise((r) => { liberar = r })
  const fim = new Promise((r) => { avisarFim = r })
  const revisaoAntiga = revisao
  await pagina.route("**/api/pedidos/fixture/sensibilidade", async (rota) => {
    const parametros = rota.request().postDataJSON()
    avisarInicio()
    await espera
    await rota.fulfill({ json: {
      estado: "indisponivel", exemplo: false, parametros, revisao_lote: revisaoAntiga,
      fonte: "API sintética do teste", atualizado_em: null, modelo_versao: null, opcoes: [],
      aviso: "Resposta antiga não pode aparecer depois da remoção.",
    } })
    avisarFim()
  }, { times: 1 })
  await secao.getByRole("button", { name: "Consultar os três lotes", exact: true }).click()
  await inicio
  await pagina.route("**/api/pedidos/fixture/lote", (rota) => {
    assert.equal(rota.request().postDataJSON().acao, "tirar")
    revisao = "b".repeat(64)
    const opcoes = pedido.opcoes.map((o, i) => i === 0 ? { ...o, itens: [], fazendas: 0 } : o)
    return rota.fulfill({ json: { ...pedido, revisao_lote: revisao, opcoes } })
  })
  await pagina.locator(".tabela-lote button").first().click()
  await pagina.getByRole("button", { name: "Tirar do lote", exact: true }).click()
  await secao.getByText("A consulta depende da grade de cenários publicada pelo motor.", { exact: false }).waitFor()
  assert.equal(await secao.locator("table").count(), 0)
  liberar()
  await fim
  await secao.getByRole("button", { name: "Consultar os três lotes", exact: true }).click()
  await secao.getByText("Resultado sintético do teste de sensibilidade.", { exact: true }).waitFor()
  assert.equal(await secao.getByText("Resposta antiga não pode aparecer depois da remoção.", { exact: true }).count(), 0)
  // Reabre a fixture inicial para os demais testes do mapa, sem mudar o cenário deles.
  revisao = pedido.revisao_lote
  await pagina.reload()
  await pagina.getByRole("heading", { name: "Sensibilidade dos três lotes", exact: true }).waitFor()
}
