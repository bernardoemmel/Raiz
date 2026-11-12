import type { Geo } from "./dados/tipos"

/** Contrato da prospecção: somente terra. As permissões e os créditos pertencem ao servidor. */
export interface MedidaTerra {
  valor: number | null
  unidade: string
  fonte: string
  data_referencia: string | null
  data_corte: string | null
  estimado: boolean
}
export interface FichaTerraDados {
  versao: number
  codigo_car: string
  municipio: string
  cod_ibge: string | number | null
  uf: string
  bioma: string | null
  data_corte: string | null
  area_total: MedidaTerra
  area_restauravel: MedidaTerra
  caminho_terra: { codigo: string; rotulo: string; situacao: string; fonte: string; data_referencia: string | null; regra_versao: string | null }
  pendencias: { codigo: string; texto: string }[]
  sobreposicoes: { codigo: string; rotulo: string; area: MedidaTerra }[]
  embargos: { area: MedidaTerra; situacao: string }
  serie_uso: { ano: number; mata: MedidaTerra; pasto: MedidaTerra; lavoura: MedidaTerra; agua: MedidaTerra }[]
  perdas: { ano: number | null; tipo: string; rotulo: string; area: MedidaTerra }[]
  credito: { p10: MedidaTerra; p50: MedidaTerra; p90: MedidaTerra; base: string; metodo: string; versao_modelo: string | null }
  tir: { p10: MedidaTerra; p50: MedidaTerra; p90: MedidaTerra; tipo: string }
  risco: { nivel: string | null; fonte: string; data_referencia: string | null; regra_versao: string | null }
  agrupamento: { pequena: boolean | null; grupo_id: string | null; imoveis: MedidaTerra; area: MedidaTerra }
}
export interface VisualTerra {
  imovel: Geo
  mascara: Geo
  camadas: Geo
  fonte_perimetro: string
  fonte_camadas: string
  data_referencia: string | null
  data_corte: string | null
  avisos: string[]
}
export type SateliteTerra = { disponivel: false; aviso: string } | {
  disponivel: true
  caixa: [number, number, number, number]
  data_cena: string
  satelite: string
  credito: string
  largura: number
  altura: number
}
export interface FiltrosProspeccao {
  q?: string
  uf?: string
  cod_ibge?: string
  bioma?: string
  area_min_ha?: string
  area_max_ha?: string
  caminho_terra?: string
  situacao_terra?: string
  credito_min?: string
  credito_max?: string
  risco?: string
}
export interface ResumoTerra {
  codigo_car: string
  uf: string
  cod_ibge: string | number
  municipio: string
  bioma: string | null
  area_ha: number | null
  area_restauravel_ha: number | null
  caminho_terra: string | null
  situacao_terra: string | null
  risco: string | null
  pequena: boolean | null
  agrupar: boolean
  credito_p10: number | null
  credito_p50: number | null
  credito_p90: number | null
  data_corte: string | null
  fonte: string
}
export interface BuscaProspeccao {
  total: number | null
  contagem?: string
  pagina: number
  limite: number
  tem_mais: boolean
  total_agrupamentos?: number
  agrupamentos_limitados?: boolean
  totais: {
    fazendas: number | null
    area_ha: number | null
    area_restauravel_ha: number | null
    credito_p10: number | null
    credito_p50: number | null
    credito_p90: number | null
    com_credito: number | null
    pequenas: number | null
    fonte: string
    data_corte_min: string | null
    data_corte_max: string | null
  }
  agrupamentos: { uf: string; cod_ibge: string | number; municipio: string; bioma: string | null; fazendas: number; area_ha: number | null; credito_p50: number | null; criterio: string }[]
  imoveis?: ResumoTerra[]
  aviso: string
}
export interface PlanosConsulta {
  planos: { id: string; nome: string; creditos: number; valor_rs: number }[]
  custo_ficha: number
  unidade: string
  pagamento_disponivel: boolean
  mensagem: string
}
export interface SaldoConsulta { creditos: number; fichas_desbloqueadas: number }
export interface CompraConsulta {
  id: number | string
  plano: string
  creditos: number
  valor_rs: number
  estado: "pendente" | "paga" | "expirada" | "cancelada"
  modo: "producao"
  pix_copia_cola: string | null
  expira_em: string | null
}
export class ErroProspeccao extends Error {
  status: number
  constructor(status: number, mensagem: string) { super(mensagem); this.status = status }
}
export function parametrosProspeccao(filtros: FiltrosProspeccao, pagina = 1): string {
  const params = new URLSearchParams()
  for (const [chave, valor] of Object.entries(filtros)) if (valor?.trim()) params.set(chave, valor.trim())
  params.set("pagina", String(pagina))
  params.set("limite", "20")
  return params.toString()
}
export function fonteProspeccao(api: string | undefined, token: () => string | null) {
  async function pedir<T>(caminho: string, corpo?: unknown, sinal?: AbortSignal, publica = false, imagem = false): Promise<T> {
    if (!api) throw new ErroProspeccao(503, "A ficha completa precisa da conexão com a Raíz. O mapa agregado continua aberto.")
    const sessao = publica ? null : token()
    if (!publica && !sessao) throw new ErroProspeccao(401, "Entre na Raíz para continuar.")
    const resposta = await fetch(`${api.replace(/\/$/, "")}/prospeccao/${caminho}`, {
      method: corpo === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", ...(sessao ? { Authorization: `Bearer ${sessao}` } : {}) },
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
      signal: sinal,
      cache: "no-store",
    })
    if (!resposta.ok) {
      const padrao = resposta.status === 429 ? "Limite de consultas atingido. Aguarde antes de tentar novamente." : resposta.status === 402 ? "Esta ficha precisa ser desbloqueada com um crédito pago." : resposta.status === 401 ? "A sessão acabou. Entre novamente." : "Não foi possível concluir a consulta. Tente novamente."
      const erro = await resposta.json().catch(() => null) as { detail?: unknown } | null
      throw new ErroProspeccao(resposta.status, typeof erro?.detail === "string" ? erro.detail : padrao)
    }
    return (imagem ? resposta.blob() : resposta.json()) as Promise<T>
  }
  return {
    disponivel: !!api,
    agregado: (f: FiltrosProspeccao, sinal?: AbortSignal) => {
      const params = new URLSearchParams(parametrosProspeccao(f))
      params.delete("pagina"); params.delete("limite")
      return pedir<BuscaProspeccao>(`agregado?${params}`, undefined, sinal, true)
    },
    buscar: (f: FiltrosProspeccao, pagina: number, sinal?: AbortSignal) => pedir<BuscaProspeccao>(`busca?${parametrosProspeccao(f, pagina)}`, undefined, sinal),
    ficha: (car: string, sinal?: AbortSignal) => pedir<FichaTerraDados>(`fichas/${encodeURIComponent(car)}`, undefined, sinal),
    visual: (car: string, sinal?: AbortSignal) => pedir<VisualTerra>(`fichas/${encodeURIComponent(car)}/visual`, undefined, sinal),
    satelite: (car: string, sinal?: AbortSignal) => pedir<SateliteTerra>(`fichas/${encodeURIComponent(car)}/visual/satelite`, undefined, sinal),
    imagemSatelite: (car: string, sinal?: AbortSignal) => pedir<Blob>(`fichas/${encodeURIComponent(car)}/visual/satelite.webp`, undefined, sinal, false, true),
    desbloquear: (car: string) => pedir<FichaTerraDados>(`fichas/${encodeURIComponent(car)}/desbloquear`, {}),
    contato: (car: string) => pedir<{ id: number | string; estado: string; criado_em: string; mensagem: string }>("contatos", { codigo_car: car }),
    planos: () => pedir<PlanosConsulta>("planos", undefined, undefined, true),
    saldo: () => pedir<SaldoConsulta>("saldo"),
    comprar: (plano: string, chave: string) => pedir<CompraConsulta>("compras", { plano, chave_idempotencia: chave }),
    compras: () => pedir<CompraConsulta[]>("compras"),
    compra: (id: number | string) => pedir<CompraConsulta>(`compras/${encodeURIComponent(String(id))}`),
  }
}
