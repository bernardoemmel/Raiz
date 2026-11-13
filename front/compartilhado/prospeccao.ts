import type { PastaFiadorDados, HistoricoPasta, PastasDaFichaDados } from "./pasta-fiador"
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
export interface EvidenciaCompromisso {
  fonte_id: string; objeto_id: string; registro: string; tipo: string; situacao: string; certeza: string
  fonte_url: string | null; data_referencia: string | null; observado_em: string | null
  inicio: string | null; fim: string | null; area: MedidaTerra
}
export interface TerraComprometidaDados {
  versao: number; situacao: string; area_confirmada: MedidaTerra; area_indicio: MedidaTerra
  evidencias: EvidenciaCompromisso[]; contexto_jurisdicional: EvidenciaCompromisso[]
  cobertura: { fonte_id: string; estado: string; escopo: string; recorte: string; bbox: number[] | null; url: string | null; licenca: string; data_referencia: string | null; consultado_em: string | null }[]
  aviso: string
}
export interface MudancaTerra {
  tipo: string; campo: string; antes: unknown; depois: unknown
  fonte: string; data_referencia: string | null; data_corte: string | null
}
export interface VersaoFicha { id: number; hash: string; registrada_em: string }
export interface MudancasConsulta {
  primeira_consulta: boolean; consulta_anterior_em: string | null
  versao_anterior_id: number | null; versao_atual_id: number; mudancas: MudancaTerra[]
}
export interface HistoricoFicha {
  codigo_car: string
  historico: { id: number; origem: string; registrada_em: string; versao_id: number; anterior_id: number | null; mudancas: MudancaTerra[]; hash_conteudo: string }[]
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
  terra_comprometida?: TerraComprometidaDados
  versao_ficha?: VersaoFicha
  o_que_mudou?: MudancasConsulta
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
  metodo: string
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
  ficha_liberada?: boolean
  situacao_basica?: "apto" | "com_pendencia" | "nao_apto"
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
  escopo_metricas?: "fichas_liberadas" | "agregado_regional"
  total: number | null
  contagem?: string
  pagina: number
  limite: number
  tem_mais: boolean
  total_agrupamentos?: number
  agrupamentos_limitados?: boolean
  totais: {
    fichas_liberadas?: number
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
  agrupamentos: { fichas_liberadas?: number; uf: string; cod_ibge: string | number; municipio: string; bioma: string | null; fazendas: number; area_ha: number | null; credito_p50: number | null; criterio: string }[]
  imoveis?: ResumoTerra[]
  aviso: string
}
export interface PlanosConsulta {
  planos: { id: string; nome: string; creditos: number; valor_rs: number | null; status?: "provisorio" | "aprovado"; aviso_preco?: string
    modalidade?: "por_ficha" | "por_lote" | "assinatura"; status_quantidade?: "proposta" | "aprovada"
    pagamento_disponivel?: boolean; cobranca_implementada?: boolean; renovacao_automatica?: boolean
    creditos_por_ciclo?: number; ciclo_meses?: number; status_ciclo?: "proposta" | "aprovado"; aviso_modalidade?: string
    validade_creditos_dias?: number | null; acumula_creditos?: boolean | null
    regra_excedentes?: string; regra_cancelamento?: string; regra_reembolso?: string
  }[]
  status?: "provisorio" | "aprovado"
  custo_ficha: number
  unidade: string
  pagamento_disponivel: boolean
  mensagem: string
}
export interface BuscaSalva {
  id: string
  nome: string
  filtros: Partial<Record<keyof FiltrosProspeccao, string | number | null>>
  criada_em: string
  verificada_em: string
}
export interface AvisoBusca {
  id: number
  busca_id: string
  nome_busca: string
  codigo_car: string
  criada_em: string
  lida_em: string | null
  mensagem: string
  tipo?: string
  ficha_liberada?: boolean
  mudancas?: MudancaTerra[]
}
export interface PaginaAvisos { avisos: AvisoBusca[]; proximo_cursor: number | null }

/** A API guarda filtros numéricos como números; formulários usam strings sem inventar mínimos. */
export function filtrosDaBuscaSalva(filtros: BuscaSalva["filtros"]): FiltrosProspeccao {
  const permitidos = ["q", "uf", "cod_ibge", "bioma", "area_min_ha", "area_max_ha", "caminho_terra", "situacao_terra", "credito_min", "credito_max", "risco"]
  return Object.fromEntries(Object.entries(filtros).filter(([chave, valor]) => permitidos.includes(chave) && valor != null && String(valor).trim() !== "").map(([chave, valor]) => [chave, String(valor)]))
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
  retryAfter: number | null
  constructor(status: number, mensagem: string, retryAfter: number | null = null) { super(mensagem); this.status = status; this.retryAfter = retryAfter }
}
export function parametrosProspeccao(filtros: FiltrosProspeccao, pagina = 1): string {
  const params = new URLSearchParams()
  for (const [chave, valor] of Object.entries(filtros)) if (valor?.trim()) params.set(chave, valor.trim())
  params.set("pagina", String(pagina))
  params.set("limite", "20")
  return params.toString()
}
export function fonteProspeccao(api: string | undefined, token: () => string | null) {
  async function respostaDe(caminho: string, corpo?: unknown, sinal?: AbortSignal, publica = false, metodo?: "DELETE"): Promise<Response> {
    if (!api) throw new ErroProspeccao(503, "A ficha completa precisa da conexão com a Raíz. O mapa básico continua aberto.")
    const sessao = publica ? null : token()
    if (!publica && !sessao) throw new ErroProspeccao(401, "Entre na Raíz para continuar.")
    const resposta = await fetch(`${api.replace(/\/$/, "")}/prospeccao/${caminho}`, {
      method: metodo ?? (corpo === undefined ? "GET" : "POST"),
      headers: { "Content-Type": "application/json", ...(sessao ? { Authorization: `Bearer ${sessao}` } : {}) },
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
      signal: sinal,
      cache: "no-store",
    })
    if (!resposta.ok) {
      const padrao = resposta.status === 429 ? "Limite de consultas atingido. Aguarde antes de tentar novamente." : resposta.status === 402 ? "Esta ficha precisa ser desbloqueada com um crédito pago." : resposta.status === 401 ? "A sessão acabou. Entre novamente." : "Não foi possível concluir a consulta. Tente novamente."
      const erro = await resposta.json().catch(() => null) as { detail?: unknown } | null
      const espera = Number(resposta.headers.get("Retry-After"))
      const segundos = Number.isFinite(espera) && espera > 0 ? Math.ceil(espera) : null
      const mensagem = typeof erro?.detail === "string" ? erro.detail : padrao
      throw new ErroProspeccao(resposta.status, segundos && resposta.status === 429 ? `${mensagem} Tente novamente em ${segundos} segundos.` : mensagem, segundos)
    }
    return resposta
  }
  async function pedir<T>(caminho: string, corpo?: unknown, sinal?: AbortSignal, publica = false, metodo?: "DELETE"): Promise<T> {
    return (await respostaDe(caminho, corpo, sinal, publica, metodo)).json() as Promise<T>
  }
  return {
    disponivel: !!api,
    pastasDaFicha: (car: string, sinal?: AbortSignal) => pedir<PastasDaFichaDados>(`fichas/${encodeURIComponent(car)}/pastas`, undefined, sinal),
    pasta: (pedido: string, opcao: string, versao?: string, sinal?: AbortSignal) => pedir<PastaFiadorDados>(`pastas/${encodeURIComponent(pedido)}/${encodeURIComponent(opcao)}${versao ? `?versao_id=${encodeURIComponent(versao)}` : ""}`, undefined, sinal),
    historicoPasta: (pedido: string, opcao: string, sinal?: AbortSignal) => pedir<HistoricoPasta>(`pastas/${encodeURIComponent(pedido)}/${encodeURIComponent(opcao)}/historico`, undefined, sinal),
    exportarPasta: async (pedido: string, opcao: string, sinal?: AbortSignal) => {
      const resposta = await respostaDe(`pastas/${encodeURIComponent(pedido)}/${encodeURIComponent(opcao)}/exportar`, undefined, sinal)
      if (!resposta.headers.get("Content-Type")?.includes("application/zip")) throw new ErroProspeccao(502, "Formato de pasta inválido.")
      return resposta.blob()
    },
    comparar: (codigos_car: string[], sinal?: AbortSignal) => pedir<{ fichas: FichaTerraDados[] }>("comparar", { codigos_car }, sinal),
    historico: (car: string, sinal?: AbortSignal) => pedir<HistoricoFicha>(`fichas/${encodeURIComponent(car)}/historico?limite=20`, undefined, sinal),
    exportar: async (car: string, formato: "json" | "csv", sinal?: AbortSignal) => {
      const resposta = await respostaDe(`fichas/${encodeURIComponent(car)}/exportar?formato=${formato}`, undefined, sinal)
      const tipo = formato === "json" ? "application/json" : "text/csv"
      if (!(resposta.headers.get("content-type") ?? "").includes(tipo)) throw new ErroProspeccao(502, `A Raíz não retornou um arquivo ${formato.toUpperCase()} válido. Tente novamente.`)
      return resposta.blob()
    },
    pdf: async (car: string, sinal?: AbortSignal) => {
      const resposta = await respostaDe(`fichas/${encodeURIComponent(car)}/pdf`, undefined, sinal)
      if (!(resposta.headers.get("content-type") ?? "").includes("application/pdf")) throw new ErroProspeccao(502, "A Raíz não retornou um PDF válido. Tente novamente.")
      return resposta.blob()
    },
    buscasSalvas: (sinal?: AbortSignal) => pedir<BuscaSalva[]>("buscas-salvas", undefined, sinal),
    salvarBusca: (nome: string, filtros: FiltrosProspeccao, sinal?: AbortSignal) => pedir<BuscaSalva>("buscas-salvas", { nome, filtros: Object.fromEntries(Object.entries(filtros).filter(([, v]) => v?.trim())) }, sinal),
    excluirBusca: (id: string, sinal?: AbortSignal) => pedir<{ id: string; excluida: boolean }>(`buscas-salvas/${encodeURIComponent(id)}`, undefined, sinal, false, "DELETE"),
    avisos: (depois = 0, sinal?: AbortSignal) => pedir<PaginaAvisos>(`avisos?depois=${depois}&limite=50`, undefined, sinal),
    lerAviso: (id: number, sinal?: AbortSignal) => pedir<{ id: number; lida_em: string }>(`avisos/${id}/ler`, {}, sinal),
    agregado: (f: FiltrosProspeccao, sinal?: AbortSignal) => {
      const params = new URLSearchParams(parametrosProspeccao(f))
      params.delete("pagina"); params.delete("limite")
      return pedir<BuscaProspeccao>(`agregado?${params}`, undefined, sinal, true)
    },
    buscar: (f: FiltrosProspeccao, pagina: number, sinal?: AbortSignal) => pedir<BuscaProspeccao>(`busca?${parametrosProspeccao(f, pagina)}`, undefined, sinal),
    ficha: (car: string, sinal?: AbortSignal) => pedir<FichaTerraDados>(`fichas/${encodeURIComponent(car)}`, undefined, sinal),
    visual: (car: string, sinal?: AbortSignal) => pedir<VisualTerra>(`fichas/${encodeURIComponent(car)}/visual`, undefined, sinal),
    satelite: (car: string, sinal?: AbortSignal) => pedir<SateliteTerra>(`fichas/${encodeURIComponent(car)}/visual/satelite`, undefined, sinal),
    imagemSatelite: async (car: string, sinal?: AbortSignal) => (await respostaDe(`fichas/${encodeURIComponent(car)}/visual/satelite.webp`, undefined, sinal)).blob(),
    desbloquear: (car: string) => pedir<FichaTerraDados>(`fichas/${encodeURIComponent(car)}/desbloquear`, {}),
    contato: (car: string) => pedir<{ id: number | string; estado: string; criado_em: string; mensagem: string }>("contatos", { codigo_car: car }),
    planos: () => pedir<PlanosConsulta>("planos", undefined, undefined, true),
    saldo: () => pedir<SaldoConsulta>("saldo"),
    comprar: (plano: string, chave: string) => pedir<CompraConsulta>("compras", { plano, chave_idempotencia: chave }),
    compras: () => pedir<CompraConsulta[]>("compras"),
    compra: (id: number | string) => pedir<CompraConsulta>(`compras/${encodeURIComponent(String(id))}`),
  }
}
