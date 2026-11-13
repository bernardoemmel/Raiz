/** Regressão de identidade: o resumo chega depois da telemetria, sem desmontar as 27 UFs nem perder foco. */
import assert from "node:assert/strict"

const UFS = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"]
const INICIO = Date.parse("2026-11-13T12:05:00Z")

/** No V2 a telemetria fica em Sobre os dados; abrir o diálogo não recria suas linhas. */
async function abrirDados(pagina) {
  const dialogo = pagina.locator("dialog.dados-mapa-v2")
  await pagina.getByRole("button", { name: "Sobre os dados", exact: true }).click()
  await dialogo.waitFor({ state: "visible" })
  assert(await dialogo.evaluate(no => no.open), "Sobre os dados abre um diálogo acessível no mapa.")
  assert.equal(await pagina.locator(".painel-lateral").count(), 0, "A entrada V2 não restaura a coluna lateral.")
}

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
    await abrirDados(pagina)
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

/** Respostas independentes não empurram a telemetria já pintada para fora da tela. */
export async function conferirEstabilidadePainelBrasil(navegador, base) {
  const resultados = []
  for (const consulta of ["resumo", "cobertura"]) {
    const contexto = await navegador.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" })
    const pagina = await contexto.newPage()
    let liberar
    const retida = new Promise(resolve => { liberar = resolve })
    try {
      await pagina.addInitScript(() => {
        window.__deslocamentosPainel = []
        new PerformanceObserver(lista => {
          for (const entrada of lista.getEntries()) {
            if (!entrada.hadRecentInput) window.__deslocamentosPainel.push({ valor: entrada.value, inicio: entrada.startTime })
          }
        }).observe({ type: "layout-shift", buffered: true })
      })
      await pagina.route(consulta === "resumo" ? "**/amostra/resumo_PA.csv.gz" : "**/geo/indice.json", async rota => {
        await retida
        await rota.continue()
      })
      await pagina.route("**/amostra/processamento.json*", rota => rota.fulfill({ json: telemetria(1) }))
      await pagina.goto(base, { waitUntil: "domcontentloaded" })
      await abrirDados(pagina)
      await pagina.waitForFunction(() => document.querySelectorAll(".processamento-estado").length === 27)
      if (consulta === "resumo") await pagina.getByText("Lendo os municípios processados", { exact: true }).waitFor()
      else await pagina.locator(".numeros").waitFor()
      await pagina.evaluate(() => document.fonts.ready)
      await pagina.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      const antes = await pagina.evaluateHandle(() => ({
        inicio: performance.now(),
        painel: document.querySelector(".processamento-estados"),
        cobertura: document.querySelector('[aria-labelledby="cobertura-titulo"]'),
        linhas: [...document.querySelectorAll(".processamento-estado")],
        y: document.querySelector(".processamento-estados").getBoundingClientRect().y,
        coberturaY: document.querySelector('[aria-labelledby="cobertura-titulo"]').getBoundingClientRect().y,
        scrollTop: document.querySelector("dialog.dados-mapa-v2").scrollTop,
      }))
      liberar()
      await pagina.getByRole("heading", { name: "Dados disponíveis no mapa", exact: true }).waitFor()
      await pagina.locator(".cobertura-carregando").waitFor({ state: "detached" })
      await pagina.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      const depois = await pagina.evaluate(antes => ({
        cls: window.__deslocamentosPainel.filter(d => d.inicio >= antes.inicio).reduce((soma, d) => soma + d.valor, 0),
        deslocamento: Math.abs(document.querySelector(".processamento-estados").getBoundingClientRect().y - antes.y),
        coberturaDeslocamento: Math.abs(document.querySelector('[aria-labelledby="cobertura-titulo"]').getBoundingClientRect().y - antes.coberturaY),
        scroll: document.querySelector("dialog.dados-mapa-v2").scrollTop - antes.scrollTop,
        painel: document.querySelector(".processamento-estados") === antes.painel,
        cobertura: document.querySelector('[aria-labelledby="cobertura-titulo"]') === antes.cobertura,
        linhas: antes.linhas.every((linha, i) => linha === document.querySelectorAll(".processamento-estado")[i]),
        reservas: document.querySelectorAll(".resumo-brasil-carregando, .cobertura-carregando").length,
      }), antes)
      assert(depois.cls <= 0.1, `${consulta} tardio deslocou o painel: CLS ${depois.cls}.`)
      assert(depois.deslocamento < 100, `${consulta} tardio empurrou a telemetria ${depois.deslocamento}px.`)
      assert(depois.coberturaDeslocamento < 100, `${consulta} tardio empurrou a cobertura ${depois.coberturaDeslocamento}px.`)
      assert.equal(depois.scroll, 0, "A consulta não desloca a rolagem do painel.")
      assert(depois.painel && depois.linhas, "A chegada dos dados preserva o painel e as 27 linhas.")
      assert(depois.cobertura, "A cobertura mantém seu nó quando o resumo independente chega.")
      assert.equal(depois.reservas, 0, "A reserva temporária termina com a consulta; não altera o painel pronto.")
      resultados.push({ consulta, ...depois })
    } finally {
      liberar()
      await contexto.close()
    }
  }
  return resultados
}
