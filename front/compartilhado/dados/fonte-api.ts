/**
 * Fonte da API do back-end. Mesmo contrato da amostra: as telas não sabem qual das duas está em uso.
 *
 * Rotas esperadas (proposta para o back-end; JSON com as MESMAS colunas dos CSV do motor, docs/colunas.md):
 *   GET  {api}/municipios                         → [{cod_ibge, municipio, uf, imoveis, sem_problema, ...}]
 *   GET  {api}/municipios/{cod_ibge}/imoveis      → [{cod_imovel, ha, frente, ...}]  (404 = ainda sem dado)
 *   GET  {api}/imoveis/{cod_imovel}               → {cod_imovel, ...}               (404 = não existe)
 *   GET  {api}/imoveis/{cod_imovel}/ficha         → FichaJson (dados/ficha.ts: linha, contexto, perímetro)
 *   GET  {api}/imoveis/{cod_imovel}/certidoes     → [{registro_cns, registro_matricula, ha_sobre_car, parcelas}]
 *   GET  {api}/busca?q=                           → RespostaBusca (dados/busca.ts: situacao, mensagem, imoveis, municipios)
 *   GET  {api}/geo/{cod_ibge}/{camada}.geojson    → municipio | imoveis | ti | uc | rios
 *   GET  {api}/geo/{cod_ibge}/base.pmtiles        → mapa base (precisa responder a Range)
 *   GET  {api}/estados                            → Estados (dados/tipos.ts): os 27 estados, quantos municípios o motor
 *                                                   processou, de quantos na lista do IBGE e se está completo
 *   GET  {api}/estados/{uf}/pontos                → {campos, pontos: [[lon, lat, situacao, ha, cod_ibge, n]]} (aptas de
 *                                                   um estado; n > 1 é a soma do município, no meio dele)
 *   GET  {api}/geo/brasil/municipios.geojson      → todos os municípios do Brasil, simplificados (cod_ibge, nome, uf)
 *   GET  {api}/geo/brasil/estados.geojson         → os 27 estados (uf, cod, rotulo: [lon, lat])
 *   GET  {api}/geo/brasil/base.pmtiles            → mapa base único, do país ao município (precisa responder a Range)
 * Autorização: Bearer no cabeçalho, com o token vindo de VITE_RAIZ_API_TOKEN só em ambiente interno.
 */

import { comoLinha, n0, texto } from "./colunas"
import { lerPontos, memo, type FonteDeDados } from "./fonte"
import type { RespostaBusca } from "./busca"
import { lerFicha, type FichaJson } from "./ficha"
import { funilDosImoveis, lerFunil, lerImovel } from "./funil"
import type { Estados, Geo } from "./tipos"

export function fonteApi(api: string, token?: string): FonteDeDados {
  const raiz = api.endsWith("/") ? api : api + "/"
  const cabecalhos: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {}

  async function json<T>(caminho: string, sinal?: AbortSignal): Promise<T | null> {
    const r = await fetch(raiz + caminho, { headers: cabecalhos, signal: sinal })
    if (r.status === 404) return null
    if (!r.ok) throw new Error(`${r.status} em ${caminho}`)
    return (await r.json()) as T
  }

  const municipios = memo(async () =>
    ((await json<Record<string, unknown>[]>("municipios")) ?? []).map((o) => {
      const l = comoLinha(o)
      return lerFunil(l, l.uf ?? "")
    }),
  )

  const imoveis = memo(async (cod: string) => {
    const lista = await json<Record<string, unknown>[]>(`municipios/${cod}/imoveis`)
    return lista ? lista.map((o) => lerImovel(comoLinha(o))) : null
  })

  return {
    nome: "api",
    async imagem(caminho) {
      if (!token) return raiz + caminho
      const r = await fetch(raiz + caminho, { headers: cabecalhos })
      return r.ok ? URL.createObjectURL(await r.blob()) : null
    },
    municipios: () => municipios(""),
    async municipio(cod) {
      const m = (await municipios("")).find((x) => x.cod_ibge === cod)
      if (m) return m
      const lista = await imoveis(cod)
      return lista?.length ? funilDosImoveis(lista, cod, lista[0].municipio, lista[0].uf) : null
    },
    imoveis,
    async imovel(cod_imovel) {
      const o = await json<Record<string, unknown>>(`imoveis/${encodeURIComponent(cod_imovel)}`)
      return o ? lerImovel(comoLinha(o)) : null
    },
    async ficha(cod_imovel) {
      const dado = await json<FichaJson>(`imoveis/${encodeURIComponent(cod_imovel)}/ficha`)
      return dado ? lerFicha(dado) : null
    },
    async certidoes(cod_imovel) {
      const lista = (await json<Record<string, unknown>[]>(`imoveis/${encodeURIComponent(cod_imovel)}/certidoes`)) ?? []
      return lista.map((o) => {
        const l = comoLinha(o)
        return {
          cod_imovel,
          registro_cns: texto(l, "registro_cns") ?? "",
          registro_matricula: texto(l, "registro_matricula") ?? "",
          ha_sobre_car: n0(l, "ha_sobre_car") || null,
          parcelas: n0(l, "parcelas") || null,
        }
      })
    },
    async buscar(q, sinal) {
      const r = await json<RespostaBusca>(`busca?q=${encodeURIComponent(q)}`, sinal)
      if (!r) throw new Error("a API não respondeu à busca")
      return r
    },
    async estados() {
      const e = await json<Estados>("estados")
      if (!e) throw new Error("a API não respondeu GET /estados")
      return e
    },
    async pontos(uf) {
      return lerPontos(await json(`estados/${uf}/pontos`))
    },
    async municipiosComImoveis() {
      return (await municipios("")).filter((m) => m.linha.tem_imoveis !== "False").map((m) => m.cod_ibge)
    },
    geo: {
      // A API ainda não fornece o manifesto de desenhos. Não confundir municípios processados com contornos existentes.
      cobertura: async () => undefined,
      async brasil() {
        const [municipios, estados] = await Promise.all([json<Geo>("geo/brasil/municipios.geojson"), json<Geo>("geo/brasil/estados.geojson")])
        return { municipios, estados, base: `${raiz}geo/brasil/base.pmtiles` }
      },
      camada: (cod, camada) => json<Geo>(`geo/${cod}/${camada}.geojson`),
      // a API ainda não lista; os municípios com lista por fazenda têm o contorno das fazendas
      comContorno: () => municipios("").then((l) => l.filter((m) => m.linha.tem_imoveis !== "False").map((m) => m.cod_ibge)),
      async base(cod) {
        return `${raiz}geo/${cod}/base.pmtiles`
      },
    },
  }
}
