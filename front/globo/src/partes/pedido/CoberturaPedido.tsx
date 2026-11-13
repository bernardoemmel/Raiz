import { fonte, useCarga } from "../../dados"
import { fmtInt, UFS } from "../../../../compartilhado/formato"
import { coberturaTerritorial, type CoberturaTerritorial } from "../../../../compartilhado/pedidos/territorio"
import type { CamposPedido } from "../../../../compartilhado/pedidos/tipos"

const nomes = (ufs: string[]) => ufs.map((uf) => UFS[uf] ?? uf).join(", ")

export function ResumoCoberturaPedido({ cobertura: c }: { cobertura: CoberturaTerritorial }) {
  return <div className="cobertura-pedido" aria-live="polite">
    <p><strong>{c.disponiveis.length ? `Dados publicados em ${fmtInt(c.disponiveis.length)} ${c.disponiveis.length === 1 ? "estado" : "estados"}.` : c.desconhecidos.length ? "A cobertura dos estados ainda não pôde ser confirmada." : "Nenhum estado com dados publicados neste alcance."}</strong>
      {c.municipios_processados !== null && c.municipios_esperados !== null && ` ${fmtInt(c.municipios_processados)} de ${fmtInt(c.municipios_esperados)} municípios processados.`}</p>
    {!!c.disponiveis.length && <p><strong>Entram na consulta:</strong> {nomes(c.disponiveis)}.</p>}
    {!!c.parciais.length && <p><strong>Cobertura parcial:</strong> {nomes(c.parciais)}. Entram somente os municípios já processados.</p>}
    {!!c.faltantes.length && <p><strong>Ainda sem dados publicados:</strong> {nomes(c.faltantes)}. A ausência de dados não significa ausência de potencial.</p>}
    {!!c.desconhecidos.length && <p><strong>Cobertura ainda não informada:</strong> {nomes(c.desconhecidos)}. Não foram contados como zero.</p>}
    {!c.recorte_exato && <p>Esta é a disponibilidade dos estados antes do recorte. A API aplica o bioma e os demais limites às fazendas; estes totais não medem a oferta do bioma.</p>}
    <p className="legenda-frase">Manifesto do Release: {c.atualizado_em ? <time dateTime={c.atualizado_em}>{new Date(c.atualizado_em).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short" })} (Brasília)</time> : "data ainda não informada"}. Estados novos entram quando o processamento publica seus dados.</p>
  </div>
}

export function CoberturaPedido({ onde }: { onde: CamposPedido["onde"] }) {
  const carga = useCarga(() => fonte.estados(), [])
  return <section className="secao-painel" aria-label="Disponibilidade territorial do pedido">
    <h3>Estados disponíveis para este pedido</h3>
    {carga.carregando ? <p role="status">Conferindo os estados no Release…</p> : carga.erro || !carga.dado ? <p role="status">Não foi possível conferir a cobertura agora. O pedido conserva o alcance escolhido; nenhum estado foi contado como sem dados.</p> : <ResumoCoberturaPedido cobertura={coberturaTerritorial(onde, carga.dado)} />}
  </section>
}
