/**
 * A camada ÚNICA de acesso a dados do front. As telas só falam com `FonteDeDados`; quem entrega os dados pode ser a
 * amostra em CSV (hoje) ou a API do back-end (depois), sem mudar tela nenhuma.
 *
 * Escolha (variável de ambiente do Vite, no .env do front, nunca no git):
 *   VITE_RAIZ_API=https://api.exemplo/   → usa a API (fonte-api.ts)
 *   sem a variável                       → usa dados/amostra/ e front/geo/ (fonte-amostra.ts)
 */

export { comoLinha } from "./colunas"
import type { ImovelBasico } from "./basico"
import type { RespostaBusca } from "./busca"
import type { Ficha } from "./ficha"
import type { CoberturaMapa } from "./cobertura-mapa"
import type { CamadaGeo, Estados, FunilMunicipio, Geo, Imovel, PontoFazenda } from "./tipos"

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
  /** Camada pública mínima, independente dos dados completos e sem métricas por imóvel. */
  basicos?(cod_ibge: string): Promise<ImovelBasico[] | null>
  /** imóveis de um município; null quando o motor ainda não entregou dado por fazenda desse município */
  imoveis(cod_ibge: string): Promise<Imovel[] | null>
  /** um imóvel pelo código do CAR (procura em todos os municípios disponíveis) */
  imovel(cod_imovel: string): Promise<Imovel | null>
  /** a ficha leve de uma fazenda: a linha do imóvel, o contexto do município e o perímetro (uma fazenda só) */
  ficha(cod_imovel: string): Promise<Ficha | null>
  /** cartório (CNS) e matrícula das parcelas SIGEF do imóvel, quando o motor gerou certidoes_<mun>.csv */
  certidoes(cod_imovel: string): Promise<Certidao[]>
  /** Código do CAR (inteiro ou começo), nome ou código do município; busca local no site e GET /busca na API. */
  buscar(q: string, sinal?: AbortSignal): Promise<RespostaBusca>
  /** os 27 estados: quantos municípios o motor já processou, de quantos (lista do IBGE), e se está completo */
  estados(): Promise<Estados>
  /** fazendas aptas de UM estado como pontos (o mapa carrega só o estado escolhido) */
  pontos(uf: string): Promise<PontoFazenda[]>
  /** quais municípios têm dado por fazenda */
  municipiosComImoveis(): Promise<string[]>
  geo: {
    /** Contagem e datas do índice leve, sem baixar contornos municipais ou dados individuais. */
    cobertura(): Promise<CoberturaMapa | undefined>
    camada(cod_ibge: string, camada: CamadaGeo): Promise<Geo | null>
    /** municípios com o contorno de cada fazenda (imoveis_<cod>.geojson) */
    comContorno(): Promise<string[]>
    /** URL do mapa base em PMTiles do município, ou null se ainda não foi gerado */
    base(cod_ibge: string): Promise<string | null>
    /** o Brasil: contorno de todos os municípios, dos 27 estados e o mapa base único (do país ao município) */
    brasil(): Promise<{ municipios: Geo | null; estados: Geo | null; base: string | null; cobertura?: CoberturaMapa }>
  }
  /**
   * URL pronta para <img> de um arquivo da fonte (a capa da ficha). Com token, baixa com o cabeçalho e devolve um
   * endereço blob:; sem token, devolve o endereço direto (o navegador guarda em cache). null quando não há.
   */
  imagem(caminho: string): Promise<string | null>
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

/**
 * Texto que pode vir comprimido em gzip (os CSV do site estático ficam em .csv.gz para caber no GitHub Pages): confere
 * a assinatura do gzip e descomprime no navegador; se o servidor já descomprimiu, lê como texto.
 */
export async function buscarTextoGz(url: string): Promise<string | null> {
  const r = await fetch(url)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`${r.status} ao ler ${url}`)
  if ((r.headers.get("content-type") ?? "").includes("text/html")) return null
  const bytes = new Uint8Array(await r.arrayBuffer())
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
    const fluxo = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"))
    return new Response(fluxo).text()
  }
  return new TextDecoder().decode(bytes)
}

export async function buscarTexto(url: string): Promise<string | null> {
  const r = await fetch(url)
  if (r.status === 404) return null
  if (!r.ok) throw new Error(`${r.status} ao ler ${url}`)
  if ((r.headers.get("content-type") ?? "").includes("text/html")) return null
  return r.text()
}

/** Os pontos como o plugin e a API mandam: { campos, pontos: [[lon, lat, situacao, ha, cod_ibge, n], ...] }. */
export function lerPontos(json: { campos?: string[]; pontos?: unknown[][] } | unknown[] | null): PontoFazenda[] {
  if (!json) return []
  // a API pode mandar a lista de objetos direto
  if (Array.isArray(json)) return (json as PontoFazenda[]).map((p) => ({ ...p, n: p.n ?? 1 }))
  const campos = json.campos ?? ["lon", "lat", "situacao", "ha", "cod_ibge", "n"]
  const i = (c: string) => campos.indexOf(c)
  return (json.pontos ?? []).map((p) => ({
    lon: Number(p[i("lon")]),
    lat: Number(p[i("lat")]),
    situacao: p[i("situacao")] === "apta" ? "apta" : "pendencia",
    ha: Number(p[i("ha")]) || 0,
    cod_ibge: String(p[i("cod_ibge")]),
    n: i("n") >= 0 ? Number(p[i("n")]) || 1 : 1,
  }))
}
