import { UFS } from "../formato"

/** Proveniência territorial por UF. Não admite URLs livres, mensagens nem informações de imóveis. */
export type MalhasMapa = Record<string, { fonte: "IBGE"; ano: number; sha256: string }>

export function malhasPublicas(valor: unknown): MalhasMapa {
  if (valor === undefined) return {}
  if (!valor || typeof valor !== "object" || Array.isArray(valor)) throw new Error("Proveniência das malhas inválida")
  const saida: MalhasMapa = {}
  for (const [uf, bruto] of Object.entries(valor)) {
    if (!Object.hasOwn(UFS, uf) || !bruto || typeof bruto !== "object" || Array.isArray(bruto))
      throw new Error("UF inválida na proveniência das malhas")
    const item = bruto as Record<string, unknown>
    if (Object.keys(item).sort().join(",") !== "ano,fonte,sha256" || item.fonte !== "IBGE" ||
      typeof item.ano !== "number" || !Number.isInteger(item.ano) || item.ano < 2000 || item.ano > new Date().getUTCFullYear() ||
      typeof item.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(item.sha256))
      throw new Error("Campos inválidos na proveniência da malha IBGE")
    saida[uf] = { fonte: "IBGE", ano: item.ano, sha256: item.sha256 }
  }
  return saida
}

/** A origem é formada pelo contrato oficial; nunca vem de texto fornecido por um pacote. */
export function urlMalhaIbge(uf: string, ano: number): string {
  return `https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_${ano}/UFs/${uf}/${uf}_Municipios_${ano}.zip`
}
