/**
 * Pedido de lote (cena-alvo): a resposta de exemplo, no mesmo formato da API, com fazendas aptas de verdade de São
 * Félix do Xingu e Cumaru do Norte (as que têm contorno em front/geo). Confere a base, as 3 opções, tirar e trocar, a
 * busca de interesse em ondas, a reserva, a exclusividade e que nada pessoal do dono aparece.
 */

import fs from "node:fs"
import path from "node:path"
import { beforeAll, describe, expect, it } from "vitest"
import { lerCsv } from "../dados/csv"
import { complementosDe, juntarComplementos } from "../dados/complementos"
import type { FonteDeDados } from "../dados/fonte"
import { lerImovel } from "../dados/funil"
import type { Geo, Imovel } from "../dados/tipos"
import { semReservadasPorOutros } from "../pedidos/exclusividade"
import {
  CAMPOS_PADRAO,
  candidatoDe,
  cobrancaDe,
  grupoDe,
  montarPedido,
  mudarOnda,
  PREMISSAS,
  reservadaPorOutro,
  simularAndamento,
  type Candidato,
  type PedidoGuardado,
} from "../pedidos/exemplo"
import { fontePedidosExemplo } from "../pedidos/fonte-pedidos"
import { fmtFaixaMeta, fmtMeta, tituloDoPedido } from "../pedidos/texto"
import type { CamposPedido, Pedido } from "../pedidos/tipos"
import { mascarar } from "../privacidade"
import { pontoDentro } from "../rotulos-mapa"
import { lerRota } from "../../globo/src/rota"

const AMOSTRA = path.resolve(__dirname, "../../../dados/amostra")
const GEO = path.resolve(__dirname, "../../geo")
const COM_CONTORNO = ["1507300", "1504950"]
const temGeo = COM_CONTORNO.every((c) => fs.existsSync(path.join(GEO, `imoveis_${c}.geojson`)))

const ler = (a: string) => lerCsv(fs.readFileSync(path.join(AMOSTRA, a), "utf8")).linhas
const imoveisDe = (cod: string): Imovel[] => {
  const { porImovel } = juntarComplementos(complementosDe(fs.readdirSync(AMOSTRA), cod).map((arquivo) => ({ arquivo, linhas: ler(arquivo) })))
  return ler(`imoveis_${cod}.csv`).map((l) => lerImovel(l, porImovel.get(l.cod_imovel)))
}
const geoDe = (cod: string): Geo => JSON.parse(fs.readFileSync(path.join(GEO, `imoveis_${cod}.geojson`), "utf8"))

let cands: Candidato[] = []
const AGORA = new Date("2026-11-12T12:00:00Z")
const guardado = (campos: CamposPedido = CAMPOS_PADRAO, extra: Partial<PedidoGuardado> = {}): PedidoGuardado => ({
  id: "teste",
  criado_em: AGORA.toISOString(),
  campos,
  edicoes: {},
  solicitado: null,
  reserva: null,
  dados_de: {},
  ...extra,
})

beforeAll(() => {
  if (!temGeo) return
  for (const cod of COM_CONTORNO) {
    const centro = new Map(geoDe(cod).features.map((f) => [String(f.properties.cod_imovel), pontoDentro(f.geometry)]))
    for (const i of imoveisDe(cod)) {
      const c = candidatoDe(i, centro.get(i.cod_imovel) ?? null)
      if (c) cands.push(c)
    }
  }
})

/** nenhuma chave nem valor de dado pessoal do dono em lugar nenhum da resposta */
function semDadoPessoal(obj: unknown) {
  const texto = JSON.stringify(obj)
  const chaves = [...texto.matchAll(/"([^"]+)":/g)].map((m) => m[1])
  // "max_donos" é campo do pedido (quantos donos no lote), não dado de dono
  expect(chaves.filter((k) => /cpf|cnpj|nome|telefone|celular|whats|e_?mail|propriet|^dono|endereco/i.test(k))).toEqual([])
  expect(mascarar(texto)).toBe(texto)
}

describe.skipIf(!temGeo)("pedido de lote: base e as 3 opções", () => {
  let p: Pedido
  beforeAll(() => {
    p = montarPedido(guardado(), cands, AGORA)
  })

  it("monta com fazendas aptas de verdade, sem as reservadas por outro cliente", () => {
    expect(cands.length).toBeGreaterThan(5000)
    expect(cands.every((c) => !reservadaPorOutro(c.cod_imovel))).toBe(true)
    const todos = new Set([...COM_CONTORNO.flatMap((c) => imoveisDe(c).filter((i) => i.apta).map((i) => i.cod_imovel))])
    expect([...todos].filter(reservadaPorOutro).length, "o exemplo tem reservas de outros clientes").toBeGreaterThan(0)
    for (const o of p.opcoes) expect(o.itens.some((i) => reservadaPorOutro(i.cod_imovel))).toBe(false)
  })

  it("quanto existe na base: faixa P10 < P50 < P90, por caminho e por interesse somam o total", () => {
    const b = p.base
    expect(b.fazendas).toBeGreaterThan(0)
    expect(b.creditos.p10).toBeLessThan(b.creditos.p50)
    expect(b.creditos.p50).toBeLessThan(b.creditos.p90)
    expect(b.por_caminho.reduce((s, c) => s + c.fazendas, 0)).toBe(b.fazendas)
    expect(b.por_interesse.reduce((s, c) => s + c.fazendas, 0)).toBe(b.fazendas)
    expect(b.alcanca_meta).toBe(true)
    expect(b.falta).toBe(0)
    // posse em titulação fica de fora no padrão; pequena nunca sai por tamanho
    expect(b.por_caminho.map((c) => c.caminho)).not.toContain("posse_em_titulacao")
    expect(p.opcoes.some((o) => o.pequenas > 0)).toBe(true)
  })

  it("as 3 opções fecham a meta, cada uma pelo seu critério", () => {
    const [barata, segura, compacta] = p.opcoes
    expect(p.opcoes.map((o) => o.id)).toEqual(["barata", "segura", "compacta"])
    for (const o of p.opcoes) {
      const lote = o.itens.filter((i) => i.papel === "lote")
      const reservas = o.itens.filter((i) => i.papel === "reserva")
      expect(o.alcanca_meta, o.id).toBe(true)
      expect(lote.reduce((s, i) => s + i.creditos.p50, 0)).toBeGreaterThanOrEqual(CAMPOS_PADRAO.meta.valor)
      expect(lote).toHaveLength(o.fazendas)
      expect(reservas.length, `${o.id}: reservas`).toBeGreaterThanOrEqual(3)
      expect(new Set(o.itens.map((i) => i.cod_imovel)).size, `${o.id}: sem fazenda repetida`).toBe(o.itens.length)
      expect(o.creditos.p10).toBeLessThan(o.creditos.p90)
      expect(o.marcos.map((m) => m.ano)).toEqual([7, 10, 15, 20, 25])
      expect(o.mistura_terra.reduce((s, m) => s + m.fracao, 0)).toBeCloseTo(1, 2)
    }
    // mais barata: o menor custo por crédito
    expect(barata.custo_usd_credito.p50).toBeLessThanOrEqual(segura.custo_usd_credito.p50)
    expect(barata.custo_usd_credito.p50).toBeLessThanOrEqual(compacta.custo_usd_credito.p50)
    // mais segura: fecha no P10, mais chance em todo marco e menos multa
    expect(segura.itens.filter((i) => i.papel === "lote").reduce((s, i) => s + i.creditos.p10, 0)).toBeGreaterThanOrEqual(CAMPOS_PADRAO.meta.valor)
    for (const [k, m] of segura.marcos.entries()) expect(m.chance).toBeGreaterThan(barata.marcos[k].chance)
    expect(segura.multa_esperada_usd).toBeLessThan(barata.multa_esperada_usd)
    // mais compacta: as fazendas mais perto umas das outras
    const espalhamento = (o: typeof barata) => {
      const l = o.itens.filter((i) => i.papel === "lote")
      const lon = l.reduce((s, i) => s + i.lon, 0) / l.length
      const lat = l.reduce((s, i) => s + i.lat, 0) / l.length
      return l.reduce((s, i) => s + Math.hypot(i.lon - lon, i.lat - lat), 0) / l.length
    }
    expect(espalhamento(compacta)).toBeLessThan(espalhamento(barata))
    expect(espalhamento(compacta)).toBeLessThan(espalhamento(segura))
  })

  it("filtro de interesse do dono: só interessados entra; sem base suficiente, diz quanto falta e o que afrouxar", () => {
    const so = montarPedido(guardado({ ...CAMPOS_PADRAO, interesse: "interessados" }), cands, AGORA)
    for (const o of so.opcoes)
      for (const i of o.itens) expect(["interessado", "aceite_fase1", "contrato_firme"], i.cod_imovel).toContain(i.interesse)
    const apertado = montarPedido(guardado({ ...CAMPOS_PADRAO, interesse: "com_aceite", terra: ["matricula_conferida"] }), cands, AGORA)
    expect(apertado.base.alcanca_meta).toBe(false)
    expect(apertado.base.falta).toBe(CAMPOS_PADRAO.meta.valor)
    expect(apertado.base.afrouxar.length).toBeGreaterThan(0)
    const ganhos = apertado.base.afrouxar.map((a) => a.ganho)
    expect(ganhos).toEqual([...ganhos].sort((a, b) => b - a))
    expect(apertado.opcoes.every((o) => !o.alcanca_meta && o.falta > 0)).toBe(true)
  })

  it("tirar e trocar: quem sai não volta, quem entra fica marcado, e a meta continua fechada", () => {
    const lote = p.opcoes[0].itens.filter((i) => i.papel === "lote")
    const reserva = p.opcoes[0].itens.find((i) => i.papel === "reserva")!
    const g = guardado(CAMPOS_PADRAO, { edicoes: { barata: { tiradas: [lote[0].cod_imovel], trocas: [{ sai: lote[1].cod_imovel, entra: reserva.cod_imovel }] } } })
    const o = montarPedido(g, cands, AGORA).opcoes[0]
    const cods = o.itens.map((i) => i.cod_imovel)
    expect(cods).not.toContain(lote[0].cod_imovel)
    expect(cods).not.toContain(lote[1].cod_imovel)
    const entrou = o.itens.find((i) => i.cod_imovel === reserva.cod_imovel)!
    expect(entrou).toMatchObject({ papel: "lote", trocou: lote[1].cod_imovel })
    expect(o.alcanca_meta).toBe(true)
  })

  it("nada pessoal do dono na resposta; o título do pedido em palavras", () => {
    semDadoPessoal(p)
    expect(tituloDoPedido(CAMPOS_PADRAO)).toBe("1 milhão de créditos, Amazônia, ProFloresta+")
    expect(fmtMeta(380_000, "hectares")).toBe("380 mil ha")
    expect(fmtFaixaMeta({ p10: 11e6, p50: 15.9e6, p90: 20e6 }, "creditos")).toBe("cerca de 16 milhões de créditos (de 11 milhões a 20 milhões)")
  })
})

describe.skipIf(!temGeo)("busca de interesse em ondas e reserva", () => {
  const onda = PREMISSAS.onda_ms
  const em = (n: number) => new Date(AGORA.getTime() + (n - 1) * onda + 10)
  let opcao: Pedido["opcoes"][number]
  let g: PedidoGuardado
  beforeAll(() => {
    mudarOnda(null)
    opcao = montarPedido(guardado(), cands, AGORA).opcoes[0]
    g = guardado(CAMPOS_PADRAO, { solicitado: { opcao: "barata", em: AGORA.toISOString() } })
  })

  it("contata mais donos do que a meta pede, a meta com interesse só sobe e o grupo fecha", () => {
    let antes = -1
    let pronto: number | null = null
    for (let n = 1; n <= 12; n++) {
      const a = simularAndamento(g, opcao, cands, CAMPOS_PADRAO, em(n))
      expect(a.com_interessado, `onda ${n}`).toBeGreaterThanOrEqual(antes)
      expect(a.com_aceite).toBeLessThanOrEqual(a.com_interessado)
      expect(a.com_contrato).toBeLessThanOrEqual(a.com_aceite)
      antes = a.com_interessado
      if (a.status === "grupo_pronto" && pronto === null) pronto = n
      semDadoPessoal(a)
    }
    expect(pronto, "o grupo fecha em poucas ondas").not.toBeNull()
    const a = simularAndamento(g, opcao, cands, CAMPOS_PADRAO, em(12))
    expect(a.com_interessado).toBeGreaterThanOrEqual(CAMPOS_PADRAO.meta.valor)
    expect(a.ondas[0].contatados, "a primeira onda contata mais que o lote").toBeGreaterThan(opcao.fazendas)
    expect(a.ondas[0].canais).toEqual(["WhatsApp", "carta", "e-mail"])
    // quem recusou saiu do grupo, com o motivo contado (sem nome)
    const grupo = new Set(grupoDe(a))
    for (const f of a.fazendas.filter((x) => x.interesse === "recusou")) expect(grupo.has(f.cod_imovel)).toBe(false)
    expect(a.motivos.reduce((s, m) => s + m.fazendas, 0)).toBe(a.recusas)
    expect(a.proxima_onda_em).toBeNull()
  })

  it("reserva: valor por hectare do grupo, prazo de 60 dias, Pix só depois de pedir, e vence sem contrato", () => {
    const a = simularAndamento(g, opcao, cands, CAMPOS_PADRAO, em(12))
    const ha = a.fazendas.filter((f) => grupoDe(a).includes(f.cod_imovel)).reduce((s, f) => s + f.hectares, 0)
    const cotacao = cobrancaDe(g, ha)
    expect(cotacao.pix).toBeNull()
    expect(cotacao.valor_brl).toBe(Math.max(PREMISSAS.reserva_minima_brl, Math.round(ha * PREMISSAS.reserva_brl_ha)))
    expect(cotacao.prazo_dias).toBe(60)
    expect(cotacao.abatimento).toMatch(/abatida da conexão por hectare/)
    const pedida = { ...g, reserva: { criada_em: em(12).toISOString(), pago_em: null, valor_brl: cotacao.valor_brl, hectares: cotacao.hectares } }
    const pix = cobrancaDe(pedida, ha * 2)
    expect(pix.valor_brl, "o valor fica fixo depois de pedir").toBe(cotacao.valor_brl)
    expect(pix.pix!.copia_e_cola.startsWith("000201"), "o Pix de exemplo não é um código de banco").toBe(false)
    const paga = { ...pedida, reserva: { ...pedida.reserva, pago_em: em(13).toISOString() } }
    const reservado = montarPedido(paga, cands, em(14))
    expect(reservado.status).toBe("reservado")
    expect(new Date(reservado.reservado_ate!).getTime() - em(13).getTime()).toBe(60 * 86_400_000)
    expect(montarPedido(paga, cands, new Date(em(13).getTime() + 61 * 86_400_000)).status).toBe("reserva_vencida")
  })
})

describe.skipIf(!temGeo)("área logada de exemplo, de ponta a ponta", () => {
  /** fonte de dados mínima, lendo a amostra do disco (o navegador lê pelo plugin do Vite) */
  const fonte = {
    geo: { comContorno: async () => COM_CONTORNO, camada: async (cod: string) => geoDe(cod) },
    imoveis: async (cod: string) => imoveisDe(cod),
    estados: async () => ({ pasta: "amostra", lista_ibge: "", estados: [] }),
  } as unknown as FonteDeDados

  it("entra pelo link, pede, troca, busca interesse, reserva e paga; outra conta não vê o pedido", async () => {
    let agora = AGORA.getTime()
    mudarOnda(1000)
    const f = fontePedidosExemplo(fonte, () => new Date(agora))
    expect(f.sessao()).toBeNull()
    await expect(f.listar()).rejects.toThrow(/Entre/)
    const { link_exemplo } = await f.entrar("Compras@Exemplo.com.br")
    const token = link_exemplo!.replace("#/entrar/", "")
    expect(lerRota(link_exemplo!)).toEqual({ tela: "entrar", token })
    const s = await f.confirmar(token)
    expect(s.email).toBe("compras@exemplo.com.br")
    expect(await f.listar()).toEqual([])

    const p = await f.criar(CAMPOS_PADRAO)
    expect(lerRota(`#/pedidos/${p.id}`)).toEqual({ tela: "pedido", id: p.id })
    expect(lerRota(`#/pedidos/${p.id}/grupo`)).toEqual({ tela: "grupo", id: p.id })
    expect(p.status).toBe("lote_montado")
    const lote = p.opcoes[0].itens.filter((i) => i.papel === "lote")
    const trocado = await f.mudarLote(p.id, { opcao: "barata", acao: "trocar", cod_imovel: lote[0].cod_imovel })
    expect(trocado.opcoes[0].itens.find((i) => i.trocou === lote[0].cod_imovel)?.papel).toBe("lote")
    await expect(f.reservar(p.id)).rejects.toThrow(/não fechou/)

    await f.solicitarInteresse(p.id, "barata")
    await expect(f.mudarLote(p.id, { opcao: "barata", acao: "tirar", cod_imovel: lote[1].cod_imovel })).rejects.toThrow(/já começou/)
    expect((await f.listar())[0].status).toBe("buscando_interesse")
    agora += 12_000
    const a = (await f.andamento(p.id))!
    expect(a.status).toBe("grupo_pronto")
    expect((await f.listar())[0]).toMatchObject({ status: "grupo_pronto", titulo: "1 milhão de créditos, Amazônia, ProFloresta+" })

    expect((await f.reserva(p.id))!.pix).toBeNull()
    const c = await f.reservar(p.id)
    expect(c.pix!.copia_e_cola).toMatch(/^EXEMPLO-SEM-VALOR/)
    expect(c.pago).toBe(false)
    const pago = await f.pagarExemplo!(p.id)
    expect(pago.pago).toBe(true)
    const r = (await f.listar())[0]
    expect(r.status).toBe("reservado")
    expect(r.reservado_ate).toBe(pago.reservado_ate)

    // outra pessoa entra: não vê o pedido de ninguém
    f.sair()
    const outro = await f.entrar("outra@empresa.com")
    await f.confirmar(outro.link_exemplo!.replace("#/entrar/", ""))
    expect(await f.listar()).toEqual([])
    expect(await f.pedido(p.id)).toBeNull()
    mudarOnda(null)
  }, 60_000)

  it("link de entrada inválido não entra", async () => {
    const f = fontePedidosExemplo(fonte)
    await expect(f.confirmar("abc.def")).rejects.toThrow(/não vale/)
  })
})

describe.skipIf(!temGeo)("exclusividade: reservada por outro cliente some para todo mundo", () => {
  it("some da lista do município, do contorno no mapa, da ficha, da busca e das certidões", async () => {
    const sfx = imoveisDe("1507300")
    const reservada = sfx.find((i) => reservadaPorOutro(i.cod_imovel))!
    const livre = sfx.find((i) => !reservadaPorOutro(i.cod_imovel))!
    const base = {
      imoveis: async () => sfx,
      imovel: async (c: string) => sfx.find((i) => i.cod_imovel === c) ?? null,
      ficha: async () => ({}) as never,
      certidoes: async () => [{ cod_imovel: reservada.cod_imovel }] as never,
      buscar: async (q: string) => ({ q, tipo: "car", situacao: "ok", mensagem: null, imoveis: sfx.filter((i) => i.cod_imovel === q), municipios: [] }),
      geo: { camada: async () => geoDe("1507300"), comContorno: async () => ["1507300"], base: async () => null, brasil: async () => ({ municipios: null, estados: null, base: null }) },
    } as unknown as FonteDeDados
    const f = semReservadasPorOutros(base)
    const lista = (await f.imoveis("1507300"))!
    expect(lista.some((i) => i.cod_imovel === reservada.cod_imovel)).toBe(false)
    expect(lista.some((i) => i.cod_imovel === livre.cod_imovel)).toBe(true)
    expect(await f.imovel(reservada.cod_imovel)).toBeNull()
    expect(await f.ficha(reservada.cod_imovel)).toBeNull()
    expect(await f.certidoes(reservada.cod_imovel)).toEqual([])
    const r = await f.buscar(reservada.cod_imovel)
    expect(r.imoveis).toEqual([])
    expect(r.situacao).toBe("nao_encontrado")
    const geo = (await f.geo.camada("1507300", "imoveis"))!
    expect(geo.features.some((x) => x.properties.cod_imovel === reservada.cod_imovel)).toBe(false)
  })
})

describe("rotas da área logada", () => {
  it("entrar, meus pedidos, novo pedido, pedido e grupo", () => {
    expect(lerRota("#/entrar")).toEqual({ tela: "entrar", token: null })
    expect(lerRota("#/entrar/ab12.cd34")).toEqual({ tela: "entrar", token: "ab12.cd34" })
    expect(lerRota("#/pedidos")).toEqual({ tela: "pedidos" })
    expect(lerRota("#/pedidos/novo")).toEqual({ tela: "pedido-novo" })
    expect(lerRota("#/pedidos/x1y2z3")).toEqual({ tela: "pedido", id: "x1y2z3" })
    expect(lerRota("#/pedidos/x1y2z3/grupo")).toEqual({ tela: "grupo", id: "x1y2z3" })
    expect(lerRota("#/pedidos/../x")).toEqual({ tela: "entrada" })
  })
})
