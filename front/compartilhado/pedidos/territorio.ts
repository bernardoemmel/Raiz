/** Cobertura territorial do pedido. Disponibilidade vem sempre do manifesto atual. */
import { bool, num } from "../dados/colunas"
import type { Estados, FunilMunicipio } from "../dados/tipos"
import { UFS, ufDoCodigo } from "../formato"
import type { CamposPedido, PublicacaoLote } from "./tipos"

export const BIOMAS = ["Amazônia", "Cerrado", "Mata Atlântica", "Caatinga", "Pantanal", "Pampa"] as const
export type EscopoPedido = "estados" | "biomas" | "brasil"
type Onde = CamposPedido["onde"]

export function escopoDoPedido(onde: Onde): EscopoPedido {
  return onde.ufs.length ? "estados" : onde.biomas.length ? "biomas" : "brasil"
}

/** Mudar o alcance não conserva um município, desenho ou raio invisível da seleção anterior. */
export function mudarEscopoPedido(onde: Onde, escopo: EscopoPedido): Onde {
  return {
    ...onde, municipios: [], raio: null, poligono: null,
    ufs: escopo === "estados" ? onde.ufs : [],
    biomas: escopo === "biomas" ? (onde.biomas.length ? onde.biomas : ["Amazônia"]) : [],
  }
}

export interface CoberturaTerritorial {
  disponiveis: string[]
  parciais: string[]
  faltantes: string[]
  desconhecidos: string[]
  municipios_processados: number | null
  municipios_esperados: number | null
  atualizado_em: string | null
  recorte_exato: boolean
}

/** Os números são a cobertura estadual antes do recorte do pedido, nunca a oferta do bioma. */
export function coberturaTerritorial(onde: Onde, manifesto: Estados): CoberturaTerritorial {
  const ufsMunicipais = onde.municipios.map(ufDoCodigo).filter((uf): uf is string => uf !== null)
  const solicitadas = [...new Set(onde.ufs.length ? onde.ufs : ufsMunicipais.length ? ufsMunicipais : Object.keys(UFS))]
    .sort((a, b) => (UFS[a] ?? a).localeCompare(UFS[b] ?? b, "pt-BR"))
  const estados = new Map(manifesto.estados.map((e) => [e.uf, e]))
  const resposta: CoberturaTerritorial = {
    disponiveis: [], parciais: [], faltantes: [], desconhecidos: [],
    municipios_processados: 0, municipios_esperados: 0,
    atualizado_em: manifesto.gerado_em && Number.isFinite(Date.parse(manifesto.gerado_em)) ? manifesto.gerado_em : null,
    recorte_exato: !onde.biomas.length && !onde.municipios.length && !onde.raio && !onde.poligono && !onde.so_fornecedores_cadeia,
  }
  for (const uf of solicitadas) {
    const e = estados.get(uf)
    if (!e || !Number.isInteger(e.municipios) || e.municipios < 0 || !Number.isInteger(e.municipios_ibge) || e.municipios_ibge <= 0 || e.municipios > e.municipios_ibge) {
      resposta.desconhecidos.push(uf)
      continue
    }
    resposta.municipios_processados! += e.municipios
    resposta.municipios_esperados! += e.municipios_ibge
    if (!e.municipios) resposta.faltantes.push(uf)
    else {
      resposta.disponiveis.push(uf)
      if (e.municipios < e.municipios_ibge) resposta.parciais.push(uf)
    }
  }
  if (resposta.desconhecidos.length) {
    resposta.municipios_processados = null
    resposta.municipios_esperados = null
  }
  return resposta
}

/** Uma linha municipal entra uma vez, mesmo que o pedido tenha estados ou biomas repetidos. */
export function resumirCoberturaMunicipal(onde: Onde, municipios: FunilMunicipio[]): PublicacaoLote["cobertura"] {
  const selecionados = [...new Map(municipios.filter((m) => (!onde.ufs.length || onde.ufs.includes(m.uf)) && (!onde.municipios.length || onde.municipios.includes(m.cod_ibge))).map((m) => [m.cod_ibge, m])).values()]
  const recorteNaoPublicado = !!(onde.biomas.length || onde.raio || onde.poligono || onde.so_fornecedores_cadeia)
  const somar = (coluna: string): number | null => {
    if (!selecionados.length || recorteNaoPublicado) return null
    let soma = 0
    for (const m of selecionados) {
      const valor = num(m.linha ?? {}, coluna)
      if (bool(m.linha ?? {}, "dados_suprimidos") === true || valor === null) return null
      soma += valor
    }
    return soma
  }
  const fazendas = somar("imoveis"), hectares = somar("ha_carbono")
  const observacao = recorteNaoPublicado
    ? "A contagem de municípios e estados indica a cobertura territorial antes dos filtros. O recorte por bioma, raio, desenho ou cadeia exige a API; os totais de fazendas e hectares desse recorte ainda não estão publicados. Não somamos um estado inteiro como se pertencesse a um só bioma."
    : !selecionados.length
      ? "Nenhum município deste recorte foi publicado. Isso não significa que não existam fazendas ou potencial de restauração."
      : fazendas === null || hectares === null
        ? "O total não está disponível: há municípios com dados suprimidos ou valores ainda não publicados. As contagens de municípios e estados permanecem conhecidas."
        : undefined
  return { municipios: selecionados.length, estados: new Set(selecionados.map((m) => m.uf)).size, fazendas, hectares, ...(observacao ? { observacao } : {}) }
}
