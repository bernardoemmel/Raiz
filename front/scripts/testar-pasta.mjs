#!/usr/bin/env node
/** Pasta privada em desktop/celular, teclado, pendências, exportação e troca de sessão. */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { conferirPaginaAcessivel } from './conferir-acessibilidade.mjs'
const globo = fileURLToPath(new URL('../globo/', import.meta.url))
const require = createRequire(path.join(globo, 'package.json'))
const { chromium } = require('playwright')
const { default: AxeBuilder } = await import(pathToFileURL(require.resolve('@axe-core/playwright')).href)
const { createServer } = await import(pathToFileURL(require.resolve('vite')).href)
process.env.VITE_RAIZ_API = '/teste-api'
const servidor = await createServer({ root: globo, configFile: path.join(globo, 'vite.config.ts'), server: { port: 0 }, logLevel: 'error' })
await servidor.listen()
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || (fs.existsSync('/usr/bin/chromium') ? '/usr/bin/chromium' : undefined), args: ['--no-sandbox'] })
const saida = process.env.RAIZ_EVIDENCIAS_PASTA || '/tmp/raiz-pasta-fiador'
fs.mkdirSync(saida, { recursive: true })
const car = 'PA-1504950-' + 'A'.repeat(32), pedido = '00000000-0000-4000-8000-000000000001'
const fonte = [{ documento_id: 'doc-sintetico', localizador: 'pagina:1', data_referencia: '2026-11-01' }]
const medida = (valor, unidade = 'ha') => ({ valor, unidade, natureza: 'estimado', fontes: fonte })
const periodo = { inicio: '2027-01-01', fim: '2052-01-01' }
const pasta = { pasta_id: 'pasta-teste', versao_id: 'versao-teste', numero: 1, anterior_id: null, tipo_alteracao: 'inclusao', motivo: 'entrada_conferida', assinatura: 'a'.repeat(64), registrada_em: '2026-11-13T01:00:00Z',
  dados: { pedido_id: pedido, opcao: 'segura', data_corte: '2026-11-01', documentos: [{ id: 'doc-sintetico', referencia: 'DOC-' + 'A'.repeat(12), tipo: 'garantia', estado: 'conferido', valido_ate: '2027-01-01', sem_vencimento: false }],
    imoveis: [{ codigo_car: car, area_elegivel: medida('0.25'), titulo: { nivel: 'conferencia_concluida', situacao: 'conferida', fontes: fonte }, garantia: { situacao: 'conferida', fontes: fonte },
      creditos: [{ metodo: 'regeneracao_assistida', area: medida('0.25'), p10: medida('10', 'tCO2e'), p50: medida('20', 'tCO2e'), p90: medida('30', 'tCO2e'), periodo, modelo_versao: 'teste', fontes: fonte }],
      preco: { valor: '24.90', moeda: 'BRL', unidade: 'tCO2e', periodo, natureza: 'estimado', fontes: fonte } }] },
  validacao: { pronto: true, regra_versao: 'teste', conferido_em: '2026-11-13', falhas: [], campos: [{ campo: 'imoveis/0/garantia', fontes: fonte }], documentos: [{ id: 'doc-sintetico', tipo: 'garantia', estado: 'conferido', valido_ate: '2027-01-01' }] }, previsoes: [] }
let pendente = false, exportacoes = 0
const chamadas = []
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
  await ctx.addInitScript(() => localStorage.setItem('raiz.sessao', JSON.stringify({ token: 'cliente-a', email: 'teste@raiz.invalid' })))
  await ctx.route('**/teste-api/**', async (route) => {
    const req = route.request(), url = new URL(req.url())
    chamadas.push({ url: url.pathname, token: req.headers().authorization, method: req.method() })
    if (req.headers().authorization !== 'Bearer cliente-a') return route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Pasta não encontrada.' }) })
    if (url.pathname.endsWith('/exportar')) { exportacoes++; return route.fulfill({ contentType: 'application/zip', body: 'ZIP-SINTETICO', headers: { 'Content-Disposition': 'attachment; filename="pasta.zip"' } }) }
    const p = structuredClone(pasta)
    if (pendente) { p.validacao.pronto = false; p.validacao.falhas = [{ codigo: 'garantia_pendente', campo: 'imoveis/0/garantia', mensagem: 'A garantia precisa estar conferida.', documento_id: 'doc-sintetico' }] }
    const body = url.pathname.endsWith('/historico') ? { versoes: [{ id: 'versao-teste', numero: 1, tipo: 'inclusao', registrada_em: '2026-11-13' }] } : p
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  const page = await ctx.newPage(), erros = []
  page.on('pageerror', (e) => erros.push(e.message))
  page.on('console', (m) => { if (m.type() === 'error') erros.push({ texto: m.text(), url: m.location().url }) })
  const url = servidor.resolvedUrls.local[0] + '#/pedidos/' + pedido + '/pasta'
  await page.goto(url)
  await page.getByRole('heading', { name: 'Conferência concluída' }).waitFor()
  await page.locator('.tabulator-row').first().waitFor()
  const cabecalho = page.getByRole('columnheader', { name: 'CAR', exact: true })
  await cabecalho.focus(); await page.keyboard.press('Enter')
  assert.equal(await cabecalho.getAttribute('aria-sort'), 'ascending')
  await conferirPaginaAcessivel(page, AxeBuilder, 'pasta-desktop', saida)
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Baixar banco + comprador', exact: true }).click()
  await download; assert.equal(exportacoes, 1)
  await page.setViewportSize({ width: 360, height: 800 })
  await conferirPaginaAcessivel(page, AxeBuilder, 'pasta-celular', saida)
  pendente = true
  await page.getByLabel('Opção do lote').selectOption('barata')
  await page.getByRole('heading', { name: 'Pasta com pendências' }).waitFor()
  assert(await page.getByRole('button', { name: 'Baixar banco + comprador', exact: true }).isDisabled())
  await conferirPaginaAcessivel(page, AxeBuilder, 'pasta-pendente', saida)
  await page.evaluate(() => { localStorage.setItem('raiz.sessao', JSON.stringify({ token: 'cliente-b', email: 'teste-b@raiz.invalid' })); window.dispatchEvent(new Event('raiz-sessao')) })
  await page.getByRole('alert').filter({ hasText: 'Pasta não encontrada.' }).waitFor()
  assert.equal(await page.locator('.tabulator-row').count(), 0)
  assert.equal(await page.getByText(car, { exact: true }).count(), 0)
  assert.equal(exportacoes, 1)
  assert(chamadas.every((c) => c.method === 'GET' && c.token))
  assert.equal(erros.length, 2) // Duas recusas 404 esperadas da conta sem acesso.
  assert(erros.every((e) => e.texto.includes('404 (Not Found)') && e.url.includes('/teste-api/prospeccao/pastas/')))
  fs.writeFileSync(path.join(saida, 'resultado.json'), JSON.stringify({ aprovado: true, exportacoes, desktop: 1440, celular: 360, contatos: 0 }, null, 2))
  console.log('Pasta: desktop, celular, teclado, axe, pendência e troca de sessão passaram.')
} finally { await browser.close(); await servidor.close() }
