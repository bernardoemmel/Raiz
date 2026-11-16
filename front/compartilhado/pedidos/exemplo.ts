/**
 * Resposta de EXEMPLO do back-end de pedidos, enquanto POST /pedidos, /solicitar-interesse, /andamento e /reservar não
 * estão prontos. Mesmo formato do contrato (pedidos/tipos.ts), feito com fazendas aptas de verdade (as que já têm o
 * contorno no mapa) e premissas escritas abaixo, para a tela poder ser usada e testada de ponta a ponta. Os números de
 * custo, TIR, chance e aceite são ilustrativos: o otimizador de verdade (solver aberto, cena-alvo) fica no back-end.
 *
 * Tudo é determinístico: o mesmo pedido dá o mesmo lote, e o andamento da busca de interesse sai do tempo desde que o
 * cliente pediu (uma onda a cada PREMISSAS.onda_ms). Nada aqui tem nome, CPF ou contato do dono.
 */

import type { Imovel } from "../dados/tipos"
import type {
  Alerta,
  Andamento,
  BaseDisponivel,
  CaminhoTerra,
  CamposPedido,
  Cobranca,
  Faixa,
  FazendaDoLote,
  IdOpcao,
  Marco,
  Metodo,
  NivelInteresse,
  Opcao,
  Pedido,
  StatusPedido,
} from "./tipos"

/** Premissas da resposta de exemplo (aparecem na tela em "Ver como calculamos"). */
export const PREMISSAS = {
  versao: "exemplo-2026-11-12",
  /** créditos líquidos contados em 25 anos (o horizonte do ProFloresta+) */
  anos: 25,
  /** desconto do potencial bruto do motor: linha de base, vazamento e reserva de não permanência */
  desconto_liquido: 0.4,
  /** P10 e P90 como fração do P50 da captura */
  p10: 0.7,
  p90: 1.25,
  /** custo de restaurar por hectare, em dólar, por método */
  custo_ha_usd: {
    regeneracao_assistida: 350,
    semeadura_direta: 1100,
    plantio_total: 2900,
    agrofloresta: 3500,
    silvipastoril: 1500,
  } as Record<Metodo, number>,
  /** captura relativa à regeneração assistida */
  captura_relativa: {
    regeneracao_assistida: 1,
    semeadura_direta: 1.1,
    plantio_total: 1.25,
    agrofloresta: 0.9,
    silvipastoril: 0.5,
  } as Record<Metodo, number>,
  /** custo fixo por fazenda (contrato, monitoramento); a pequena agrupada divide com as vizinhas */
  custo_fixo_usd: 12000,
  custo_fixo_pequena_usd: 3000,
  /** risco do caminho da terra (0 a 1) */
  risco_terra: {
    matricula_conferida: 0.05,
    matricula_a_conferir: 0.12,
    concessao: 0.15,
    assentamento: 0.25,
    posse_em_titulacao: 0.45,
  } as Record<CaminhoTerra, number>,
  /** chance de aceite esperada por nível de interesse */
  aceite: { sem_contato: 0.45, contatado: 0.5, interessado: 0.75, aceite_fase1: 0.92, contrato_firme: 1, recusou: 0, sem_resposta: 0.1 } as Record<
    NivelInteresse,
    number
  >,
  multa_usd_credito: 8,
  /** uma onda de contato a cada tanto (no back-end, dias; no exemplo, segundos para dar para ver) */
  onda_ms: 20_000,
  reserva_brl_ha: 12,
  reserva_minima_brl: 2000,
  prazo_reserva_dias: 60,
}

/** Marcos do cronograma: fração da meta entregue até cada ano. */
export function marcosDo(campos: CamposPedido): { ano: number; fracao: number }[] {
  if (campos.cronograma === "proprio" && campos.marcos_proprios?.length) return [...campos.marcos_proprios].sort((a, b) => a.ano - b.ano)
  if (campos.cronograma === "livre") return [{ ano: PREMISSAS.anos, fracao: 1 }]
  // ProFloresta+: 12% no ano 7 até 100% no ano 25 (os marcos do meio são os de exemplo)
  return [
    { ano: 7, fracao: 0.12 },
    { ano: 10, fracao: 0.25 },
    { ano: 15, fracao: 0.5 },
    { ano: 20, fracao: 0.75 },
    { ano: 25, fracao: 1 },
  ]
}

export const CAMPOS_PADRAO: CamposPedido = {
  meta: { tipo: "creditos", valor: 1_000_000 },
  cronograma: "profloresta",
  onde: { biomas: ["Amazônia"], ufs: [], municipios: [], raio: null, poligono: null, so_fornecedores_cadeia: false },
  dinheiro: { custo_max_usd_credito: null, tir_min: null, preco_venda_usd: 25, fracao_financiada: 0 },
  metodos: ["regeneracao_assistida", "semeadura_direta", "plantio_total"],
  terra: ["matricula_conferida", "matricula_a_conferir", "concessao", "assentamento"],
  forma: { distancia_max_km: null, max_donos: null, area_min_contigua_ha: null },
  interesse: "qualquer",
  exclusoes: ["embargo", "terra_indigena", "uc_protecao_integral", "projeto_carbono"],
}

// ---- sorteio determinístico ---------------------------------------------------------------------------------------

/** FNV-1a: o mesmo texto dá sempre o mesmo número entre 0 e 1 */
export function sorteio(texto: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < texto.length; i++) {
    h ^= texto.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0) / 4294967296
}

/**
 * Fazendas reservadas por OUTRO cliente, no exemplo (cerca de 1,5%): somem de toda busca, mapa, ficha e lote. No
 * back-end, quem esconde é o servidor.
 */
export const reservadaPorOutro = (cod_imovel: string) => sorteio("reserva:" + cod_imovel) < 0.015

/** Nível de interesse que a fazenda já tem na base de exemplo (a maioria nunca foi contatada). */
export function interesseInicial(cod_imovel: string): NivelInteresse {
  const u = sorteio("interesse:" + cod_imovel)
  if (u < 0.01) return "contrato_firme"
  if (u < 0.05) return "aceite_fase1"
  if (u < 0.14) return "interessado"
  if (u < 0.24) return "contatado"
  return "sem_contato"
}

const ORDEM_INTERESSE: NivelInteresse[] = ["sem_contato", "contatado", "interessado", "aceite_fase1", "contrato_firme"]
const nivel = (n: NivelInteresse) => ORDEM_INTERESSE.indexOf(n)

// ---- candidatos ---------------------------------------------------------------------------------------------------

/** Uma fazenda apta pronta para entrar em lote. */
export interface Candidato {
  cod_imovel: string
  cod_ibge: string
  municipio: string
  uf: string
  bioma: string | null
  /** área que pode voltar a ser mata */
  hectares: number
  tco2_ano: number
  caminho: CaminhoTerra
  pequena: boolean
  lon: number
  lat: number
  embargo: boolean
  terra_indigena: boolean
  uc_protecao_integral: boolean
  projeto_carbono: boolean
  /** fogo no ano mais recente do MapBiomas (ha) e o ano */
  fogo_ha: number
  fogo_ano: number | null
  desmate_recente: boolean
  interesse: NivelInteresse
}

export function caminhoDe(i: Imovel): CaminhoTerra {
  if (i.com_matricula || i.f_matricula >= 0.5) return i.linha.matricula_conferida === "True" ? "matricula_conferida" : "matricula_a_conferir"
  if (i.assentamento) return "assentamento"
  return "posse_em_titulacao"
}

const num = (v: string | undefined) => {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

/** O candidato a partir do imóvel do motor e do meio do polígono (só fazenda apta e não reservada por outro). */
export function candidatoDe(i: Imovel, centro: [number, number] | null): Candidato | null {
  if (!i.apta || !centro || reservadaPorOutro(i.cod_imovel)) return null
  return {
    cod_imovel: i.cod_imovel,
    cod_ibge: i.cod_ibge,
    municipio: i.municipio,
    uf: i.uf,
    bioma: i.bioma,
    hectares: i.carbono_ha,
    tco2_ano: i.carbono_tco2_ano,
    caminho: caminhoDe(i),
    pequena: i.pequena,
    lon: centro[0],
    lat: centro[1],
    embargo: i.embargo_ha > 0,
    terra_indigena: i.ti_ha > 0 || (i.ti_funai_ha ?? 0) > 0,
    uc_protecao_integral: num(i.linha.uc_protecao_integral_ha) > 0,
    projeto_carbono: num(i.linha.projeto_carbono_ha) > 0,
    fogo_ha: i.mb_fogo_ha ?? 0,
    fogo_ano: i.mb_ano,
    desmate_recente: (i.desm_pos2016_ha ?? 0) > 0,
    interesse: interesseInicial(i.cod_imovel),
  }
}

// ---- contas por fazenda ---------------------------------------------------------------------------------------------

interface Conta {
  c: Candidato
  metodo: Metodo
  creditos: Faixa
  custo_usd: number
  custo_usd_credito: number
  risco: number
  aceite: number
}

const ORDEM_METODOS: Metodo[] = ["regeneracao_assistida", "semeadura_direta", "plantio_total", "agrofloresta", "silvipastoril"]

function contar(c: Candidato, campos: CamposPedido): Conta | null {
  const metodo = ORDEM_METODOS.find((m) => campos.metodos.includes(m))
  if (!metodo) return null
  const bruto = c.tco2_ano * PREMISSAS.anos * (1 - PREMISSAS.desconto_liquido) * PREMISSAS.captura_relativa[metodo]
  const custo = c.hectares * PREMISSAS.custo_ha_usd[metodo] + (c.pequena ? PREMISSAS.custo_fixo_pequena_usd : PREMISSAS.custo_fixo_usd)
  const risco = Math.min(
    1,
    PREMISSAS.risco_terra[c.caminho] + (c.fogo_ha > 0 ? 0.1 : 0) + (c.desmate_recente ? 0.05 : 0) - Math.max(0, nivel(c.interesse) - 1) * 0.05,
  )
  return {
    c,
    metodo,
    creditos: { p10: bruto * PREMISSAS.p10, p50: bruto, p90: bruto * PREMISSAS.p90 },
    custo_usd: custo,
    custo_usd_credito: bruto > 0 ? custo / bruto : Infinity,
    risco,
    aceite: PREMISSAS.aceite[c.interesse] * (c.caminho === "posse_em_titulacao" ? 0.8 : 1),
  }
}

/** quanto a fazenda vale na unidade da meta */
function naMeta(k: Conta, campos: CamposPedido): number {
  if (campos.meta.tipo === "hectares") return k.c.hectares
  if (campos.meta.tipo === "flag_t_ano") return k.c.tco2_ano * (1 - PREMISSAS.desconto_liquido)
  return k.creditos.p50
}

function distanciaKm(a: { lon: number; lat: number }, b: { lon: number; lat: number }): number {
  const r = Math.PI / 180
  const dLat = (b.lat - a.lat) * r
  const dLon = (b.lon - a.lon) * r
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2
  return 6371 * 2 * Math.asin(Math.sqrt(s))
}

function dentroDoPoligono(p: [number, number], anel: [number, number][]): boolean {
  let dentro = false
  for (let i = 0, j = anel.length - 1; i < anel.length; j = i++) {
    const [xi, yi] = anel[i]
    const [xj, yj] = anel[j]
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) dentro = !dentro
  }
  return dentro
}

/** os candidatos que passam no pedido (sem o filtro de interesse, que vai à parte) */
function filtrar(cands: Candidato[], campos: CamposPedido): Conta[] {
  const o = campos.onde
  if (o.so_fornecedores_cadeia) return []
  const saida: Conta[] = []
  for (const c of cands) {
    if (o.biomas.length && !o.biomas.includes(c.bioma ?? "")) continue
    if (o.ufs.length && !o.ufs.includes(c.uf)) continue
    if (o.municipios.length && !o.municipios.includes(c.cod_ibge)) continue
    if (o.raio && distanciaKm(c, o.raio) > o.raio.km) continue
    if (o.poligono && o.poligono.length >= 4 && !dentroDoPoligono([c.lon, c.lat], o.poligono)) continue
    if (!campos.terra.includes(c.caminho)) continue
    if (campos.exclusoes.includes("embargo") && c.embargo) continue
    if (campos.exclusoes.includes("terra_indigena") && c.terra_indigena) continue
    if (campos.exclusoes.includes("uc_protecao_integral") && c.uc_protecao_integral) continue
    if (campos.exclusoes.includes("projeto_carbono") && c.projeto_carbono) continue
    const k = contar(c, campos)
    if (!k || !(k.creditos.p50 > 0)) continue
    if (campos.dinheiro.custo_max_usd_credito !== null && k.custo_usd_credito > campos.dinheiro.custo_max_usd_credito) continue
    if (campos.dinheiro.tir_min !== null && tirDaFazenda(k, campos) < campos.dinheiro.tir_min) continue
    saida.push(k)
  }
  return saida
}

const passaInteresse = (c: Candidato, f: CamposPedido["interesse"]) =>
  f === "qualquer" || (f === "interessados" ? nivel(c.interesse) >= nivel("interessado") : nivel(c.interesse) >= nivel("aceite_fase1"))

// ---- dinheiro -----------------------------------------------------------------------------------------------------

/** fração da meta entregue até o ano t (interpolando os marcos; nada antes do ano 3) */
function entregueAte(t: number, marcos: { ano: number; fracao: number }[]): number {
  let anterior = { ano: 3, fracao: 0 }
  for (const m of marcos) {
    if (t <= m.ano) return t <= anterior.ano ? anterior.fracao : anterior.fracao + ((m.fracao - anterior.fracao) * (t - anterior.ano)) / (m.ano - anterior.ano)
    anterior = m
  }
  return 1
}

/** caixa ano a ano: custo nos 3 primeiros anos, receita conforme os créditos saem */
function caixa(custo: number, creditos: number, campos: CamposPedido): number[] {
  const marcos = marcosDo(campos)
  const fluxo: number[] = []
  for (let t = 0; t <= PREMISSAS.anos; t++) {
    const saida = t === 0 ? custo * 0.6 : t === 1 ? custo * 0.25 : t === 2 ? custo * 0.15 : 0
    const emitidos = (entregueAte(t, marcos) - entregueAte(t - 1, marcos)) * creditos
    fluxo.push(emitidos * campos.dinheiro.preco_venda_usd - saida)
  }
  return fluxo
}

/** taxa interna de retorno por bisseção (-90% a 200% ao ano) */
export function tir(fluxo: number[]): number {
  const vpl = (r: number) => fluxo.reduce((s, f, t) => s + f / (1 + r) ** t, 0)
  let a = -0.9
  let b = 2
  if (vpl(a) * vpl(b) > 0) return vpl(0) > 0 ? b : a
  for (let i = 0; i < 80; i++) {
    const m = (a + b) / 2
    if (vpl(a) * vpl(m) <= 0) b = m
    else a = m
  }
  return (a + b) / 2
}

const tirDaFazenda = (k: Conta, campos: CamposPedido) => tir(caixa(k.custo_usd, k.creditos.p50, campos))

/** função de distribuição da normal (para a chance de cumprir o marco) */
function normal(z: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(z))
  const d = 0.3989423 * Math.exp((-z * z) / 2)
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  return z > 0 ? 1 - p : p
}

// ---- opções -------------------------------------------------------------------------------------------------------

/** ordem em que cada opção puxa as fazendas: o mesmo critério com pesos diferentes */
function ordenar(contas: Conta[], id: IdOpcao, campos: CamposPedido): Conta[] {
  if (id === "barata") return [...contas].sort((a, b) => a.custo_usd_credito - b.custo_usd_credito || a.c.cod_imovel.localeCompare(b.c.cod_imovel))
  if (id === "segura")
    return [...contas].sort(
      (a, b) => a.risco - a.aceite * 0.2 - (b.risco - b.aceite * 0.2) || a.custo_usd_credito - b.custo_usd_credito || a.c.cod_imovel.localeCompare(b.c.cod_imovel),
    )
  // compacta: começa onde há mais crédito num raio e puxa as mais perto; o custo desempata
  const raio = campos.forma.distancia_max_km ?? 25
  let semente = contas[0]
  let melhor = -1
  const amostra = contas.length > 600 ? contas.filter((_, i) => i % Math.ceil(contas.length / 600) === 0) : contas
  for (const s of amostra) {
    let soma = 0
    for (const k of contas) if (distanciaKm(s.c, k.c) <= raio) soma += naMeta(k, campos)
    if (soma > melhor) {
      melhor = soma
      semente = s
    }
  }
  if (!semente) return []
  return [...contas].sort((a, b) => distanciaKm(semente.c, a.c) - distanciaKm(semente.c, b.c) || a.custo_usd_credito - b.custo_usd_credito)
}

function item(k: Conta, papel: "lote" | "reserva", trocou: string | null = null): FazendaDoLote {
  return {
    cod_imovel: k.c.cod_imovel,
    ficha_liberada: true,
    cod_ibge: k.c.cod_ibge,
    municipio: k.c.municipio,
    uf: k.c.uf,
    papel,
    hectares: Math.round(k.c.hectares),
    creditos: arredondarFaixa(k.creditos),
    metodo: k.metodo,
    caminho: k.c.caminho,
    custo_usd_credito: Math.round(k.custo_usd_credito * 100) / 100,
    pequena: k.c.pequena,
    interesse: k.c.interesse,
    trocou,
    lon: k.c.lon,
    lat: k.c.lat,
  }
}

const arredondarFaixa = (f: Faixa): Faixa => ({ p10: Math.round(f.p10), p50: Math.round(f.p50), p90: Math.round(f.p90) })

/**
 * Escolhe o lote na ordem dada até a meta, e as reservas logo depois. A mais segura fecha a meta já no P10 (cenário
 * ruim da captura), por isso leva mais fazendas e tem mais chance de cumprir os marcos.
 */
function escolher(ordem: Conta[], campos: CamposPedido, fora: Set<string>, folga = false): { lote: Conta[]; reservas: Conta[] } {
  const conta = (k: Conta) => (folga && campos.meta.tipo === "creditos" ? k.creditos.p10 : naMeta(k, campos))
  const lote: Conta[] = []
  let soma = 0
  const maxDonos = campos.forma.max_donos ?? Infinity
  const distMax = campos.forma.distancia_max_km
  let k = 0
  for (; k < ordem.length && soma < campos.meta.valor && lote.length < maxDonos; k++) {
    const x = ordem[k]
    if (fora.has(x.c.cod_imovel)) continue
    if (distMax !== null && lote.length && distanciaKm(lote[0].c, x.c) > distMax) continue
    lote.push(x)
    soma += conta(x)
  }
  // reservas: tantas quantas a chance de aceite pede (bem mais do que a meta), pelo menos 3
  const aceiteMedio = lote.length ? lote.reduce((s, x) => s + x.aceite, 0) / lote.length : 0.5
  const quantas = Math.max(3, Math.ceil(lote.length * (1 / Math.max(aceiteMedio, 0.2) - 1)))
  const reservas: Conta[] = []
  for (; k < ordem.length && reservas.length < quantas; k++) {
    const x = ordem[k]
    if (fora.has(x.c.cod_imovel)) continue
    if (distMax !== null && lote.length && distanciaKm(lote[0].c, x.c) > distMax) continue
    reservas.push(x)
  }
  return { lote, reservas }
}

function numerosDaOpcao(id: IdOpcao, lote: Conta[], reservas: Conta[], campos: CamposPedido, trocas: Map<string, string>): Opcao {
  const somar = (f: (k: Conta) => number) => lote.reduce((s, k) => s + f(k), 0)
  const creditos = { p10: somar((k) => k.creditos.p10), p50: somar((k) => k.creditos.p50), p90: somar((k) => k.creditos.p90) }
  const custo = somar((k) => k.custo_usd)
  const naUnidade = somar((k) => naMeta(k, campos))
  const meta = campos.meta.valor
  const riscoMedio = creditos.p50 > 0 ? somar((k) => k.risco * k.creditos.p50) / creditos.p50 : 0
  const fluxo = caixa(custo, creditos.p50, campos)
  let acumulado = 0
  let pico = 0
  for (const f of fluxo) {
    acumulado += f
    pico = Math.min(pico, acumulado)
  }
  // chance de cumprir cada marco: captura esperada (descontado o risco da terra) contra a meta, com a incerteza maior no começo
  const metaCreditos = campos.meta.tipo === "creditos" ? meta : creditos.p50
  const media = creditos.p50 * (1 - 0.25 * riscoMedio)
  const sigma = Math.max(1, (creditos.p90 - creditos.p10) / 2.563)
  const marcos: Marco[] = marcosDo(campos).map((m) => {
    const s = sigma * (1 + 0.5 * (1 - m.ano / PREMISSAS.anos))
    return { ano: m.ano, fracao: m.fracao, chance: Math.round(normal((media - metaCreditos) / s) * 100) / 100 }
  })
  const multa = marcos.reduce((s, m) => s + (1 - m.chance) * metaCreditos * m.fracao * 0.1 * PREMISSAS.multa_usd_credito, 0) / Math.max(1, marcos.length)
  const porCaminho = new Map<CaminhoTerra, number>()
  const porMetodo = new Map<Metodo, number>()
  for (const k of lote) {
    porCaminho.set(k.c.caminho, (porCaminho.get(k.c.caminho) ?? 0) + k.creditos.p50)
    porMetodo.set(k.metodo, (porMetodo.get(k.metodo) ?? 0) + 1)
  }
  return {
    id,
    creditos: arredondarFaixa(creditos),
    hectares: Math.round(somar((k) => k.c.hectares)),
    fazendas: lote.length,
    pequenas: lote.filter((k) => k.c.pequena).length,
    tir: {
      p10: round3(tir(caixa(custo * 1.15, creditos.p10, campos))),
      p50: round3(tir(fluxo)),
      p90: round3(tir(caixa(custo * 0.9, creditos.p90, campos))),
    },
    custo_usd_credito: {
      p10: round2(creditos.p90 ? (custo * 0.9) / creditos.p90 : 0),
      p50: round2(creditos.p50 ? custo / creditos.p50 : 0),
      p90: round2(creditos.p10 ? (custo * 1.15) / creditos.p10 : 0),
    },
    pico_caixa_usd: Math.round(-pico),
    marcos,
    multa_esperada_usd: Math.round(multa),
    mistura_terra: [...porCaminho].map(([caminho, c]) => ({ caminho, fracao: round3(creditos.p50 ? c / creditos.p50 : 0) })).sort((a, b) => b.fracao - a.fracao),
    metodos: [...porMetodo].map(([metodo, fazendas]) => ({ metodo, fazendas })),
    itens: [...lote.map((k) => item(k, "lote", trocas.get(k.c.cod_imovel) ?? null)), ...reservas.map((k) => item(k, "reserva"))],
    alcanca_meta: naUnidade >= meta,
    falta: Math.max(0, Math.round(meta - naUnidade)),
  }
}

const round2 = (v: number) => Math.round(v * 100) / 100
const round3 = (v: number) => Math.round(v * 1000) / 1000

/** Mudanças do cliente numa opção: quem ele tirou e quem trocou por quem. */
export interface Edicoes {
  tiradas: string[]
  trocas: { sai: string; entra: string }[]
}

function montarOpcao(id: IdOpcao, contas: Conta[], campos: CamposPedido, ed: Edicoes | undefined): Opcao {
  const ordem = ordenar(contas, id, campos)
  const fora = new Set(ed?.tiradas ?? [])
  const trocas = new Map<string, string>()
  for (const t of ed?.trocas ?? []) fora.add(t.sai)
  // quem entrou por troca vai para a frente da fila
  const entram = new Set((ed?.trocas ?? []).map((t) => t.entra))
  for (const t of ed?.trocas ?? []) trocas.set(t.entra, t.sai)
  const ordemFinal = [...ordem.filter((k) => entram.has(k.c.cod_imovel)), ...ordem.filter((k) => !entram.has(k.c.cod_imovel))]
  const { lote, reservas } = escolher(ordemFinal, campos, fora, id === "segura")
  return numerosDaOpcao(id, lote, reservas, campos, trocas)
}

// ---- base disponível ------------------------------------------------------------------------------------------------

function baseDe(contas: Conta[], campos: CamposPedido): Omit<BaseDisponivel, "afrouxar" | "observacao"> {
  const meta = campos.meta.valor
  const porCaminho = new Map<CaminhoTerra, { fazendas: number; hectares: number; creditos: number }>()
  const porInteresse = new Map<NivelInteresse, { fazendas: number; creditos: number }>()
  let hectares = 0
  const creditos = { p10: 0, p50: 0, p90: 0 }
  let naUnidade = 0
  for (const k of contas) {
    hectares += k.c.hectares
    creditos.p10 += k.creditos.p10
    creditos.p50 += k.creditos.p50
    creditos.p90 += k.creditos.p90
    naUnidade += naMeta(k, campos)
    const a = porCaminho.get(k.c.caminho) ?? { fazendas: 0, hectares: 0, creditos: 0 }
    a.fazendas++
    a.hectares += k.c.hectares
    a.creditos += k.creditos.p50
    porCaminho.set(k.c.caminho, a)
    const b = porInteresse.get(k.c.interesse) ?? { fazendas: 0, creditos: 0 }
    b.fazendas++
    b.creditos += k.creditos.p50
    porInteresse.set(k.c.interesse, b)
  }
  return {
    fazendas: contas.length,
    hectares: Math.round(hectares),
    creditos: arredondarFaixa(creditos),
    por_caminho: [...porCaminho].map(([caminho, v]) => ({ caminho, fazendas: v.fazendas, hectares: Math.round(v.hectares), creditos: Math.round(v.creditos) })),
    por_interesse: ORDEM_INTERESSE.filter((n) => porInteresse.has(n)).map((nivel) => ({
      nivel,
      fazendas: porInteresse.get(nivel)!.fazendas,
      creditos: Math.round(porInteresse.get(nivel)!.creditos),
    })),
    alcanca_meta: naUnidade >= meta,
    falta: Math.max(0, Math.round(meta - naUnidade)),
  }
}

const ROTULO_CAMINHO: Record<CaminhoTerra, string> = {
  matricula_conferida: "matrícula conferida",
  matricula_a_conferir: "matrícula a conferir",
  concessao: "concessão",
  assentamento: "assentamento",
  posse_em_titulacao: "posse em titulação",
}

/** o que afrouxar no pedido para alcançar a meta, com quanto cada mudança soma (na unidade da meta) */
function afrouxar(cands: Candidato[], campos: CamposPedido, atual: number): BaseDisponivel["afrouxar"] {
  const total = (c: CamposPedido) => filtrar(cands, c).filter((k) => passaInteresse(k.c, c.interesse)).reduce((s, k) => s + naMeta(k, c), 0)
  const tentativas: { campo: string; texto: string; campos: CamposPedido }[] = []
  if (campos.onde.so_fornecedores_cadeia)
    tentativas.push({
      campo: "onde",
      texto: "Tirar \"só fornecedores da cadeia\" (a lista da sua cadeia ainda não foi enviada)",
      campos: { ...campos, onde: { ...campos.onde, so_fornecedores_cadeia: false } },
    })
  if (campos.interesse !== "qualquer")
    tentativas.push({ campo: "interesse", texto: "Aceitar fazenda com qualquer interesse do dono (a Raíz busca o aceite depois)", campos: { ...campos, interesse: "qualquer" } })
  if (campos.interesse === "com_aceite")
    tentativas.push({ campo: "interesse", texto: "Aceitar fazenda com dono interessado, ainda sem aceite", campos: { ...campos, interesse: "interessados" } })
  for (const c of ["posse_em_titulacao", "assentamento", "matricula_a_conferir"] as CaminhoTerra[])
    if (!campos.terra.includes(c))
      tentativas.push({ campo: "terra", texto: `Aceitar terra em ${ROTULO_CAMINHO[c]}`, campos: { ...campos, terra: [...campos.terra, c] } })
  if (campos.dinheiro.custo_max_usd_credito !== null)
    tentativas.push({ campo: "dinheiro", texto: "Tirar o custo máximo por crédito", campos: { ...campos, dinheiro: { ...campos.dinheiro, custo_max_usd_credito: null } } })
  if (campos.dinheiro.tir_min !== null)
    tentativas.push({ campo: "dinheiro", texto: "Tirar a TIR mínima", campos: { ...campos, dinheiro: { ...campos.dinheiro, tir_min: null } } })
  if (campos.onde.ufs.length || campos.onde.municipios.length || campos.onde.raio || campos.onde.poligono)
    tentativas.push({
      campo: "onde",
      texto: "Abrir a área: todo o bioma, sem estado, município, raio ou polígono",
      campos: { ...campos, onde: { ...campos.onde, ufs: [], municipios: [], raio: null, poligono: null } },
    })
  if (campos.forma.max_donos !== null || campos.forma.distancia_max_km !== null)
    tentativas.push({ campo: "forma", texto: "Tirar o limite de donos e de distância entre fazendas", campos: { ...campos, forma: { ...campos.forma, max_donos: null, distancia_max_km: null } } })
  if (!campos.metodos.includes("plantio_total"))
    tentativas.push({ campo: "metodos", texto: "Aceitar plantio total", campos: { ...campos, metodos: [...campos.metodos, "plantio_total"] } })
  return tentativas
    .map((t) => ({ campo: t.campo, texto: t.texto, ganho: Math.round(total(t.campos) - atual) }))
    .filter((t) => t.ganho > 0)
    .sort((a, b) => b.ganho - a.ganho)
}

// ---- o pedido inteiro -----------------------------------------------------------------------------------------------

/** Estado guardado de um pedido de exemplo (o resto se recalcula). */
export interface PedidoGuardado {
  id: string
  criado_em: string
  campos: CamposPedido
  edicoes: Partial<Record<IdOpcao, Edicoes>>
  solicitado: { opcao: IdOpcao; em: string } | null
  /** valor e hectares ficam fixos quando a reserva é pedida (o grupo ainda pode ganhar resposta atrasada) */
  reserva: { criada_em: string; pago_em: string | null; valor_brl?: number; hectares?: number } | null
  /** quando os dados de cada estado foram publicados, no dia do pedido (para o alerta "o lote pode ter melhorado") */
  dados_de: Record<string, string>
}

export const IDS_OPCOES: IdOpcao[] = ["barata", "segura", "compacta"]

export function montarPedido(g: PedidoGuardado, cands: Candidato[], agora: Date, dadosAgora: Record<string, string> = {}): Pedido {
  const campos = g.campos
  const contas = filtrar(cands, campos)
  const comInteresse = contas.filter((k) => passaInteresse(k.c, campos.interesse))
  const b = baseDe(comInteresse, campos)
  const base: BaseDisponivel = {
    ...b,
    afrouxar: b.alcanca_meta ? [] : afrouxar(cands, campos, b.alcanca_meta ? 0 : campos.meta.valor - b.falta),
    observacao: "Base de exemplo: fazendas aptas que já têm o contorno no mapa. O back-end conta a base inteira.",
  }
  const opcoes = IDS_OPCOES.map((id) => montarOpcao(id, comInteresse, campos, g.edicoes[id]))
  const andamento = g.solicitado ? simularAndamento(g, opcoes.find((o) => o.id === g.solicitado!.opcao)!, cands, campos, agora) : null
  const status = statusDo(g, andamento, agora)
  const reservado_ate = g.reserva?.pago_em ? fimDaReserva(g.reserva.pago_em) : null
  return {
    id: g.id,
    criado_em: g.criado_em,
    campos,
    status,
    base,
    opcoes,
    opcao_escolhida: g.solicitado?.opcao ?? null,
    reservado_ate,
    alertas: alertasDo(g, opcoes, andamento, cands, dadosAgora),
    versao_modelo: PREMISSAS.versao,
    exemplo: true,
  }
}

const fimDaReserva = (pago_em: string) => new Date(new Date(pago_em).getTime() + PREMISSAS.prazo_reserva_dias * 86_400_000).toISOString()

function statusDo(g: PedidoGuardado, a: Andamento | null, agora: Date): StatusPedido {
  if (g.reserva?.pago_em) return new Date(fimDaReserva(g.reserva.pago_em)) > agora ? "reservado" : "reserva_vencida"
  if (!a) return "lote_montado"
  return a.status
}

function alertasDo(g: PedidoGuardado, opcoes: Opcao[], a: Andamento | null, cands: Candidato[], dadosAgora: Record<string, string>): Alerta[] {
  const alertas: Alerta[] = []
  // dado novo publicado depois do pedido: o lote pode ter melhorado
  for (const [uf, quando] of Object.entries(dadosAgora))
    if (g.dados_de[uf] && quando > g.dados_de[uf])
      alertas.push({
        tipo: "lote_melhorou",
        texto: `Dados novos de ${uf} publicados em ${new Date(quando).toLocaleDateString("pt-BR")}: o lote pode ter melhorado.`,
        data: quando,
      })
  // fazenda do grupo (ou do lote escolhido) com fogo no ano mais recente do MapBiomas: dado de verdade
  const opcao = opcoes.find((o) => o.id === (g.solicitado?.opcao ?? "barata"))
  const noGrupo = new Set(a ? a.fazendas.filter((f) => nivel(f.interesse) >= nivel("interessado")).map((f) => f.cod_imovel) : (opcao?.itens.filter((i) => i.papel === "lote").map((i) => i.cod_imovel) ?? []))
  const porCod = new Map(cands.map((c) => [c.cod_imovel, c]))
  for (const cod of noGrupo) {
    const c = porCod.get(cod)
    if (c && c.fogo_ha >= 1)
      alertas.push({
        tipo: "fazenda_com_problema",
        texto: `Fogo em ${c.fogo_ano ?? "ano recente"} numa fazenda ${a ? "do grupo" : "do lote"}: ${Math.round(c.fogo_ha)} ha em ${c.municipio} (MapBiomas Fogo).`,
        data: g.criado_em,
        cod_imovel: cod,
      })
  }
  return alertas.slice(0, 6)
}

// ---- busca de interesse em ondas ----------------------------------------------------------------------------------

const MOTIVOS = [
  "Não quer mudar o uso do pasto agora",
  "Achou o pagamento baixo",
  "Vai vender ou arrendar a terra",
  "Já negocia com outro projeto",
  "Prefere esperar o título sair",
]
const CANAIS = ["WhatsApp", "carta", "e-mail"]

/** quantas ondas o dono leva para responder (1 a 3); quem não responde sai no fim do prazo (3 ondas) */
const atraso = (cod: string) => (resposta(cod).nivel === "sem_resposta" ? 3 : 1 + Math.floor(sorteio("prazo:" + cod) * 3))

/** chance de um dono contatado dizer que tem interesse (interessado ou aceite) no exemplo */
const ACEITE_ESPERADO = 0.55

/** resposta de um dono contatado, sorteada pelo código (sempre a mesma) */
function resposta(cod: string): { nivel: NivelInteresse; motivo?: string } {
  const u = sorteio("resposta:" + cod)
  if (u < 0.4) return { nivel: "interessado" }
  if (u < 0.55) return { nivel: "aceite_fase1" }
  if (u < 0.8) return { nivel: "recusou", motivo: MOTIVOS[Math.floor(sorteio("motivo:" + cod) * MOTIVOS.length)] }
  return { nivel: "sem_resposta" }
}

/**
 * O andamento da busca de interesse no instante "agora": a onda 1 sai na hora do pedido e uma nova a cada
 * PREMISSAS.onda_ms. Quem recusa ou não responde sai e entra a próxima (primeiro as de reserva, depois o resto da
 * opção, na mesma ordem); o grupo fecha quando os créditos com dono interessado alcançam a meta.
 */
export function simularAndamento(g: PedidoGuardado, opcao: Opcao, cands: Candidato[], campos: CamposPedido, agora: Date): Andamento {
  const t0 = new Date(g.solicitado!.em).getTime()
  const ondaMs = ondaAtual()
  const ondasPassadas = Math.max(0, Math.floor((agora.getTime() - t0) / ondaMs)) + 1
  const contas = new Map(filtrar(cands, campos).map((k) => [k.c.cod_imovel, k]))
  // fila: o lote, as reservas, depois o resto da opção na mesma ordem
  const lote = opcao.itens.filter((i) => i.papel === "lote").map((i) => i.cod_imovel)
  const fila = [
    ...opcao.itens.filter((i) => i.papel === "reserva").map((i) => i.cod_imovel),
    ...ordenar([...contas.values()], opcao.id, campos)
      .map((k) => k.c.cod_imovel)
      .filter((c) => !opcao.itens.some((i) => i.cod_imovel === c)),
  ]
  const estado = new Map<string, { nivel: NivelInteresse; onda: number; trocou: string | null; motivo?: string }>()
  // quem já foi contatado antes (por outro motivo) é contatado de novo; interessado, aceite e contrato valem como estão
  const inicial = (cod: string): NivelInteresse => {
    const n = contas.get(cod)?.c.interesse ?? "sem_contato"
    return n === "contatado" ? "sem_contato" : n
  }
  for (const cod of lote) estado.set(cod, { nivel: inicial(cod), onda: 0, trocou: null })
  const grupo = [...lote]
  const valor = (cod: string) => {
    const k = contas.get(cod)
    return k ? naMeta(k, campos) : 0
  }
  const ondas: Andamento["ondas"] = []
  const sairam: string[] = []
  let prontoEm: string | null = null
  let faltou = false
  for (let n = 1; n <= ondasPassadas; n++) {
    const quando = new Date(t0 + (n - 1) * ondaMs).toISOString()
    // 1. quem foi contatado na onda anterior responde; quem já aceitou pode fechar contrato
    for (const cod of [...grupo]) {
      const e = estado.get(cod)!
      if (e.nivel === "contatado" && e.onda > 0 && n - e.onda >= atraso(cod)) {
        const r = resposta(cod)
        e.nivel = r.nivel
        e.motivo = r.motivo
      } else if (e.nivel === "aceite_fase1" && e.onda > 0 && n - e.onda >= 3 && sorteio("contrato:" + cod) < 0.35) e.nivel = "contrato_firme"
      if (e.nivel === "recusou" || e.nivel === "sem_resposta") {
        grupo.splice(grupo.indexOf(cod), 1)
        sairam.push(cod)
      }
    }
    const comInteresse = grupo.filter((c) => nivel(estado.get(c)!.nivel) >= nivel("interessado")).reduce((s, c) => s + valor(c), 0)
    if (!prontoEm && comInteresse >= campos.meta.valor) prontoEm = quando
    // o otimizador puxa mais fazendas (primeiro as de reserva, depois o resto da opção) até a meta caber na chance
    // de aceite esperada de quem ainda não respondeu: contata bem mais do que a meta pede
    if (!prontoEm) {
      const pendente = () => grupo.filter((c) => nivel(estado.get(c)!.nivel) < nivel("interessado")).reduce((s, c) => s + valor(c), 0)
      let entra: string | undefined
      while (comInteresse + pendente() * ACEITE_ESPERADO < campos.meta.valor && fila.length) {
        while ((entra = fila.shift()) && estado.has(entra));
        if (!entra) break
        grupo.push(entra)
        // quem entra depois de uma recusa aparece no mapa como troca
        estado.set(entra, { nivel: inicial(entra), onda: 0, trocou: sairam.shift() ?? null })
      }
    }
    // 2. contata quem ainda não foi contatado (com o grupo pronto, para de contatar)
    if (!prontoEm) {
      const novos = grupo.filter((c) => estado.get(c)!.nivel === "sem_contato")
      for (const c of novos) Object.assign(estado.get(c)!, { nivel: "contatado", onda: n })
      if (novos.length) ondas.push({ numero: ondas.length + 1, data: quando, contatados: novos.length, canais: n >= 3 ? [...CANAIS, "visita de parceiro local"] : CANAIS })
      else if (!grupo.some((c) => estado.get(c)!.nivel === "contatado") && !fila.length) faltou = true
    }
  }
  const soma = (minimo: NivelInteresse) => grupo.filter((c) => nivel(estado.get(c)!.nivel) >= nivel(minimo)).reduce((s, c) => s + valor(c), 0)
  const todos = [...estado]
  const motivos = new Map<string, number>()
  for (const [, e] of todos) if (e.nivel === "recusou" && e.motivo) motivos.set(e.motivo, (motivos.get(e.motivo) ?? 0) + 1)
  const comInteressado = soma("interessado")
  const status: StatusPedido = prontoEm ? "grupo_pronto" : faltou ? "faltou" : "buscando_interesse"
  return {
    pedido: g.id,
    status,
    meta: campos.meta.valor,
    com_interessado: Math.round(comInteressado),
    com_aceite: Math.round(soma("aceite_fase1")),
    com_contrato: Math.round(soma("contrato_firme")),
    ondas,
    contatados: todos.filter(([, e]) => e.onda > 0).length,
    recusas: todos.filter(([, e]) => e.nivel === "recusou").length,
    sem_resposta: todos.filter(([, e]) => e.nivel === "sem_resposta").length,
    motivos: [...motivos].map(([motivo, fazendas]) => ({ motivo, fazendas })).sort((a, b) => b.fazendas - a.fazendas),
    fazendas: todos
      .filter(([cod]) => contas.has(cod))
      .map(([cod, e]) => ({ ...item(contas.get(cod)!, grupo.includes(cod) ? "lote" : "reserva", e.trocou), interesse: e.nivel })),
    grupo_pronto_em: prontoEm,
    proxima_onda_em: status === "buscando_interesse" ? new Date(t0 + ondasPassadas * ondaMs).toISOString() : null,
    faltou: faltou
      ? {
          falta: Math.max(0, Math.round(campos.meta.valor - comInteressado)),
          afrouxar: ["Aceitar mais caminhos da terra", "Abrir a área do pedido", "Aumentar o custo máximo por crédito"],
        }
      : null,
  }
}

/** o intervalo entre ondas: o teste de tela pode encurtar (localStorage raiz.exemplo.onda_ms) */
let ondaPersonalizada: number | null = null
export const mudarOnda = (ms: number | null) => {
  ondaPersonalizada = ms
}
const ondaAtual = () => ondaPersonalizada ?? PREMISSAS.onda_ms

/** grupo fechado: as fazendas com dono interessado ou mais */
export function grupoDe(a: Andamento): string[] {
  return a.fazendas.filter((f) => nivel(f.interesse) >= nivel("interessado")).map((f) => f.cod_imovel)
}

// ---- reserva --------------------------------------------------------------------------------------------------------

export function cobrancaDe(g: PedidoGuardado, hectaresAgora: number): Cobranca {
  const hectaresGrupo = g.reserva?.hectares ?? hectaresAgora
  const valor = g.reserva?.valor_brl ?? Math.max(PREMISSAS.reserva_minima_brl, Math.round(hectaresGrupo * PREMISSAS.reserva_brl_ha))
  const criada = new Date(g.reserva?.criada_em ?? g.criado_em)
  return {
    pedido: g.id,
    valor_brl: valor,
    hectares: Math.round(hectaresGrupo),
    prazo_dias: PREMISSAS.prazo_reserva_dias,
    abatimento:
      "A reserva é abatida da conexão por hectare quando o contrato fechar. Se o prazo vencer sem contrato, o grupo volta para a base.",
    // não é um Pix de verdade: o back-end gera o código do banco; este texto não paga nada
    pix: g.reserva
      ? { copia_e_cola: `EXEMPLO-SEM-VALOR-RAIZ-RESERVA-${g.id.toUpperCase()}`, expira_em: new Date(criada.getTime() + 30 * 60_000).toISOString() }
      : null,
    pago: !!g.reserva?.pago_em,
    reservado_ate: g.reserva?.pago_em ? fimDaReserva(g.reserva.pago_em) : null,
    exemplo: true,
  }
}

export { ORDEM_INTERESSE, nivel as nivelDeInteresse }
