import { useEffect, useState } from "react"
import type { RespostaBusca } from "../../compartilhado/dados"
import { normalizar, UFS } from "../../compartilhado/formato"

/** Entrada (o Brasil), um estado, um município, a ficha de uma fazenda e a área logada (entrar e pedidos de lote). */
export type Rota =
  | { tela: "entrada" }
  | { tela: "acerto" }
  | { tela: "calendario"; car?: string }
  | { tela: "estado"; uf: string }
  | { tela: "municipio"; municipio: string }
  | { tela: "fazenda"; car: string }
  | { tela: "prospeccao" }
  | { tela: "entrar"; token: string | null }
  | { tela: "pedidos" }
  | { tela: "pedido-novo" }
  | { tela: "pedido"; id: string }
  | { tela: "grupo"; id: string }
  | { tela: "pasta"; id: string; opcao?: string }

export function lerRota(hash: string): Rota {
  const partes = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent)
  if (partes[0] === "acerto") return { tela: "acerto" }
  if (partes[0] === "calendario") return /^[A-Z]{2}[0-9]{7}[A-F0-9]{32}$/i.test((partes[1] || "").replace(/[^a-z0-9]/gi, "")) ? { tela: "calendario", car: partes[1] } : { tela: "calendario" }
  if (partes[0] === "fazenda" && partes[1]) return { tela: "fazenda", car: partes[1] }
  if (partes[0] === "prospeccao") return { tela: "prospeccao" }
  if (partes[0] === "entrar") return { tela: "entrar", token: partes[1] || null }
  if (partes[0] === "pedidos") {
    if (!partes[1]) return { tela: "pedidos" }
    if (partes[1] === "novo") return { tela: "pedido-novo" }
    if (/^[a-z0-9-]+$/i.test(partes[1])) return partes[2] === "pasta" ? { tela: "pasta", id: partes[1], ...(["barata", "segura", "compacta"].includes(partes[3]) ? { opcao: partes[3] } : {}) } : partes[2] === "grupo" ? { tela: "grupo", id: partes[1] } : { tela: "pedido", id: partes[1] }
  }
  if (partes[0] === "municipio" && /^\d{7}$/.test(partes[1] ?? "")) return { tela: "municipio", municipio: partes[1] }
  const uf = (partes[1] ?? "").toUpperCase()
  if (partes[0] === "estado" && uf in UFS) return { tela: "estado", uf }
  return { tela: "entrada" }
}

export const linkEstado = (uf: string) => `#/estado/${uf}`
export const linkCalendario = "#/calendario"
export const linkCalendarioImovel = (car: string) => `${linkCalendario}/${encodeURIComponent(car)}`
export const linkPedidos = "#/pedidos"
export const linkProspeccao = "#/prospeccao"
export const linkNovoPedido = "#/pedidos/novo"
export const linkPedido = (id: string) => `#/pedidos/${encodeURIComponent(id)}`
export const linkGrupo = (id: string) => `#/pedidos/${encodeURIComponent(id)}/grupo`
export const linkMunicipio = (cod: string) => `#/municipio/${cod}`
export const linkFazenda = (car: string) => `#/fazenda/${encodeURIComponent(car)}`

/** Município do contorno do Brasil (os 5.570), processado ou não. */
export interface MunicipioDoMapa {
  cod_ibge: string
  nome: string
  uf: string
}

/**
 * Municípios que a busca do back-end não conhece (estado ainda não processado), achados pelo nome no contorno do
 * Brasil. Escolher um faz o mesmo que tocar nele no mapa: o mapa vai até lá e o painel diz que ainda não foi lido.
 */
export function municipiosSemDados(q: string, mapa: MunicipioDoMapa[], conhecidos: Set<string>, max = 5): MunicipioDoMapa[] {
  const t = normalizar(q)
  if (t.length < 3 || /\d/.test(t)) return []
  return mapa
    .filter((m) => !conhecidos.has(m.cod_ibge) && normalizar(m.nome).includes(t))
    .sort((a, b) => Number(!normalizar(a.nome).startsWith(t)) - Number(!normalizar(b.nome).startsWith(t)) || a.nome.localeCompare(b.nome, "pt-BR"))
    .slice(0, max)
}

/**
 * Para onde vai um Enter na busca quando há um resultado só: código do CAR direto para a ficha; município (com ou sem
 * dados) para o mapa dele. Com mais de um resultado, nenhum destino: a pessoa escolhe na lista.
 */
export function destinoDaBusca(r: RespostaBusca, semDados: MunicipioDoMapa[] = []): string | null {
  const municipios = [...r.municipios.map((m) => m.cod_ibge), ...semDados.map((m) => m.cod_ibge)]
  if (r.imoveis.length === 1 && !municipios.length) return linkFazenda(r.imoveis[0].cod_imovel)
  if (!r.imoveis.length && municipios.length === 1) return linkMunicipio(municipios[0])
  return null
}

export function useRota(): Rota {
  const [rota, setRota] = useState(() => lerRota(location.hash))
  useEffect(() => {
    const mudou = () => {
      const nova = lerRota(location.hash)
      setRota(nova)
      if (nova.tela === "fazenda") window.scrollTo({ top: 0 })
    }
    window.addEventListener("hashchange", mudou)
    return () => window.removeEventListener("hashchange", mudou)
  }, [])
  return rota
}

/**
 * Pedido de voo do mapa: quem abre a ficha pela busca pede, e a ficha consome uma vez (o mapa sai do Brasil, passa
 * pelo município e pousa na fazenda). Navegar de outro jeito não pede voo.
 */
let vooPedido: string | null = null
export const pedirVoo = (car: string) => {
  vooPedido = car
}
export function consumirVoo(car: string): boolean {
  const ok = vooPedido === car
  if (ok) vooPedido = null
  return ok
}

export const linkPasta = (id: string, opcao?: string) => `#/pedidos/${encodeURIComponent(id)}/pasta${opcao ? `/${encodeURIComponent(opcao)}` : ""}`
