/**
 * O pedido de lote da cena-alvo (docs/cena-alvo.md): o cliente pede "1 milhão de créditos" e o mapa monta o melhor
 * lote. Estes tipos são o contrato com o back-end, em JSON:
 *
 *   POST {api}/entrar                         {email}                → {enviado: true}             (manda o link)
 *   POST {api}/entrar/confirmar               {token}                → Sessao
 *   GET  {api}/pedidos                                               → ResumoPedido[]              ("Meus pedidos")
 *   POST {api}/pedidos                        CamposPedido           → Pedido                      (base e 3 opções)
 *   GET  {api}/pedidos/{id}                                          → Pedido
 *   POST {api}/pedidos/{id}/lote              MudancaLote            → Pedido                      (tirar ou trocar)
 *   POST {api}/pedidos/{id}/solicitar-interesse  {opcao}             → Pedido                      (começa as ondas)
 *   GET  {api}/pedidos/{id}/andamento                                → Andamento
 *   POST {api}/pedidos/{id}/reservar                                 → Cobranca                    (Pix da reserva)
 *   GET  {api}/pedidos/{id}/reserva                                  → Cobranca                    (valor, prazo; pago ou não)
 *
 * Autorização: o token da Sessao no cabeçalho (Authorization: Bearer). Nada aqui tem nome, CPF, CNPJ ou contato do
 * dono: o contato passa pela Raíz. Fazenda reservada por outro cliente nunca aparece em resposta de outro cliente.
 */

import type { Geo } from "../dados/tipos"
import type { FichaCredito } from "../ficha-credito"

/** O que conta na meta. */
export type TipoMeta = "creditos" | "hectares" | "flag_t_ano"
export type Cronograma = "profloresta" | "livre" | "proprio"
export type Metodo = "regeneracao_assistida" | "semeadura_direta" | "plantio_total" | "agrofloresta" | "silvipastoril"
/** caminho da terra, do menos ao mais arriscado */
export type CaminhoTerra = "matricula_conferida" | "matricula_a_conferir" | "concessao" | "assentamento" | "posse_em_titulacao"
export type FiltroInteresse = "qualquer" | "interessados" | "com_aceite"
export type Exclusao = "embargo" | "terra_indigena" | "uc_protecao_integral" | "projeto_carbono"

/**
 * Nível de interesse do dono. Só sobe com registro (data, canal e versão do termo):
 * sem_contato → contatado → interessado → aceite_fase1 → contrato_firme; ou recusou / sem_resposta (com motivo).
 */
export type NivelInteresse =
  | "sem_contato"
  | "contatado"
  | "interessado"
  | "aceite_fase1"
  | "contrato_firme"
  | "recusou"
  | "sem_resposta"

export type IdOpcao = "barata" | "segura" | "compacta"

export interface CamposPedido {
  meta: { tipo: TipoMeta; valor: number }
  /** ProFloresta+: 12% no ano 7 até 100% no ano 25 */
  cronograma: Cronograma
  /** datas próprias: ano → fração da meta (só com cronograma "proprio") */
  marcos_proprios?: { ano: number; fracao: number }[]
  onde: {
    biomas: string[]
    ufs: string[]
    municipios: string[]
    /** raio em volta de uma planta ou fábrica */
    raio?: { lon: number; lat: number; km: number } | null
    /** polígono desenhado no mapa: anel [lon, lat] fechado */
    poligono?: [number, number][] | null
    so_fornecedores_cadeia: boolean
  }
  dinheiro: {
    custo_max_usd_credito: number | null
    tir_min: number | null
    preco_venda_usd: number
    fracao_financiada: number
  }
  metodos: Metodo[]
  terra: CaminhoTerra[]
  forma: { distancia_max_km: number | null; max_donos: number | null; area_min_contigua_ha: number | null }
  interesse: FiltroInteresse
  exclusoes: Exclusao[]
}

/** Uma faixa de simulação: P10, P50 e P90. */
export interface Faixa {
  p10: number
  p50: number
  p90: number
}

/** "Quanto existe na nossa base" para o pedido, logo ao enviar. */
export interface BaseDisponivel {
  fazendas: number
  hectares: number
  creditos: Faixa
  por_caminho: { caminho: CaminhoTerra; fazendas: number; hectares: number; creditos: number }[]
  por_interesse: { nivel: NivelInteresse; fazendas: number; creditos: number }[]
  alcanca_meta: boolean
  /** quanto falta para a meta, na unidade da meta (0 quando alcança) */
  falta: number
  /** o que afrouxar no pedido, do que mais ajuda ao que menos */
  afrouxar: { campo: string; texto: string; ganho: number }[]
  /** de onde a base saiu (por exemplo, "municípios com o contorno das fazendas") */
  observacao?: string
}

export type PapelNoLote = "lote" | "reserva"

export interface FazendaDoLote {
  cod_imovel: string
  cod_ibge: string
  municipio: string
  uf: string
  papel: PapelNoLote
  /** A API retém as medidas individuais até o cliente liberar esta ficha. */
  ficha_liberada: boolean
  hectares: number | null
  creditos: Faixa | null
  metodo: Metodo | null
  caminho: CaminhoTerra | null
  custo_usd_credito: number | null
  /** pequena (até 4 módulos fiscais): entra agrupada com as vizinhas, nunca descartada */
  pequena: boolean
  interesse: NivelInteresse
  /** entrou no lugar de outra (troca do cliente ou recusa do dono) */
  trocou?: string | null
  lon: number
  lat: number
  /** Somente quando a API autorizar o detalhe dessa fazenda; não buscar o conjunto público para contornar o portão. */
  geometria?: Geo["features"][number]["geometry"] | null
}

export interface Marco {
  ano: number
  /** fração da meta entregue até esse ano */
  fracao: number
  /** chance de cumprir (0 a 1) */
  chance: number
}

/** Fazendas da opção que o preço do pedido não paga (preço de equilíbrio acima dele): o plantio abaixo do equilíbrio */
export interface AbaixoEquilibrio {
  preco_usd: number
  fazendas: number
  creditos: number
  /** parte dos créditos da opção (0 a 1) */
  fracao: number
  preco_equilibrio_medio_usd: number | null
  metodos: Partial<Record<Metodo, number>>
  /** créditos da base que o preço paga */
  base_que_se_paga: number
  /** a meta só fecha com elas */
  so_fecha_com_elas: boolean
  aviso: string | null
}

export interface Opcao {
  id: IdOpcao
  creditos: Faixa
  hectares: number
  fazendas: number
  pequenas: number
  tir: Faixa
  custo_usd_credito: Faixa
  pico_caixa_usd: number
  marcos: Marco[]
  multa_esperada_usd: number
  mistura_terra: { caminho: CaminhoTerra; fracao: number }[]
  metodos: { metodo: Metodo; fazendas: number }[]
  /** fazendas do lote e de reserva, na ordem em que entram */
  itens: FazendaDoLote[]
  alcanca_meta: boolean
  falta: number
  /** o otimizador põe a regeneração antes do plantio que o preço não paga e avisa quando só fecha com ele */
  abaixo_equilibrio?: AbaixoEquilibrio
  /** Detalhes disponíveis apenas na API autenticada ou demonstração sintética. */
  destrava?: DestravadorPublicado[]
  o_que_falta?: string[]
  /** Evidência agregada privada, vinculada à revisão efetiva do lote. Nunca consta no resumo aberto. */
  ficha_credito?: FichaCredito
}

export type StatusPedido =
  | "lote_montado"
  | "buscando_interesse"
  | "grupo_pronto"
  | "faltou"
  | "reservado"
  | "contrato"
  | "reserva_vencida"

export interface Alerta {
  tipo: "lote_melhorou" | "fazenda_com_problema"
  texto: string
  data: string
  cod_imovel?: string
}

export interface Pedido {
  id: string
  criado_em: string
  campos: CamposPedido
  status: StatusPedido
  base: BaseDisponivel
  opcoes: Opcao[]
  /** a opção que foi para a busca de interesse */
  opcao_escolhida: IdOpcao | null
  reservado_ate: string | null
  alertas: Alerta[]
  /** versão do modelo e das premissas (para aprender depois com o que aconteceu) */
  versao_modelo: string
  /** Identidade da sugestão e composição atuais, para rejeitar cálculos derivados antigos. */
  revisao_lote?: string | null
  /** true na resposta de exemplo (sem back-end): a tela avisa */
  exemplo?: boolean
  /** Consulta pública ao cenário publicado. Não é uma execução do pedido nem libera detalhes das fazendas. */
  publicacao?: PublicacaoLote
}

export interface DestravadorPublicado {
  tipo: "salvaguarda" | "regularizacao" | "certidao"
  texto: string
  fazendas: number | null
  hectares: number | null
  /** P50 informado na regularização; nunca é um ganho adicional que se possa somar. */
  creditos: number | null
  creditos_faixa: Faixa | null
  /** Uma fazenda pode constar em várias pendências, inclusive nas duas fontes do quadro. */
  somavel: false
}

/** Resumo aberto com lista positiva; a composição e a diligência pertencem à API autenticada. */
export interface OpcaoPublicada {
  id: IdOpcao
  creditos: Faixa | null
  /** Custo médio por crédito em US$, conforme o lote publicado. */
  custo_usd_credito: number | null
  hectares: number | null
  /** Titulares e reservas; as três alternativas não são somáveis. */
  fazendas: number | null
  /** Somente matrícula conferida ou concessão documentada, nunca matrícula a conferir. */
  terra_pronta: { creditos_p50: number | null; fracao_meta: number | null }
}

export interface PublicacaoLote {
  contrato: "publico_lotes"
  versao: 1
  estado: "ausente" | "publicado"
  aviso: string
  fonte: string
  atualizado_em: string | null
  cenario: string
  modelo_versao: string | null
  uf: string
  volume_creditos: number | null
  preco_contrato_usd: number | null
  /** O snapshot publicado é referência; filtros novos exigem uma execução autenticada do solver. */
  pedido_recalculado: false
  base: {
    fazendas: number | null
    hectares: number | null
    creditos: { p10: number | null; p50: number | null; p90: number | null }
    observacao: string
  }
  cobertura: { municipios: number | null; estados: number | null; fazendas: number | null; hectares: number | null; observacao?: string }
  opcoes: OpcaoPublicada[]
}

export interface ResumoPedido {
  id: string
  criado_em: string
  titulo: string
  status: StatusPedido
  reservado_ate: string | null
  /** fração da meta com dono interessado (0 a 1), quando a busca começou */
  com_interesse: number | null
  alertas: number
}

export interface MudancaLote {
  opcao: IdOpcao
  acao: "tirar" | "trocar"
  cod_imovel: string
  /** na troca, a fazenda de reserva que entra (sem ela, a melhor reserva) */
  por?: string | null
}

export interface Onda {
  numero: number
  data: string
  contatados: number
  /** canais usados (WhatsApp, carta, e-mail, visita de parceiro local) */
  canais: string[]
}

export interface Andamento {
  pedido: string
  status: StatusPedido
  meta: number
  /** créditos (ou a unidade da meta) por nível alcançado, cumulativo: contrato está dentro de aceite, que está dentro de interessado */
  com_interessado: number
  com_aceite: number
  com_contrato: number
  ondas: Onda[]
  contatados: number
  recusas: number
  sem_resposta: number
  motivos: { motivo: string; fazendas: number }[]
  /**
   * Cada fazenda do grupo e quem já foi contatado, com o nível de interesse de agora (papel "lote" = está no grupo;
   * "reserva" = saiu ou espera) e "trocou" quando entrou no lugar de quem recusou.
   */
  fazendas: FazendaDoLote[]
  /** quando o grupo fechou (status grupo_pronto) */
  grupo_pronto_em: string | null
  proxima_onda_em: string | null
  /** o que faltou e o que afrouxar, se as opções acabaram */
  faltou?: { falta: number; afrouxar: string[] } | null
}

export interface Cobranca {
  pedido: string
  valor_brl: number
  hectares: number
  prazo_dias: number
  /** a reserva é abatida da conexão por hectare quando o contrato fecha */
  abatimento: string
  /** null antes de pedir a reserva (GET /reserva devolve só o valor e o prazo) */
  pix: { copia_e_cola: string; expira_em: string | null } | null
  pago: boolean
  reservado_ate: string | null
  modo_teste?: boolean
  exemplo?: boolean
}

export interface Sessao {
  token: string
  email: string
}
