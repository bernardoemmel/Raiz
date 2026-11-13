import { ufDoCodigo } from "../formato"

/** Cobertura do desenho na origem, sem CAR, coordenadas ou qualquer dado por fazenda. */
export interface CoberturaMapa {
  gerado_em: string | null
  dados_publicados_em: string | null
  /** Diferença conferida com o índice do site anteriormente publicado; ausência não significa zero. */
  novos_desde?: { anterior_em: string; atual_em: string; municipios: string[] } | null
  com_desenho: string[]
  sem_desenho: string[]
  /** Básico aberto: CAR, situação e perímetro; camadas individuais detalhadas exigem ficha paga. */
  acesso: "restrito" | "aberto"
}

interface Indice {
  gerado_em?: unknown
  dados_publicados_em?: unknown
  municipios?: Record<string, { imoveis?: { arquivo?: unknown } }>
  sem_contorno?: Record<string, unknown>
}

const dataValida = (v: unknown): string | null =>
  typeof v === "string" && /^\d{4}-\d\d-\d\dT/.test(v) && Number.isFinite(Date.parse(v)) ? v : null
const codigoValido = (cod: string) => /^\d{7}$/.test(cod) && Boolean(ufDoCodigo(cod))

/** Só conta desenhos do manifesto atual que de fato existem; cache antigo não entra na cobertura. */
export function coberturaDoIndice(indice: Indice, existe: (arquivo: string) => boolean, dadosPublicadosEm?: string): CoberturaMapa {
  const municipios = Object.entries(indice.municipios ?? {}).filter(([cod]) => codigoValido(cod))
  const com_desenho = municipios.filter(([cod, camadas]) => {
    const arquivo = camadas.imoveis?.arquivo
    return typeof arquivo === "string" && new RegExp(`^imoveis_${cod}\\.geojson(?:\\.gz)?$`).test(arquivo) && existe(arquivo)
  }).map(([cod]) => cod).sort()
  const comDesenho = new Set(com_desenho)
  const sem_desenho = [...new Set([...municipios.map(([cod]) => cod), ...Object.keys(indice.sem_contorno ?? {}).filter(codigoValido)])]
    .filter((cod) => !comDesenho.has(cod)).sort()
  return {
    gerado_em: dataValida(indice.gerado_em),
    dados_publicados_em: dataValida(indice.dados_publicados_em) ?? dataValida(dadosPublicadosEm),
    com_desenho,
    sem_desenho,
    acesso: "restrito",
  }
}

export function contarCobertura(cobertura: CoberturaMapa, uf?: string | null) {
  const filtrar = (cods: string[]) => [...new Set(cods)].filter((cod) => !uf || ufDoCodigo(cod) === uf)
  const com = filtrar(cobertura.com_desenho)
  return { municipios: com.length, estados: new Set(com.map(ufDoCodigo)).size, semDesenho: filtrar(cobertura.sem_desenho).length }
}
