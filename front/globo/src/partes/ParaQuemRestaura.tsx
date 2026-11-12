import type { Imovel } from "../../../compartilhado/dados"
import { fmtHa, fmtInt } from "../../../compartilhado/formato"
import {
  AVISO,
  fmtFaixa,
  fmtNum1,
  fmtPct1,
  fmtReais,
  lerRestauracao,
  MODOS,
  textoFaltou,
  type Faixa,
} from "../../../compartilhado/restauracao"

/** Barra clara de P10 a P90 com ponto escuro no P50, numa escala comum à linha (guia do front, item 1.6). */
function BarraFaixa({ f, min, max }: { f: Faixa; min: number; max: number }) {
  const esc = (v: number) => (max > min ? ((v - min) / (max - min)) * 100 : 50)
  return (
    <span className="faixa-barra" aria-hidden="true">
      <i className="faixa-p10-p90" style={{ left: `${esc(f.p10)}%`, width: `${Math.max(esc(f.p90) - esc(f.p10), 1)}%` }} />
      <b className="faixa-p50" style={{ left: `${esc(f.p50)}%` }} />
    </span>
  )
}

interface PropsLinha {
  rotulo: string
  f: Faixa
  fmt: (n: number) => string
  unidade: string
  ajuda?: string
}

function Linha({ rotulo, f, fmt, unidade, ajuda }: PropsLinha) {
  const min = Math.min(0, f.p10)
  const max = Math.max(f.p90, 0) * 1.05 || 1
  return (
    <div className="faixa-linha">
      <dt>
        {rotulo}
        {ajuda && <span className="faixa-ajuda">{ajuda}</span>}
      </dt>
      <dd>
        <span className="num">{fmtFaixa(f, fmt, unidade)}</span>
        <BarraFaixa f={f} min={min} max={max} />
      </dd>
    </div>
  )
}

export function ParaQuemRestaura({ imovel }: { imovel: Imovel }) {
  const r = lerRestauracao(imovel.linha)
  if (!r)
    return (
      <section className="painel bloco restaurar" aria-labelledby="restaurar-titulo">
        <h2 id="restaurar-titulo">Para quem restaura</h2>
        <p className="bloco-resumo">O valor para quem restaura ainda não foi calculado para este município.</p>
      </section>
    )
  const modos = MODOS.filter((m) => r.porModoHa[m.id] > 0.05)
  return (
    <section className="painel bloco restaurar" aria-labelledby="restaurar-titulo">
      <h2 id="restaurar-titulo">Para quem restaura</h2>
      <div className="aviso-estimativa" role="note">
        <span className="aviso-icone" aria-hidden="true">
          !
        </span>
        <strong>{AVISO}</strong>
      </div>

      <p className="restaurar-principal">
        {r.areaHa > 0 ? (
          <>
            <span className="num">{fmtHa(r.areaHa)}</span> de pasto livre, fora da reserva legal e da APP. Caminho
            indicado: <strong>{r.nomeModo}</strong>.
          </>
        ) : (
          <>Sem pasto livre fora da reserva legal e da APP para restaurar com crédito.</>
        )}
      </p>
      {modos.length > 1 && (
        <p className="bloco-resumo num">
          {modos.map((m, k) => (
            <span key={m.id}>
              {k > 0 && "; "}
              {m.curto} em {fmtHa(r.porModoHa[m.id])}
            </span>
          ))}
          .
        </p>
      )}

      {r.areaHa > 0 && (
        <>
          <dl className="faixas">
            <Linha rotulo="Custo de restaurar" f={r.custoHa} fmt={fmtReais} unidade="por ha" ajuda="com acesso, relevo e pasto" />
            <Linha rotulo="Carbono tirado do ar" f={r.capturaHaAno} fmt={fmtNum1} unidade="t por ha por ano" ajuda="com chuva e solo" />
            <Linha
              rotulo="Crédito que sobra"
              f={r.creditoHaAno}
              fmt={fmtNum1}
              unidade="t por ha por ano"
              ajuda="menos linha de base, reserva de risco e incerteza"
            />
            <Linha rotulo="Valor presente" f={r.vplHa} fmt={fmtReais} unidade="por ha" ajuda="a 12% ao ano" />
            <Linha rotulo="Retorno sem financiamento" f={r.tirProjetoPct} fmt={fmtPct1} unidade="ao ano" />
            <Linha
              rotulo="Retorno com financiamento"
              f={r.tirAlavancadaPct}
              fmt={fmtPct1}
              unidade="ao ano"
              ajuda="80% pelo Fundo Clima"
            />
            <Linha rotulo="Dinheiro próprio no pior momento" f={r.picoCapitalHa} fmt={fmtReais} unidade="por ha" />
          </dl>

          <p className="bloco-resumo">
            Linha de base: sem projeto, cerca de {fmtInt(r.regeneraSozinhaPct)}% deste pasto viraria mata sozinho em 25
            anos. Esse carbono não vira crédito: o desconto é de {fmtInt(r.descontoLinhaBasePct)}% da captura
            {r.linhaBaseFonte === "padrao" ? " (taxa padrão; ainda sem a medida do município)" : " (medido nos pastos parecidos do município)"}.
          </p>

          {r.lote && (
            <p className="bloco-resumo">
              {r.lote.imoveis > 1
                ? `Junto com ${fmtInt(r.lote.imoveis - 1)} ${r.lote.imoveis === 2 ? "vizinha" : "vizinhas"}, são ${fmtHa(r.lote.ha)} e cerca de ${fmtInt(r.lote.creditosNoPrazo)} créditos em 25 anos.`
                : `Sozinha, são ${fmtHa(r.lote.ha)} e cerca de ${fmtInt(r.lote.creditosNoPrazo)} créditos em 25 anos.`}{" "}
              {r.lote.fechaContrato
                ? "O lote fecha um contrato de 1 milhão de créditos."
                : r.lote.haParaContrato
                  ? `Um contrato de 1 milhão de créditos pede cerca de ${fmtHa(r.lote.haParaContrato)} com este rendimento.`
                  : ""}
            </p>
          )}
        </>
      )}

      <details className="como-calculamos">
        <summary>Ver como calculamos</summary>
        <p>
          Cenário ProFloresta+ do BNDES: US$ 55 por tonelada, contrato de 25 anos com entregas nos anos 7, 12, 17, 22 e
          25, 80% financiado pelo Fundo Clima a 2,3% ao ano, 5 anos de carência e 20 de amortização. Faixa de P10 a P90
          por sorteio do custo e da captura. O vazamento (gado que muda de lugar) ainda não foi medido.
        </p>
        {r.faltou.length > 0 && <p>Faltou dado de {r.faltou.map(textoFaltou).join(", ")}: nesses itens valeu a premissa neutra.</p>}
        {r.versao && (
          <p>
            Versão do cálculo: <code>{r.versao}</code>
          </p>
        )}
      </details>
    </section>
  )
}
