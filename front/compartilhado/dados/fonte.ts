/**
 * A camada ÚNICA de acesso a dados do front. As telas só falam com `FonteDeDados`; quem entrega os dados pode ser a
 * amostra em CSV (hoje) ou a API do back-end (depois), sem mudar tela nenhuma.
 *
 * Escolha (variável de ambiente do Vite, no .env do front, nunca no git):
 *   VITE_RAIZ_API=https://api.exemplo/   → usa a API (fonte-api.ts)
 *   sem a variável                       → usa dados/amostra/ e front/geo/ (fonte-amostra.ts)
 */

export { comoLinha } from "./colunas"
import type { Ficha } from "./ficha"
import type { CamadaGeo, FunilMunicipio, Geo, Imovel } from "./tipos"

export interface Certidao {
  cod_imovel: string
  registro_cns: string
  registro_matricula: string
  ha_sobre_car: number | null
  parcelas: number | null
}

export interface FonteDeDados {
  /** "amostra" ou "api", para mostrar na tela de onde vêm os números */
  readonly nome: string
  /** todos os municípios com funil (resumo), de todos os estados disponíveis */
  municipios(): Promise<FunilMunicipio[]>
  /** funil de um município: o resumo, ou a soma dos imóveis se não houver resumo */
  municipio(cod_ibge: string): Promise<FunilMunicipio | null>
  /** imóveis de um município; null quando o motor ainda não entregou dado por fazenda desse município */
  imoveis(cod_ibge: string): Promise<Imovel[] | null>
  /** um imóvel pelo código do CAR (procura em todos os municípios disponíveis) */
  imovel(cod_imovel: string): Promise<Imovel | null>
  /** a ficha leve de uma fazenda: a linha do imóvel, o contexto do município e o perímetro (uma fazenda só) */
  ficha(cod_imovel: string): Promise<Ficha | null>
  /** cartório (CNS) e matrícula das parcelas SIGEF do imóvel, quando o motor gerou certidoes_<mun>.csv */
  certidoes(cod_imovel: string): Promise<Certidao[]>
  /** quais municípios têm dado por fazenda */
  municipiosComImoveis(): Promise<string[]>
  geo: {
    camada(cod_ibge: string, camada: CamadaGeo): Promise<Geo | null>
    /** URL do mapa base em PMTiles do município, ou null se ainda não foi gerado */
    base(cod_ibge: string): Promise<string | null>
  }
}

/** Guarda a promessa de cada chave: a mesma leitura não é feita duas vezes. */
export function memo<T>(fn: (chave: string) => Promise<T>): (chave: string) => Promise<T> {
  const cache = new Map<string, Promise<T>>()
  return (chave) => {
    let p = cache.get(chave)
    if (!p) {
      p = fn(chave)
      cache.set(chave, p)
      p.catch(() => cache.delete(chave))
    }
    return p
  }
}

export async function buscarJson<T>(url: string): Promise<T | null> {
  const r = await fetch(url)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`${r.status} ao ler ${url}`)
  const tipo = r.headers.get("content-type") ?? ""
  // o servidor de desenvolvimento devolve o index.html para caminho que não existe
  if (tipo.includes("text/html")) return null
  return (await r.json()) as T
}

export async function buscarTexto(url: string): Promise<string | null> {
  const r = await fetch(url)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`${r.status} ao ler ${url}`)
  if ((r.headers.get("content-type") ?? "").includes("text/html")) return null
  return r.text()
}
