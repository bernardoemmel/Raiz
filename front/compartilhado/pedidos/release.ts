/** Apenas o contrato revisado publico_lotes v1; snapshots completos ou antigos permanecem privados. */
import type { Faixa, IdOpcao, OpcaoPublicada, PublicacaoLote } from "./tipos"
import { documentoEmIdentificador } from "../privacidade"

const IDS: IdOpcao[] = ["barata", "segura", "compacta"]
const objeto = (v: unknown): Record<string, unknown> => v && typeof v === "object" && !Array.isArray(v) ? v as Record<string, unknown> : {}
const numero = (v: unknown): number | null => typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : null
const contagem = (v: unknown) => numero(v) !== null && Number.isInteger(v) ? v as number : null
function faixa(v: unknown): Faixa | null {
  const o = objeto(v), p10 = numero(o.p10), p50 = numero(o.p50), p90 = numero(o.p90)
  return p10 !== null && p50 !== null && p90 !== null && p10 <= p50 && p50 <= p90 ? { p10, p50, p90 } : null
}

function ausente(): PublicacaoLote {
  return {
    contrato: "publico_lotes", versao: 1, estado: "ausente",
    aviso: "O resumo dos três lotes ainda não está disponível. A composição, o desenho das fazendas e a diligência exigem a API autenticada.",
    fonte: "https://github.com/bernardoemmel/Raiz/blob/main/docs/dados-publicados.md",
    atualizado_em: null, cenario: "central_r11", modelo_versao: null, uf: "PA",
    volume_creditos: null, preco_contrato_usd: null, pedido_recalculado: false,
    base: { fazendas: null, hectares: null, creditos: { p10: null, p50: null, p90: null },
      observacao: "Cobertura regional publicada. Os três lotes são alternativas e não devem ser somados." },
    cobertura: { municipios: null, estados: null, fazendas: null, hectares: null }, opcoes: [],
  }
}

/** Segunda lista positiva, aplicada tanto no build como no navegador. Nunca repassa textos livres da origem. */
export function projetarPublicacaoLote(valor: unknown): PublicacaoLote {
  const v = objeto(valor), vazio = ausente()
  if (v.contrato !== "publico_lotes" || v.versao !== 1 || v.estado !== "publicado" || v.uf !== "PA" || v.cenario !== "central_r11") return vazio
  if (typeof v.modelo_versao !== "string" || !/^[A-Za-z0-9_.+-]{1,100}$/.test(v.modelo_versao)
    || documentoEmIdentificador(v.modelo_versao)
    || typeof v.atualizado_em !== "string" || !/^\d{4}-\d{2}-\d{2}T/.test(v.atualizado_em) || !Number.isFinite(Date.parse(v.atualizado_em))) return vazio
  if (!Array.isArray(v.opcoes) || v.opcoes.length !== IDS.length || new Set(v.opcoes.map(o => objeto(o).id)).size !== IDS.length) return vazio
  const meta = numero(v.volume_creditos)
  if (meta === null || meta <= 0 || numero(v.preco_contrato_usd) === null) return vazio
  const opcoes: OpcaoPublicada[] = []
  for (const id of IDS) {
    const o = objeto(v.opcoes.find(o => objeto(o).id === id))
    if (o.id !== id) return vazio
    const fazendas = contagem(o.fazendas), suficiente = fazendas !== null && fazendas >= 5
    const t = objeto(o.terra_pronta), pronto = suficiente ? numero(t.creditos_p50) : null
    opcoes.push({ id, fazendas, creditos: suficiente ? faixa(o.creditos) : null,
      hectares: suficiente ? numero(o.hectares) : null, custo_usd_credito: suficiente ? numero(o.custo_usd_credito) : null,
      terra_pronta: { creditos_p50: pronto, fracao_meta: pronto === null ? null : Math.min(1, pronto / meta) } })
  }
  const c = objeto(v.cobertura)
  const cobertura = { municipios: contagem(c.municipios), estados: contagem(c.estados), fazendas: contagem(c.fazendas), hectares: numero(c.hectares) }
  return { ...vazio, estado: "publicado", atualizado_em: new Date(v.atualizado_em).toISOString(), modelo_versao: v.modelo_versao,
    volume_creditos: meta, preco_contrato_usd: numero(v.preco_contrato_usd), cobertura, opcoes,
    aviso: "Resumo do cenário publicado. Os filtros do novo pedido não recalculam estes lotes. Composição, desenho, tabela por fazenda e diligência ficam na área autenticada.",
    base: { ...vazio.base, fazendas: cobertura.fazendas, hectares: cobertura.hectares } }
}

export const lerPublicacaoLote = projetarPublicacaoLote
