import type { Faixa } from "../../../../compartilhado/pedidos/tipos"

/**
 * Faixa do analista (guia, item 1.6): barra clara de P10 a P90 e ponto escuro no P50, com a meta marcada quando houver.
 * O texto ao lado diz o mesmo em palavras ("cerca de 1 milhão (de 720 mil a 1,3 milhão)").
 */
export function FaixaBarra({ faixa, meta, escala, rotulo }: { faixa: Faixa; meta?: number; escala?: number; rotulo: string }) {
  const max = Math.max(escala ?? 0, faixa.p90, meta ?? 0) * 1.08 || 1
  const pct = (v: number) => `${Math.max(0, Math.min(100, (v / max) * 100))}%`
  return (
    <div className="faixa-pedido" role="img" aria-label={rotulo}>
      <span className="fp-trilho" />
      <span className="fp-p10p90" style={{ left: pct(faixa.p10), width: `max(4px, ${pct(faixa.p90 - faixa.p10)})` }} />
      {meta !== undefined && <span className="fp-meta" style={{ left: pct(meta) }} />}
      <span className="fp-p50" style={{ left: pct(faixa.p50) }} />
    </div>
  )
}
