/** Palavras das telas de pedido: rótulos de cada valor do contrato e as frases que se repetem. */

import { fmtDestaque, fmtInt, UFS } from "../formato"
import type { CaminhoTerra, CamposPedido, Cronograma, Exclusao, Faixa, FiltroInteresse, IdOpcao, Metodo, NivelInteresse, StatusPedido, TipoMeta } from "./tipos"

export const ROTULO_OPCAO: Record<IdOpcao, { nome: string; criterio: string }> = {
  barata: { nome: "Mais barata", criterio: "menor custo líquido por crédito" },
  segura: { nome: "Mais segura", criterio: "menos risco de terra e mais chance de aceite do dono" },
  compacta: { nome: "Mais compacta", criterio: "fazendas vizinhas, menos logística e vazamento" },
}

export const ROTULO_META: Record<TipoMeta, { nome: string; unidade: string; unidadeUma: string }> = {
  creditos: { nome: "Créditos líquidos (t CO2e)", unidade: "créditos", unidadeUma: "crédito" },
  hectares: { nome: "Hectares restaurados", unidade: "ha", unidadeUma: "ha" },
  flag_t_ano: { nome: "Toneladas FLAG por ano", unidade: "t por ano", unidadeUma: "t por ano" },
}

export const ROTULO_CRONOGRAMA: Record<Cronograma, string> = {
  profloresta: "ProFloresta+ (12% no ano 7 até 100% no ano 25)",
  livre: "Livre (tudo até o ano 25)",
  proprio: "Datas próprias",
}

export const ROTULO_METODO: Record<Metodo, string> = {
  regeneracao_assistida: "Regeneração assistida",
  semeadura_direta: "Semeadura direta",
  plantio_total: "Plantio total",
  agrofloresta: "Agrofloresta ou cacau",
  silvipastoril: "Silvipastoril (meta FLAG)",
}

export const ROTULO_CAMINHO: Record<CaminhoTerra, string> = {
  matricula_conferida: "Matrícula conferida",
  matricula_a_conferir: "Matrícula a conferir",
  concessao: "Concessão",
  assentamento: "Assentamento",
  posse_em_titulacao: "Posse em titulação",
}

export const ROTULO_INTERESSE_FILTRO: Record<FiltroInteresse, string> = {
  qualquer: "Qualquer",
  interessados: "Só com dono interessado",
  com_aceite: "Só com aceite do dono",
}

export const ROTULO_EXCLUSAO: Record<Exclusao, string> = {
  embargo: "Embargo do Ibama",
  terra_indigena: "Terra indígena",
  uc_protecao_integral: "Unidade de conservação de proteção integral",
  projeto_carbono: "Sobreposição com projeto de carbono existente",
}

export const ROTULO_INTERESSE: Record<NivelInteresse, string> = {
  sem_contato: "Sem contato",
  contatado: "Contatado",
  interessado: "Interessado",
  aceite_fase1: "Aceite (fase 1)",
  contrato_firme: "Contrato firme",
  recusou: "Recusou",
  sem_resposta: "Sem resposta",
}

/** selo de nível do guia (item 4.7): bronze = achada no CAR, prata = título conferido, ouro = dono aceitou */
export function seloDeNivel(caminho: CaminhoTerra, interesse: NivelInteresse): { classe: "bronze" | "prata" | "ouro"; texto: string } {
  if (interesse === "aceite_fase1" || interesse === "contrato_firme") return { classe: "ouro", texto: "Ouro: dono aceitou" }
  if (caminho === "matricula_conferida") return { classe: "prata", texto: "Prata: título conferido" }
  return { classe: "bronze", texto: "Bronze: achada no CAR" }
}

export function rotuloStatus(s: StatusPedido, reservadoAte: string | null): string {
  switch (s) {
    case "lote_montado":
      return "Lote montado"
    case "buscando_interesse":
      return "Buscando interesse"
    case "grupo_pronto":
      return "Grupo pronto"
    case "faltou":
      return "Faltou fazenda"
    case "reservado":
      return reservadoAte ? `Reservado até ${dataCurta(reservadoAte)}` : "Reservado"
    case "reserva_vencida":
      return "Reserva vencida"
    case "contrato":
      return "Contrato"
  }
}

export const dataCurta = (iso: string) => new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })
export const dataLonga = (iso: string) => new Date(iso).toLocaleDateString("pt-BR", { day: "numeric", month: "long", year: "numeric" })

/** "1 milhão de créditos"; "380 mil ha"; "12 mil t por ano" */
export function fmtMeta(valor: number, tipo: TipoMeta): string {
  const u = ROTULO_META[tipo]
  const v = fmtDestaque(valor)
  if (tipo === "creditos") return `${v} ${/milh|bilh|mil$/.test(v) ? "de " : ""}${valor === 1 ? u.unidadeUma : u.unidade}`
  return `${v} ${u.unidade}`
}

/** "cerca de 16 milhões de créditos (de 11 milhões a 20 milhões)" */
export const fmtFaixaMeta = (f: Faixa, tipo: TipoMeta) => `cerca de ${fmtMeta(f.p50, tipo)} (de ${fmtDestaque(f.p10)} a ${fmtDestaque(f.p90)})`

/** "cerca de 1,1 milhão (de 770 mil a 1,4 milhão)", como pede o guia (item 1.6) */
export const fmtFaixa = (f: Faixa, fmt: (n: number) => string = fmtDestaque) => `cerca de ${fmt(f.p50)} (de ${fmt(f.p10)} a ${fmt(f.p90)})`

export const fmtUsd = (v: number) => (Math.abs(v) >= 1000 ? `US$ ${fmtDestaque(v)}` : `US$ ${v.toLocaleString("pt-BR", { maximumFractionDigits: 2, minimumFractionDigits: v < 100 ? 2 : 0 })}`)
export const fmtBrl = (v: number) => v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 2 })
export const fmtTir = (t: number) => `${(t * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% ao ano`

/** "1 milhão de créditos, Amazônia, ProFloresta+" */
export function tituloDoPedido(c: CamposPedido): string {
  const onde = c.onde.poligono
    ? "área desenhada"
    : c.onde.municipios.length
      ? `${fmtInt(c.onde.municipios.length)} ${c.onde.municipios.length === 1 ? "município" : "municípios"}`
      : c.onde.ufs.length
        ? c.onde.ufs.map((u) => UFS[u] ?? u).join(", ")
        : c.onde.biomas.join(", ") || "Brasil"
  const crono = c.cronograma === "profloresta" ? "ProFloresta+" : c.cronograma === "livre" ? "cronograma livre" : "datas próprias"
  return `${fmtMeta(c.meta.valor, c.meta.tipo)}, ${onde}, ${crono}`
}
