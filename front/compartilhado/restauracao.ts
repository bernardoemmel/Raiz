/**
 * Valor para quem restaura com crédito de carbono (o desenvolvedor), lido das colunas de desenvolvedor_<mun>.csv
 * (docs/colunas.md), que o back-end calcula em raiz/restauracao.py. Tudo é estimativa em faixa P10 a P90: a tela
 * sempre mostra o aviso e a faixa, nunca um número solto.
 */

import { num, texto } from "./dados/colunas"
import type { Linha } from "./dados/csv"

export type Modo = "regeneracao_assistida" | "semeadura_direta" | "plantio_total"

export const MODOS: { id: Modo; nome: string; curto: string }[] = [
  { id: "regeneracao_assistida", nome: "Regeneração assistida", curto: "Regeneração" },
  { id: "semeadura_direta", nome: "Semeadura direta (muvuca)", curto: "Semeadura" },
  { id: "plantio_total", nome: "Plantio total de mudas", curto: "Plantio" },
]

export const AVISO =
  "Estimativa da Raíz para orientar a conversa com o desenvolvedor. Não é orçamento nem promessa de crédito: custos, captura e linha de base são premissas a calibrar com dados reais."

export interface Faixa {
  p10: number
  p50: number
  p90: number
}

export interface Marco {
  ano: number
  chancePct: number
}

export type FormaDono = "participacao" | "arrendamento" | "duas_fases"

export interface Restauracao {
  modo: Modo
  nomeModo: string
  areaHa: number
  porModoHa: Record<Modo, number>
  custoHa: Faixa
  capturaHaAno: Faixa
  /** curva (forma da URTX, rodada 11) ou constante (premissas antigas) */
  capturaModelo: string
  capturaTotalHa: number | null
  creditoHaAno: Faixa
  creditoAno: number
  /** créditos líquidos até o fim do contrato (ano 25), por ha */
  creditoContratoHa: Faixa | null
  creditoContrato: number | null
  /** descontos em %, nesta ordem: linha de base, vazamento, reserva e incerteza */
  descontos: { linhaBase: number; linhaBaseMedida: number | null; vazamento: number; reserva: number; incerteza: number }
  marcos: Marco[]
  marcosTodosPct: number | null
  multaEsperadaHa: number | null
  rescisaoPct: number | null
  divida: { fracao: number; rsHa: number; limitadaIcsd: boolean } | null
  dono: {
    forma: FormaDono
    rsHaAno: number | null
    aluguelRef: number | null
    aluguelFonte: string | null
    tirAluguel: number | null
    tirDuasFases: number | null
  }
  precoEquilibrioUsd: number | null
  custoCreditoUsd: number | null
  descontoLinhaBase: number
  descontoLinhaBasePct: number
  regeneraSozinhaPct: number
  linhaBaseFonte: string | null
  vplHa: Faixa
  tirProjetoPct: Faixa
  tirAlavancadaPct: Faixa
  picoCapitalHa: Faixa
  valorDesenvolvedor: number
  lote: {
    id: string
    imoveis: number
    ha: number
    creditosNoPrazo: number
    fechaContrato: boolean
    haParaContrato: number | null
  } | null
  faltou: string[]
  cenario: string
  versao: string | null
}

const TEXTO_FALTOU: Record<string, string> = {
  distancia_mata: "distância do pasto à mata",
  declividade: "declividade",
  chuva: "chuva",
  solo: "solo",
  acesso: "distância da estrada e da cidade",
  fogo: "histórico de fogo",
  idade_pasto: "idade do pasto",
  vigor_pasto: "vigor do pasto",
  linha_base_municipio: "linha de base medida no município",
}

export const textoFaltou = (id: string) => TEXTO_FALTOU[id] ?? id

function faixa(l: Linha, base: string, p50?: string): Faixa | null {
  const m = num(l, p50 ?? `${base}_p50`)
  if (m === null) return null
  const a = num(l, `${base}_p10`) ?? m
  const b = num(l, `${base}_p90`) ?? m
  return { p10: Math.min(a, m), p50: m, p90: Math.max(b, m) }
}

/** Os marcos do ProFloresta+ que a linha traz (marco_<ano>_chance_pct), em ordem de ano. */
export function lerMarcos(l: Linha): Marco[] {
  return Object.keys(l)
    .map((k) => /^marco_(\d+)_chance_pct$/.exec(k))
    .filter((m): m is RegExpExecArray => m !== null)
    .map((m) => ({ ano: Number(m[1]), chancePct: num(l, m[0]) }))
    .filter((m): m is Marco => m.chancePct !== null)
    .sort((a, b) => a.ano - b.ano)
}

/** null quando o município ainda não tem o cálculo (a ficha mostra o estado vazio). */
export function lerRestauracao(l: Linha): Restauracao | null {
  const modo = texto(l, "modo_restauracao") as Modo | null
  const m = MODOS.find((x) => x.id === modo)
  const custo = faixa(l, "custo_restauracao_ha")
  const captura = faixa(l, "captura_tco2_ha_ano")
  const credito = faixa(l, "credito_liquido_tco2_ha_ano", "credito_liquido_tco2_ha_ano")
  const vpl = faixa(l, "vpl_rs_ha")
  const tirP = faixa(l, "tir_projeto_pct")
  const tirA = faixa(l, "tir_alavancada_pct")
  const pico = faixa(l, "pico_capital_proprio_rs_ha")
  if (!m || !custo || !captura || !credito || !vpl || !tirP || !tirA || !pico) return null
  const grupo = texto(l, "grupo_id")
  return {
    modo: m.id,
    nomeModo: m.nome,
    areaHa: num(l, "restauracao_area_ha") ?? 0,
    porModoHa: Object.fromEntries(MODOS.map((x) => [x.id, num(l, `restauracao_${x.id}_ha`) ?? 0])) as Record<Modo, number>,
    custoHa: custo,
    capturaHaAno: captura,
    capturaModelo: texto(l, "captura_modelo") ?? "constante",
    capturaTotalHa: num(l, "captura_total_tco2_ha_p50"),
    creditoHaAno: credito,
    creditoAno: num(l, "credito_liquido_tco2_ano") ?? 0,
    creditoContratoHa: faixa(l, "credito_liquido_tco2_ha_contrato"),
    creditoContrato: num(l, "credito_liquido_tco2_contrato"),
    descontos: {
      linhaBase: num(l, "desconto_linha_base_pct") ?? 0,
      linhaBaseMedida: num(l, "linha_base_medida_pct"),
      vazamento: num(l, "vazamento_pct") ?? 0,
      reserva: num(l, "reserva_risco_pct") ?? 12,
      incerteza: num(l, "incerteza_pct") ?? 10,
    },
    marcos: lerMarcos(l),
    marcosTodosPct: num(l, "marcos_todos_chance_pct"),
    multaEsperadaHa: num(l, "multa_esperada_rs_ha"),
    rescisaoPct: num(l, "rescisao_chance_pct"),
    divida:
      num(l, "divida_fracao") !== null
        ? {
            fracao: num(l, "divida_fracao") ?? 0,
            rsHa: num(l, "divida_rs_ha") ?? 0,
            limitadaIcsd: (texto(l, "divida_limitada_icsd") ?? "").toLowerCase() === "true",
          }
        : null,
    dono: {
      forma: (texto(l, "pagamento_dono") as FormaDono | null) ?? "arrendamento",
      rsHaAno: num(l, "dono_rs_ha_ano"),
      aluguelRef: num(l, "arrendamento_referencia_rs_ha_ano"),
      aluguelFonte: texto(l, "arrendamento_referencia_fonte"),
      tirAluguel: num(l, "tir_projeto_pct_arrendamento"),
      tirDuasFases: num(l, "tir_projeto_pct_duas_fases"),
    },
    precoEquilibrioUsd: num(l, "preco_equilibrio_usd_t"),
    custoCreditoUsd: num(l, "custo_credito_usd"),
    descontoLinhaBase: num(l, "desconto_linha_base") ?? 0,
    descontoLinhaBasePct: num(l, "desconto_linha_base_pct") ?? 0,
    regeneraSozinhaPct: num(l, "linha_base_regenera_pct") ?? 0,
    linhaBaseFonte: texto(l, "linha_base_fonte"),
    vplHa: vpl,
    tirProjetoPct: tirP,
    tirAlavancadaPct: tirA,
    picoCapitalHa: pico,
    valorDesenvolvedor: num(l, "valor_desenvolvedor_rs") ?? 0,
    lote: grupo
      ? {
          id: grupo,
          imoveis: num(l, "grupo_imoveis") ?? 1,
          ha: num(l, "grupo_ha") ?? 0,
          creditosNoPrazo: num(l, "grupo_creditos_prazo") ?? 0,
          fechaContrato: (texto(l, "grupo_fecha_contrato") ?? "").toLowerCase() === "true",
          haParaContrato: num(l, "grupo_ha_para_contrato"),
        }
      : null,
    faltou: (texto(l, "restauracao_faltou") ?? "").split(",").filter(Boolean),
    cenario: texto(l, "restauracao_cenario") ?? "central_r11",
    versao: texto(l, "restauracao_versao"),
  }
}

// --- cenários (raiz/regras/padroes/cenarios_restauracao.yaml) ----------------------------------------------------

export interface DescricaoCenario {
  nome: string
  taxa: string
  financiamento: string
  texto: string
}

const CENTRAL =
  "Rodada 11: contrato de 25 anos do ProFloresta+ com marcos de 12% no ano 7, 30% no 12, 50% no 17, 70% no 22 e 100% no 25 (tolerância de 25%, multas e rescisão), venda a US$ 30 depois do ano 25 até o ano 40, custos oficiais do SFB, captura em curva (forma da URTX), dono pago por 40 anos e Fundo Clima de 35 a 50% do investimento a 4,94% ao ano, 8 anos de carência e dívida até onde o caixa paga 1,3 vez as parcelas."

export const CENARIOS: Record<string, DescricaoCenario> = {
  central_r11: { nome: "Central, US$ 55", taxa: "a 9,2% ao ano", financiamento: "Fundo Clima, até 50% do investimento", texto: CENTRAL },
  central_r11_74: { nome: "Central, US$ 74", taxa: "a 9,2% ao ano", financiamento: "Fundo Clima, até 50% do investimento", texto: CENTRAL },
  estresse_r11: {
    nome: "Estresse, US$ 55",
    taxa: "a 9,2% ao ano",
    financiamento: "Fundo Clima, até 50% do investimento",
    texto: `${CENTRAL} No estresse, linha de base e vazamento de 40%.`,
  },
  otimista_fundador: {
    nome: "Otimista do fundador, US$ 55",
    taxa: "a 12% ao ano",
    financiamento: "80% pelo Fundo Clima",
    texto:
      "Premissas antigas do fundador: US$ 55 por tonelada, contrato de 25 anos com entregas nos anos 7, 12, 17, 22 e 25, sem multa, captura constante, custo de mercado no ano 0, 80% financiado pelo Fundo Clima a 2,3% ao ano, 5 anos de carência e 20 de amortização.",
  },
  otimista_fundador_74: {
    nome: "Otimista do fundador, US$ 74",
    taxa: "a 12% ao ano",
    financiamento: "80% pelo Fundo Clima",
    texto:
      "Premissas antigas do fundador a US$ 74 por tonelada: contrato de 25 anos, sem multa, captura constante, 80% financiado pelo Fundo Clima a 2,3% ao ano.",
  },
}

export const descricaoCenario = (id: string): DescricaoCenario => CENARIOS[id] ?? CENARIOS.central_r11

export const NOMES_DONO: Record<FormaDono, string> = {
  participacao: "parte do crédito mais piso",
  arrendamento: "aluguel fixo por ha",
  duas_fases: "aceite em duas fases",
}

// --- painel do município: ordenar e filtrar pelo valor para quem restaura ---------------------------------------

export type OrdemRestauracao = "area" | "valor" | "vpl_ha" | "tir"

export const ORDENS: { id: OrdemRestauracao; rotulo: string }[] = [
  { id: "area", rotulo: "Área" },
  { id: "valor", rotulo: "Valor para quem restaura" },
  { id: "vpl_ha", rotulo: "Valor por hectare" },
  { id: "tir", rotulo: "Retorno com financiamento" },
]

function chave(r: Restauracao | null, ordem: OrdemRestauracao): number | null {
  if (!r) return null
  if (ordem === "valor") return r.valorDesenvolvedor
  if (ordem === "vpl_ha") return r.vplHa.p50
  if (ordem === "tir") return r.tirAlavancadaPct.p50
  return null
}

/** Ordena (sem cortar ninguém) e filtra pelo modo. Fazenda ainda sem o cálculo vai para o fim. */
export function ordenarFiltrar<T extends { linha: Linha }>(lista: T[], ordem: OrdemRestauracao, modo: Modo | null): T[] {
  const comR = lista.map((i) => ({ i, r: lerRestauracao(i.linha) }))
  const filtrada = modo ? comR.filter((x) => x.r?.modo === modo) : comR
  if (ordem === "area") return filtrada.map((x) => x.i)
  return [...filtrada]
    .sort((a, b) => {
      const ka = chave(a.r, ordem)
      const kb = chave(b.r, ordem)
      if (ka === null && kb === null) return 0
      if (ka === null) return 1
      if (kb === null) return -1
      return kb - ka
    })
    .map((x) => x.i)
}

// --- números -----------------------------------------------------------------------------------------------------

const dois = new Intl.NumberFormat("pt-BR", { maximumSignificantDigits: 2 })
const inteiro = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 })
const umaCasa = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 })

/** R$ com 2 algarismos significativos: "R$ 14 mil", "R$ 3,5 mil", "R$ 1,2 milhão", "menos R$ 5,9 mil". */
export function fmtReais(n: number): string {
  const a = Math.abs(n)
  const sinal = n < 0 ? "menos " : ""
  if (a >= 1e6) return `${sinal}R$ ${dois.format(a / 1e6)} ${a >= 2e6 ? "milhões" : "milhão"}`
  if (a >= 1e3) return `${sinal}R$ ${dois.format(a / 1e3)} mil`
  return `${sinal}R$ ${inteiro.format(a)}`
}

export const fmtNum1 = (n: number) => umaCasa.format(n)
export const fmtPct1 = (n: number) => `${umaCasa.format(n)}%`

/** "cerca de 7,2 t por ha por ano (de 5,5 a 10,1)": a faixa que o analista lê, com a unidade uma vez só. */
export function fmtFaixa(f: Faixa, fmt: (n: number) => string, unidade = ""): string {
  const u = unidade ? ` ${unidade}` : ""
  return `cerca de ${fmt(f.p50)}${u} (de ${fmt(f.p10)} a ${fmt(f.p90)})`
}
