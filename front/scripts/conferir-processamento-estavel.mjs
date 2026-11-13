/** Regressão de identidade: o resumo chega depois da telemetria, sem desmontar as 27 UFs nem perder foco. */
import assert from "node:assert/strict"

const UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]
const INICIO = Date.parse("2026-11-13T12:05:00Z")

function telemetria(rodada) {
  const observado = INICIO + (rodada > 1 ? 30_000 : 0)
  return { versao: 1, gerado_em: new Date(observado).toISOString(), estados: UFS.map(uf => ({
    uf, escopo: "uf", unidade: null, municipios_total: 100,
    municipios: { prontos: rodada > 1 ? 11 : 10, em_execucao: 2, com_erro: 0, pendentes: rodada > 1 ? 87 : 88, desconhecidos: 0 },
    observado_em: new Date(observado).toISOString(), ultima_mudanca_em: new Date(observado).toISOString(),
    valido_ate: new Date(observado + 20_000).toISOString(), situacao: "atual",
  })) }
}

export async function conferirProcessamentoEstavel(navegador, base) {
  const contexto = await navegador.newContext({ viewport: { width: 360, height: 800 }, reducedMotion: "reduce" })
  const pagina = await contexto.newPage()
  const erros = []
  pagina.on("pageerror", erro => erros.push(erro.message))
  pagina.on("response", resposta => { if (resposta.status() >= 400) erros.push(`${resposta.status()} ${resposta.url()}`) })
  let liberarResumo
  const resumoRetido = new Promise(resolve => { liberarResumo = resolve })
  const resumoSolicitado = pagina.waitForRequest("**/amostra/resumo_PA.csv.gz")
  let rodadas = 0
  try {
    // Relógio e ordem de respostas controlados só nesta regressão, nunca em auditoria Lighthouse.
    await pagina.clock.install({ time: new Date(INICIO) })
    await pagina.route("**/amostra/resumo_PA.csv.gz", async rota => {
      await resumoRetido
      await rota.continue()
    })
    await pagina.route("**/amostra/processamento.json*", rota => rota.fulfill({ json: telemetria(++rodadas) }))
    await pagina.goto(base, { waitUntil: "domcontentloaded" })
    await resumoSolicitado
    await pagina.waitForFunction(() => document.querySelectorAll(".processamento-estado").length === 27)
    await pagina.getByText("Lendo os municípios processados", { exact: true }).waitFor()
    const identidade = await pagina.evaluateHandle(() => ({
      painel: document.querySelector(".processamento-estados"),
      linhas: [...document.querySelectorAll(".processamento-estado")],
      links: [...document.querySelectorAll(".processamento-estado a")],
    }))
    const para = pagina.locator(".processamento-estado").filter({ has: pagina.getByRole("link", { name: "Pará", exact: true }) })
    const outrasContagens = para.locator("summary").filter({ hasText: "Outras contagens de municípios" })
    await outrasContagens.focus()
    await pagina.keyboard.press("Enter")
    assert(await para.locator("details").evaluate(elemento => elemento.open), "Teclado abre as contagens da UF.")
    liberarResumo()
    await pagina.getByRole("heading", { name: "Dados disponíveis no mapa", exact: true }).waitFor()
    const preservado = await pagina.evaluate(antes => ({
      painel: antes.painel === document.querySelector(".processamento-estados"),
      linhas: antes.linhas.every((no, i) => no === document.querySelectorAll(".processamento-estado")[i]),
      links: antes.links.every((no, i) => no === document.querySelectorAll(".processamento-estado a")[i]),
      foco: document.activeElement?.textContent === "Outras contagens de municípios",
    }), identidade)
    assert.deepEqual(preservado, { painel: true, linhas: true, links: true, foco: true }, "Resumo municipal preserva os nós das 27 UFs e o foco do teclado.")
    assert(await para.locator("details").evaluate(elemento => elemento.open), "O detalhe aberto não deve recolher quando chega o resumo.")
    assert.equal(await pagina.locator(".processamento-estado").count(), 27)
    assert.equal(await para.locator(".processamento-contagens dd").nth(1).innerText(), "2")
    // A identidade não congela os dados: observação vencida oculta o agora e a próxima rodada atualiza a contagem.
    await pagina.clock.fastForward(25_000)
    await pagina.waitForFunction(() => [...document.querySelectorAll(".processamento-situacao")].every(no => no.textContent === "Sem atualização recente"))
    assert.equal(await para.locator(".processamento-contagens dd").nth(1).innerText(), "Não informado")
    await pagina.clock.fastForward(10_000)
    await pagina.waitForFunction(() => [...document.querySelectorAll(".processamento-contagens")].every(no => no.querySelector("dd")?.textContent === "11"))
    assert.equal(await para.locator(".processamento-contagens dd").nth(1).innerText(), "2")
    assert.equal(await pagina.locator(".processamento-estado").count(), 27)
    assert.equal(await pagina.evaluate(antes => antes.linhas.every((no, i) => no === document.querySelectorAll(".processamento-estado")[i]), identidade), true)
    assert.deepEqual(erros, [], "A estabilidade da telemetria não introduz erro HTTP ou JavaScript.")
    return { ufs: 27, preservado, detalhe_aberto: true, expiracao: true, atualizacao: true, rodadas, erros }
  } finally {
    liberarResumo()
    await contexto.close()
  }
}
