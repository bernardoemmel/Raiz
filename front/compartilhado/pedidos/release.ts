/** Projeção pública do ponteiro lote_PA_central_r11.json, de raiz/restauracao_rodada.py. */
import { mascarar } from "../privacidade"
import type { CaminhoTerra, DestravadorPublicado, Faixa, IdOpcao, OpcaoPublicada, PublicacaoLote } from "./tipos"

const FONTE = "https://github.com/bernardoemmel/Raiz/releases/tag/dados"
const IDS: IdOpcao[] = ["barata", "segura", "compacta"]
const CAMINHOS: CaminhoTerra[] = ["matricula_conferida", "matricula_a_conferir", "concessao", "assentamento", "posse_em_titulacao"]
type Objeto = Record<string, unknown>
const objeto = (v: unknown): Objeto => v !== null && typeof v === "object" && !Array.isArray(v) ? v as Objeto : {}
const numero = (v: unknown): number | null => typeof v === "number" && Number.isFinite(v) ? v : null
const texto = (v: unknown): string => typeof v === "string" ? mascarar(v).replace(/\b[A-Z]{2}-\d{7}-[A-F\d.-]{32,}\b/gi, "imóvel reservado").slice(0, 1800) : ""
const data = (v: unknown): string | null => typeof v === "string" && /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(v) && Number.isFinite(Date.parse(v)) ? v : null

function faixa(v: unknown): Faixa | null {
  const o = objeto(v)
  const p10 = numero(o.p10), p50 = numero(o.p50), p90 = numero(o.p90)
  return p10 !== null && p50 !== null && p90 !== null && p10 <= p50 && p50 <= p90 ? { p10, p50, p90 } : null
}

const ROTULO_REGULARIZACAO: Record<string, string> = {
  em_titulacao: "Acompanhar a titulação em andamento.",
  pronta_para_pedir: "Conferir os requisitos e pedir a regularização.",
  falta_georreferenciamento: "Concluir o georreferenciamento certificado.",
  pendente: "Resolver as pendências da regularização.",
  impedida: "Conferir os impedimentos da terra; não liberar venda.",
  sem_calculo: "Calcular o caminho de regularização.",
}

const ROTULO_PENDENCIA: Record<string, string> = {
  "terra:matricula_conferida": "Manter a comprovação da matrícula conferida.",
  "terra:matricula_a_conferir": "Conferir a matrícula e a cadeia da terra.",
  "terra:concessao": "Conferir a concessão e a autorização do órgão gestor.",
  "terra:assentamento": "Conferir o título e a anuência para o assentamento.",
  "terra:posse_em_titulacao": "Concluir a titulação e comprovar os direitos sobre a área.",
  dupla_contagem_jurisdicional: "Documentar a exclusão e o período sem dupla contagem jurisdicional.",
  jurisdicional_a_conferir: "Comprovar ausência de sobreposição ou exclusão do programa jurisdicional.",
  clpi: "Comprovar consentimento em consulta livre, prévia e informada, custeada pelo desenvolvedor.",
  reparticao_comunidade: "Comprovar a repartição de créditos, a gestão participativa e a conta da comunidade.",
  criterio_risco_terra: "Conferir a justificativa do risco da terra.",
  criterio_titulo_nota: "Conferir a justificativa da nota do título.",
  criterio_reserva_risco: "Completar o histórico e a justificativa da reserva contra reversão.",
}

function opcao(id: IdOpcao, v: unknown): OpcaoPublicada | null {
  const r = objeto(v)
  if (!Object.keys(r).length) return null
  const certidoes = objeto(r.certidoes), economia = objeto(r.economia), espera = objeto(r.em_espera)
  const caminhos = objeto(certidoes.por_caminho)
  const titulares = numero(r.titulares), reservas = numero(r.reservas)
  const tir = numero(economia.tir_alavancada_pct)
  const destrava: DestravadorPublicado[] = (Array.isArray(r.o_que_destrava) ? r.o_que_destrava.map(objeto) : []).map((x) => ({
    tipo: "salvaguarda", texto: ROTULO_PENDENCIA[String(x.pendencia)] ?? `Conferir a pendência publicada: ${texto(x.pendencia).replace(/_/g, " ")}.`,
    fazendas: numero(x.fazendas), hectares: numero(x.ha), creditos: null, creditos_faixa: faixa(x.creditos), somavel: false,
  }))
  const regularizacao: DestravadorPublicado[] = Object.entries(objeto(espera.por_regularizacao)).filter(([classe]) => classe in ROTULO_REGULARIZACAO).map(([classe, valores]) => {
    const x = objeto(valores)
    return { tipo: "regularizacao", texto: ROTULO_REGULARIZACAO[classe], fazendas: numero(x.fazendas), hectares: numero(x.ha), creditos: numero(x.creditos), creditos_faixa: null, somavel: false }
  })
  if (!regularizacao.length && (numero(espera.fazendas) ?? 0) > 0) {
    regularizacao.push({ tipo: "regularizacao", texto: "Conferir a titulação e as autorizações das áreas em espera.", fazendas: numero(espera.fazendas), hectares: numero(espera.ha), creditos: null, creditos_faixa: null, somavel: false })
  }
  destrava.push(...regularizacao)
  if ((numero(certidoes.certidoes_a_pedir) ?? 0) > 0) {
    destrava.push({ tipo: "certidao", texto: `Pedir ${numero(certidoes.certidoes_a_pedir)!.toLocaleString("pt-BR")} certidões e conferir a cadeia da terra.`, fazendas: numero(certidoes.fazendas_a_pedir), hectares: numero(certidoes.ha_cobertos), creditos: null, creditos_faixa: null, somavel: false })
  }
  return {
    id,
    creditos: faixa(objeto(r.faixa).carteira) ?? faixa(r.creditos_lote_faixa),
    tir_p50: tir === null ? null : tir / 100,
    custo_usd_credito: numero(r.custo_credito_usd_medio),
    hectares: numero(r.ha_lote),
    fazendas: titulares !== null && reservas !== null ? titulares + reservas : null,
    pequenas: numero(r.pequenas),
    reservas,
    pendencias_terra: CAMINHOS.filter((c) => c !== "matricula_conferida" && c !== "concessao" && c in caminhos).map((caminho) => {
      const x = objeto(caminhos[caminho])
      return { caminho, fazendas: numero(x.fazendas), hectares: numero(x.ha) }
    }),
    destrava,
    o_que_falta: Array.isArray(r.o_que_falta) ? r.o_que_falta.map(texto).filter(Boolean) : [],
  }
}

/** Lista explícita: nenhum CSV de fazenda, CAR, matrícula, folha de contato ou endereço de pacote é publicado. */
export function projetarPublicacaoLote(valor: unknown): PublicacaoLote {
  const m = objeto(valor)
  const resumos = objeto(m.resumos)
  const opcoes = IDS.map((id) => opcao(id, resumos[id])).filter((o): o is OpcaoPublicada => o !== null)
  const publicado = m.uf === "PA" && m.cenario === "central_r11" && opcoes.length === 3
  const r = objeto(resumos.barata), oferta = objeto(r.oferta)
  return {
    estado: publicado ? "publicado" : "ausente",
    aviso: publicado
      ? "Cenário central_r11 publicado no Release. Créditos, área e fazendas incluem o lote e as reservas. Os filtros deste pedido ainda não foram recalculados; a API autenticada executa o pedido exato. Estimativa de triagem, sem crédito emitido nem venda liberada."
      : "As três opções do chat Lote e números ainda não foram publicadas no Release em um conjunto completo. A base territorial continua disponível; créditos, TIR e lotes aguardam o cálculo publicado.",
    fonte: FONTE,
    atualizado_em: publicado ? data(m.publicado_em) ?? data(r.data) : null,
    cenario: "central_r11",
    modelo_versao: publicado ? texto(m.modelo_versao) || null : null,
    uf: "PA",
    volume_creditos: publicado ? numero(r.volume_creditos) : null,
    preco_contrato_usd: publicado ? numero(r.preco_contrato_usd) : null,
    pedido_recalculado: false,
    base: {
      fazendas: publicado ? numero(oferta.fazendas_terra_pronta) : null,
      // O contrato informa a área de toda a oferta, não a da parcela com terra pronta. Não misturar os recortes.
      hectares: null,
      creditos: { p10: null, p50: publicado ? numero(oferta.creditos_terra_pronta) : null, p90: null },
      observacao: "Oferta com caminho da terra pronta no cenário publicado. P10, P90 e hectares desse recorte não constam do resumo. Não representa o resultado dos novos filtros.",
    },
    cobertura: {
      municipios: publicado ? numero(m.municipios_calculados) : null,
      estados: publicado ? 1 : null,
      fazendas: publicado ? numero(m.imoveis_calculados) : null,
      hectares: publicado ? numero(oferta.ha) : null,
    },
    opcoes: publicado ? opcoes : [],
  }
}

/** Revalida o arquivo projetado ao ler no navegador; propriedades futuras ou inesperadas não passam à tela. */
export function lerPublicacaoLote(valor: unknown): PublicacaoLote {
  const p = objeto(valor)
  if (p.estado !== "publicado") return projetarPublicacaoLote(null)
  const recebidas = Array.isArray(p.opcoes) ? p.opcoes.map(objeto).filter((x) => IDS.includes(x.id as IdOpcao)) : []
  if (recebidas.length !== 3 || new Set(recebidas.map((x) => x.id)).size !== 3 || p.pedido_recalculado !== false || p.uf !== "PA" || p.cenario !== "central_r11") {
    return projetarPublicacaoLote(null)
  }
  // Repete a lista explícita no navegador: campos futuros não viram uma abertura acidental dos detalhes.
  const opcoes: OpcaoPublicada[] = recebidas.map((o) => ({
    id: o.id as IdOpcao, creditos: faixa(o.creditos), tir_p50: numero(o.tir_p50), custo_usd_credito: numero(o.custo_usd_credito),
    hectares: numero(o.hectares), fazendas: numero(o.fazendas), pequenas: numero(o.pequenas), reservas: numero(o.reservas),
    pendencias_terra: (Array.isArray(o.pendencias_terra) ? o.pendencias_terra.map(objeto) : []).filter((x) => CAMINHOS.includes(x.caminho as CaminhoTerra)).map((x) => ({
      caminho: x.caminho as CaminhoTerra, fazendas: numero(x.fazendas), hectares: numero(x.hectares),
    })),
    destrava: (Array.isArray(o.destrava) ? o.destrava.map(objeto) : []).map((x) => ({ tipo: x.tipo === "salvaguarda" || x.tipo === "certidao" ? x.tipo : "regularizacao", texto: texto(x.texto), fazendas: numero(x.fazendas), hectares: numero(x.hectares), creditos: numero(x.creditos), creditos_faixa: faixa(x.creditos_faixa), somavel: false })),
    o_que_falta: Array.isArray(o.o_que_falta) ? o.o_que_falta.map(texto).filter(Boolean) : [],
  }))
  const base = objeto(p.base), creditos = objeto(base.creditos), cobertura = objeto(p.cobertura)
  return {
    estado: "publicado", aviso: texto(p.aviso), fonte: FONTE, atualizado_em: data(p.atualizado_em), cenario: "central_r11", modelo_versao: texto(p.modelo_versao) || null, uf: "PA",
    volume_creditos: numero(p.volume_creditos), preco_contrato_usd: numero(p.preco_contrato_usd), pedido_recalculado: false,
    base: { fazendas: numero(base.fazendas), hectares: numero(base.hectares), creditos: { p10: numero(creditos.p10), p50: numero(creditos.p50), p90: numero(creditos.p90) }, observacao: texto(base.observacao) },
    cobertura: { municipios: numero(cobertura.municipios), estados: numero(cobertura.estados), fazendas: numero(cobertura.fazendas), hectares: numero(cobertura.hectares), ...(texto(cobertura.observacao) ? { observacao: texto(cobertura.observacao) } : {}) }, opcoes,
  }
}
