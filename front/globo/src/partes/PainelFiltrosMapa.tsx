import { ChevronLeft, SlidersHorizontal, X } from "lucide-react"
import { SITUACOES_BASICAS, type SituacaoBasica } from "../../../compartilhado/dados/basico"
import { UFS } from "../../../compartilhado/formato"

/** Os seis biomas do IBGE (Biomas 1:250.000, 2019), na ordem do próprio IBGE. */
export const BIOMAS = ["Amazônia", "Caatinga", "Cerrado", "Mata Atlântica", "Pampa", "Pantanal"] as const
export type Bioma = (typeof BIOMAS)[number]

/** Tipos de área que o mapa desenha. TI e UC só existem no detalhe do município. */
export const TIPOS_AREA = [
  { id: "fazendas", rotulo: "Fazendas cadastradas (CAR)" },
  { id: "ti", rotulo: "Terras indígenas" },
  { id: "uc", rotulo: "Unidades de conservação" },
] as const
export type TipoArea = (typeof TIPOS_AREA)[number]["id"]

/** O que as bolas do país somam (colunas do resumo municipal do motor). */
export const ROTULO_OFERTA = {
  aptas: "Fazendas aptas",
  matricula: "Aptas com matrícula",
  agrupar: "Para agrupar (assentamentos)",
} as const
export type Oferta = keyof typeof ROTULO_OFERTA

const ESTADOS = Object.entries(UFS).sort((a, b) => a[1].localeCompare(b[1], "pt-BR"))

interface Props {
  aberto: boolean
  aoAlternar: () => void
  /** no celular o painel é uma folha sobre o mapa, com botão de fechar */
  celular?: boolean
  bioma: Bioma | null
  aoBioma: (b: Bioma | null) => void
  uf: string | null
  aoEstado: (uf: string | null) => void
  ocultos: ReadonlySet<TipoArea>
  aoTipo: (tipo: TipoArea, visivel: boolean) => void
  situacao: SituacaoBasica | null
  aoSituacao: (s: SituacaoBasica | null) => void
  municipioAberto: boolean
  oferta: Oferta
  aoOferta: (o: Oferta) => void
  aoLimpar: () => void
}

/** Painel de filtros à esquerda do mapa. Nenhum filtro corta fazenda por tamanho. */
export function PainelFiltrosMapa(p: Props) {
  const ativos = (p.bioma ? 1 : 0) + (p.uf ? 1 : 0) + p.ocultos.size + (p.situacao ? 1 : 0) + (p.oferta !== "aptas" ? 1 : 0)
  if (!p.aberto) return (
    <button type="button" className="filtros-mapa-abrir" aria-expanded="false" aria-controls="filtros-mapa" onClick={p.aoAlternar}>
      <SlidersHorizontal size={18} aria-hidden="true" />Filtros{ativos > 0 && <span className="filtros-mapa-contagem">{ativos}</span>}
    </button>
  )
  return (
    <section id="filtros-mapa" className="filtros-mapa" aria-labelledby="titulo-filtros-mapa">
      <header>
        <h2 id="titulo-filtros-mapa"><SlidersHorizontal size={16} aria-hidden="true" />Filtros</h2>
        <button type="button" className="filtros-mapa-recolher" aria-expanded="true" aria-controls="filtros-mapa" onClick={p.aoAlternar}
          aria-label={p.celular ? "Fechar filtros" : "Recolher filtros"}>{p.celular ? <X size={18} aria-hidden="true" /> : <ChevronLeft size={18} aria-hidden="true" />}</button>
      </header>
      <label className="filtros-mapa-campo">
        <span>Bioma</span>
        <select value={p.bioma ?? ""} onChange={e => p.aoBioma((e.target.value || null) as Bioma | null)}>
          <option value="">Todos os biomas</option>
          {BIOMAS.map(b => <option key={b} value={b}>{b}</option>)}
        </select>
      </label>
      <label className="filtros-mapa-campo">
        <span>Estado</span>
        <select value={p.uf ?? ""} onChange={e => p.aoEstado(e.target.value || null)}>
          <option value="">Brasil inteiro</option>
          {ESTADOS.map(([sigla, nome]) => <option key={sigla} value={sigla}>{nome}</option>)}
        </select>
      </label>
      <fieldset className="filtros-mapa-campo">
        <legend>Tipo de área</legend>
        {TIPOS_AREA.map(t => <label key={t.id} className="filtros-mapa-opcao">
          <input type="checkbox" checked={!p.ocultos.has(t.id)} onChange={e => p.aoTipo(t.id, e.target.checked)} />
          <span className={`filtros-mapa-amostra amostra-${t.id}`} aria-hidden="true" />{t.rotulo}
        </label>)}
        <small>Terras indígenas e unidades de conservação aparecem ao abrir um município.</small>
      </fieldset>
      {p.municipioAberto ? <label className="filtros-mapa-campo">
        <span>Situação</span>
        <select value={p.situacao ?? ""} aria-describedby="dica-situacao-mapa" onChange={e => p.aoSituacao((e.target.value || null) as SituacaoBasica | null)}>
          <option value="">Todas as situações</option>
          {Object.entries(SITUACOES_BASICAS).map(([id, rotulo]) => <option key={id} value={id}>{rotulo}</option>)}
        </select>
        <small id="dica-situacao-mapa">Pinta cada fazenda do município pela situação básica.</small>
      </label> : <label className="filtros-mapa-campo">
        <span>Situação</span>
        <select value={p.oferta} aria-describedby="dica-situacao-mapa" onChange={e => p.aoOferta(e.target.value as Oferta)}>
          {Object.entries(ROTULO_OFERTA).map(([id, rotulo]) => <option key={id} value={id}>{rotulo}</option>)}
        </select>
        <small id="dica-situacao-mapa">Muda o que cada círculo do mapa soma.</small>
      </label>}
      <button type="button" className="filtros-mapa-limpar" disabled={ativos === 0} onClick={p.aoLimpar}>Limpar filtros</button>
    </section>
  )
}
