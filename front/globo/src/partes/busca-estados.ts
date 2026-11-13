import { normalizar, UFS } from "../../../compartilhado/formato"

/** Catálogo de UFs já usado pelas rotas: a busca não inventa processamento nem consulta /busca no Pages. */
export function estadosDaBusca(consulta: string) {
  const q = normalizar(consulta)
  if (q.length < 2 || /\d/.test(q)) return []
  return Object.entries(UFS)
    .filter(([uf, nome]) => normalizar(uf) === q || normalizar(nome).includes(q))
    .sort(([ufA, nomeA], [ufB, nomeB]) => Number(normalizar(ufB) === q || normalizar(nomeB) === q) - Number(normalizar(ufA) === q || normalizar(nomeA) === q) || nomeA.localeCompare(nomeB, "pt-BR"))
    .slice(0, 5)
    .map(([uf, nome]) => ({ uf, nome }))
}

