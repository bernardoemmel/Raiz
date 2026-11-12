/** Contrato da camada aberta. Não é um Imovel incompleto: não contém medidas privadas. */
export const SITUACOES_BASICAS = {
  apto: "Apto",
  com_pendencia: "Com pendência",
  nao_apto: "Não apto",
} as const

export type SituacaoBasica = keyof typeof SITUACOES_BASICAS

export interface ImovelBasico {
  cod_imovel: string
  cod_ibge: string
  municipio: string
  uf: string
  situacao_basica: SituacaoBasica
}

/** Projeção por allowlist: uma coluna inesperada nunca acompanha o objeto até a tela. */
export function lerBasico(l: Record<string, string>): ImovelBasico | null {
  if (!/^[A-Z]{2}-\d{7}-[A-F0-9]{32}$/.test(l.cod_imovel ?? "") || !/^\d{7}$/.test(l.cod_ibge ?? "")) return null
  if (!Object.hasOwn(SITUACOES_BASICAS, l.situacao_basica) || !/^[A-Z]{2}$/.test(l.uf ?? "") || !l.municipio) return null
  return { cod_imovel: l.cod_imovel, cod_ibge: l.cod_ibge, municipio: l.municipio, uf: l.uf, situacao_basica: l.situacao_basica as SituacaoBasica }
}
