/**
 * Reprocessamento estado por estado (docs/reprocessamento-progressivo.md).
 *
 * O publicador grava o reprocessamento.json no Release aberto: por estado, se os dados que estão no ar já foram
 * refeitos com as regras novas, se estão sendo refeitos (e quantos municípios já estão em dia) ou se ainda são das
 * regras antigas. Só situação e contagens; nada por imóvel. Um bloco fora do contrato é ignorado inteiro.
 */

const UFS = new Set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(" "))
const SITUACOES = new Set(["atualizado", "reprocessando", "antigo"])
const MOTIVOS = new Set([
  "falta_municipio", "tarefa_com_erro", "tarefa_desatualizada", "estado_incompleto", "validacao_menos_municipios", "sem_avaliacao",
])
const CAMPOS_DOC = new Set(["escopo", "versao_publicacao", "gerado_em", "geracao_vigente", "estados"])
const CAMPOS_ESTADO = new Set(["situacao", "geracao", "prontos", "total", "motivo", "atualizado_em", "desde"])
const GERACAO = /^\d{4}-\d{2}-\d{2}[a-z0-9.-]{0,20}$/
const DATA = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/

export type SituacaoRegras = "atualizado" | "reprocessando" | "antigo"
export type MotivoRegras =
  | "falta_municipio" | "tarefa_com_erro" | "tarefa_desatualizada" | "estado_incompleto" | "validacao_menos_municipios" | "sem_avaliacao"

/** A linha de um estado no reprocessamento.json. */
export interface RegrasEstado {
  situacao: SituacaoRegras
  /** a geração das regras dos dados que estão no ar (ausente: regras antigas, anteriores a este controle) */
  geracao?: string
  /** municípios com todas as tarefas em dia com as regras novas, de `total` */
  prontos?: number
  total?: number
  motivo?: MotivoRegras
  /** quando o estado foi trocado no site com as regras novas */
  atualizado_em?: string
  /** desde quando o estado está sendo refeito */
  desde?: string
}

export interface Reprocessamento {
  geracao_vigente: string
  gerado_em?: string
  estados: Record<string, RegrasEstado>
}

const objeto = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v)
const contagem = (v: unknown) => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 && v <= 6000

/** Contrato fechado: devolve null se qualquer parte do documento estiver fora dele. */
export function lerReprocessamento(valor: unknown): Reprocessamento | null {
  if (!objeto(valor) || Object.keys(valor).some((k) => !CAMPOS_DOC.has(k))) return null
  if (valor.escopo !== "publico_basico" || valor.versao_publicacao !== 1) return null
  if (typeof valor.geracao_vigente !== "string" || !GERACAO.test(valor.geracao_vigente)) return null
  if (valor.gerado_em !== undefined && (typeof valor.gerado_em !== "string" || !DATA.test(valor.gerado_em))) return null
  if (!objeto(valor.estados)) return null
  const estados: Record<string, RegrasEstado> = {}
  for (const [uf, s] of Object.entries(valor.estados)) {
    if (!UFS.has(uf) || !objeto(s) || Object.keys(s).some((k) => !CAMPOS_ESTADO.has(k))) return null
    if (typeof s.situacao !== "string" || !SITUACOES.has(s.situacao)) return null
    if (s.geracao !== undefined && (typeof s.geracao !== "string" || !GERACAO.test(s.geracao))) return null
    if (s.motivo !== undefined && (typeof s.motivo !== "string" || !MOTIVOS.has(s.motivo))) return null
    if ((s.prontos !== undefined && !contagem(s.prontos)) || (s.total !== undefined && !contagem(s.total))) return null
    for (const k of ["atualizado_em", "desde"] as const)
      if (s[k] !== undefined && (typeof s[k] !== "string" || !DATA.test(s[k] as string))) return null
    estados[uf] = {
      situacao: s.situacao as SituacaoRegras,
      ...(s.geracao !== undefined ? { geracao: s.geracao as string } : {}),
      ...(s.prontos !== undefined ? { prontos: s.prontos as number } : {}),
      ...(s.total !== undefined ? { total: s.total as number } : {}),
      ...(s.motivo !== undefined ? { motivo: s.motivo as MotivoRegras } : {}),
      ...(s.atualizado_em !== undefined ? { atualizado_em: s.atualizado_em as string } : {}),
      ...(s.desde !== undefined ? { desde: s.desde as string } : {}),
    }
  }
  return {
    geracao_vigente: valor.geracao_vigente,
    ...(valor.gerado_em !== undefined ? { gerado_em: valor.gerado_em as string } : {}),
    estados,
  }
}

/** O que o site mostra para um estado. "novas" só quando os dados no ar são da geração vigente. */
export interface RotuloRegras {
  tipo: "novas" | "reprocessando" | "antigas"
  selo: string
  frase: string
}

const data = (iso?: string) => (iso ? new Date(iso).toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" }) : "")

export function rotuloRegras(s: RegrasEstado | undefined, vigente: string | undefined): RotuloRegras {
  const novas = !!s && !!vigente && s.geracao === vigente
  if (s?.situacao === "atualizado" && novas)
    return {
      tipo: "novas", selo: "Regras novas",
      frase: `Dados refeitos com as regras novas${s.atualizado_em ? ` e trocados no site em ${data(s.atualizado_em)}` : ""}.`,
    }
  if (s?.situacao === "reprocessando") {
    const conta = s.total ? ` ${s.prontos ?? 0} de ${s.total} municípios já estão em dia.` : ""
    const noAr = novas ? "com as regras novas" : "com as regras antigas"
    return {
      tipo: "reprocessando", selo: s.total ? `Reprocessando ${s.prontos ?? 0}/${s.total}` : "Reprocessando",
      frase: `O estado está sendo refeito com as regras novas.${conta} Até terminar, o site mostra os dados ${noAr}, que continuam valendo para consulta.`,
    }
  }
  return {
    tipo: "antigas", selo: "Regras antigas",
    frase: "Dados ainda processados com as regras antigas (classificação da terra e sobreposição com projetos de carbono anteriores). O reprocessamento troca o estado inteiro de uma vez quando terminar.",
  }
}
