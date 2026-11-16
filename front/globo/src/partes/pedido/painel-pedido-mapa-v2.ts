import type { Geo } from "../../../../compartilhado/dados/tipos"
import { lerPublicacaoLote } from "../../../../compartilhado/pedidos/release"
import type { Faixa, IdOpcao, Pedido, PublicacaoLote } from "../../../../compartilhado/pedidos/tipos"

export const OPCOES_MAPA_V2: { id: IdOpcao; nome: string }[] = [
  { id: "barata", nome: "Mais barato" },
  { id: "segura", nome: "Mais seguro" },
  { id: "compacta", nome: "Mais compacto" },
]

interface SelecaoComum {
  opcaoId: IdOpcao
  rotulo: string
  uf: string | null
  hectares: number | null
  meta: number | null
}

/** O ramo público não transporta CAR, coordenadas, H3 ou qualquer composição de lote. */
export type SelecaoPedidoMapaV2 =
  | (SelecaoComum & { origem: "publicacao" })
  | (SelecaoComum & {
    origem: "api"
    pedidoId: string
    fazendas: { cod_imovel: string; geometria: Geo["features"][number]["geometry"] }[]
  })

export interface OpcaoMapaV2 {
  id: IdOpcao
  nome: string
  fazendas: number | null
  hectares: number | null
  creditos: Faixa | null
  custo: number | null
  terraPronta: number | null
  selecao: SelecaoPedidoMapaV2
}

export interface PedidoMapaV2 {
  origem: "publicacao" | "api"
  meta: number | null
  unidade: string
  uf: string | null
  preco: number | null
  atualizadoEm: string | null
  versao: string | null
  opcoes: OpcaoMapaV2[]
  publicado: boolean
  fonte: string | null
  pedidoId: string | null
}

const numero = (n: unknown): number | null => typeof n === "number" && Number.isFinite(n) && n >= 0 ? n : null
const faixaValida = (f: Faixa | null): Faixa | null => f && numero(f.p10) !== null && numero(f.p50) !== null && numero(f.p90) !== null && f.p10 <= f.p50 && f.p50 <= f.p90 ? f : null

/** Lê apenas a projeção pública já revisada. Um formato antigo/completo nunca vira painel aberto. */
export async function carregarPublicacaoMapaV2(base: string, sinal?: AbortSignal, transporte: typeof fetch = fetch): Promise<PublicacaoLote> {
  const raiz = base.endsWith("/") ? base : `${base}/`
  const resposta = await transporte(`${raiz}amostra/lote_PA_central_r11.json`, { signal: sinal })
  if (!resposta.ok) throw new Error("Não foi possível carregar os resumos publicados dos lotes. Tente novamente.")
  const valor: unknown = await resposta.json()
  if (!valor || typeof valor !== "object" || !("contrato" in valor) || valor.contrato !== "publico_lotes" || !("versao" in valor) || valor.versao !== 1) {
    throw new Error("O arquivo de lotes tem um formato incompatível. O painel aceita somente o resumo público revisado.")
  }
  const publicacao = lerPublicacaoLote(valor)
  if ("estado" in valor && valor.estado === "publicado" && publicacao.estado !== "publicado") {
    throw new Error("O resumo de lotes não passou pela validação de versão, data e opções. Os números não foram exibidos.")
  }
  return publicacao
}

export function modeloPublicacaoMapaV2(p: PublicacaoLote): PedidoMapaV2 {
  // Reaplica a lista positiva inclusive quando o chamador já tipou o objeto.
  const seguro = lerPublicacaoLote(p)
  return {
    origem: "publicacao", meta: seguro.volume_creditos, unidade: "créditos", uf: seguro.estado === "publicado" ? seguro.uf : null,
    preco: seguro.preco_contrato_usd, atualizadoEm: seguro.atualizado_em, versao: seguro.modelo_versao,
    publicado: seguro.estado === "publicado", fonte: seguro.fonte, pedidoId: null,
    opcoes: OPCOES_MAPA_V2.flatMap(({ id, nome }) => {
      const o = seguro.opcoes.find(item => item.id === id)
      return o ? [{
        id, nome, fazendas: o.fazendas, hectares: o.hectares, creditos: o.creditos, custo: o.custo_usd_credito,
        terraPronta: o.terra_pronta.fracao_meta,
        selecao: { origem: "publicacao" as const, opcaoId: id, rotulo: nome, uf: seguro.uf, hectares: o.hectares, meta: seguro.volume_creditos },
      }] : []
    }),
  }
}

/** Só recebe um pedido da API com sessão atual; demonstrações e envelopes públicos são recusados. */
export function modeloApiMapaV2(p: Pedido, sessaoApiAtiva: boolean): PedidoMapaV2 | null {
  if (!sessaoApiAtiva || p.exemplo || p.publicacao) return null
  const uf = p.campos.onde.ufs.length === 1 ? p.campos.onde.ufs[0] : null
  const meta = numero(p.campos.meta.valor)
  return {
    origem: "api", meta, uf, unidade: p.campos.meta.tipo === "creditos" ? "créditos" : p.campos.meta.tipo === "hectares" ? "hectares" : "t FLAG/ano",
    preco: numero(p.campos.dinheiro.custo_max_usd_credito), atualizadoEm: p.criado_em, versao: p.versao_modelo,
    publicado: true, fonte: null, pedidoId: p.id,
    opcoes: OPCOES_MAPA_V2.flatMap(({ id, nome }) => {
      const o = p.opcoes.find(item => item.id === id)
      return o ? [{
        id, nome, fazendas: numero(o.fazendas), hectares: numero(o.hectares), creditos: faixaValida(o.creditos), custo: numero(o.custo_usd_credito.p50),
        // O contrato privado não fornece a fração de créditos da meta com terra pronta.
        terraPronta: null,
        selecao: {
          origem: "api" as const, opcaoId: id, rotulo: nome, uf, hectares: numero(o.hectares), meta, pedidoId: p.id,
          fazendas: o.itens.flatMap(f => f.ficha_liberada && f.geometria && ["Polygon", "MultiPolygon"].includes(f.geometria.type)
            ? [{ cod_imovel: f.cod_imovel, geometria: structuredClone(f.geometria) }] : []),
        },
      }] : []
    }),
  }
}

/** Escala comum às alternativas: nenhuma constante de volume ou posição vem da maquete. */
export function escalaFaixasMapaV2(opcoes: Pick<OpcaoMapaV2, "creditos">[]): { minimo: number; maximo: number } | null {
  const faixas = opcoes.map(o => faixaValida(o.creditos)).filter((f): f is Faixa => f !== null)
  if (!faixas.length) return null
  return { minimo: 0, maximo: Math.max(...faixas.map(f => f.p90)) }
}

export function posicoesFaixaMapaV2(faixa: Faixa | null, escala: ReturnType<typeof escalaFaixasMapaV2>) {
  const f = faixaValida(faixa)
  if (!f || !escala) return null
  const amplitude = escala.maximo - escala.minimo
  const percentual = (n: number) => amplitude > 0 ? Math.min(100, Math.max(0, (n - escala.minimo) / amplitude * 100)) : 0
  return { p10: percentual(f.p10), p50: percentual(f.p50), p90: percentual(f.p90) }
}

/** Desenho é critério explícito, nunca o recorte implícito de um lote já publicado. */
export function anelPedidoMapaV2(geo: Geo | null | undefined): [number, number][] | null {
  if (!geo || geo.features.length !== 1 || geo.features[0].geometry.type !== "Polygon") return null
  const coordenadas = geo.features[0].geometry.coordinates
  if (!Array.isArray(coordenadas) || coordenadas.length !== 1 || !Array.isArray(coordenadas[0])) return null
  const anel: unknown[] = coordenadas[0]
  if (anel.length < 4 || !anel.every(p => Array.isArray(p) && p.length === 2 && typeof p[0] === "number" && typeof p[1] === "number" && Number.isFinite(p[0]) && Number.isFinite(p[1]) && Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 90)) return null
  const pontos = anel as [number, number][]
  if (pontos[0][0] !== pontos.at(-1)![0] || pontos[0][1] !== pontos.at(-1)![1]) return null
  if (new Set(pontos.slice(0, -1).map(p => p.join(","))).size < 3) return null
  return pontos.map(([lon, lat]) => [lon, lat])
}
