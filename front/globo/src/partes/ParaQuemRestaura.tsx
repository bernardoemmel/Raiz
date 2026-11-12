import type { Imovel } from "../../../compartilhado/dados"
import { fmtHa, fmtInt } from "../../../compartilhado/formato"
import {
  AVISO,
  descricaoCenario,
  fmtFaixa,
  fmtNum1,
  fmtPct1,
  fmtReais,
  lerRestauracao,
  MODOS,
  NOMES_DONO,
  textoFaltou,
  type Faixa,
  type Restauracao,
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

/** Descontos do bruto ao líquido, na ordem da rodada 11. */
function Descontos({ r }: { r: Restauracao }) {
  const d = r.descontos
  const itens = [
    {
      nome: "Linha de base",
      pct: d.linhaBase,
      nota:
        d.linhaBaseMedida !== null && d.linhaBaseMedida < d.linhaBase
          ? `medida de ${fmtPct1(d.linhaBaseMedida)}, com o piso do cenário`
          : "o que a mata faria sozinha",
    },
    { nome: "Vazamento", pct: d.vazamento, nota: d.vazamento > 0 ? "gado que muda de lugar" : "fazenda vizinha de mitigação no lote, ou ainda sem medida" },
    { nome: "Reserva de risco", pct: d.reserva, nota: "não permanência" },
    { nome: "Incerteza", pct: d.incerteza, nota: "medição" },
  ]
  return (
    <table className="marcos">
      <caption className="bloco-resumo">Do carbono tirado do ar ao crédito, nesta ordem</caption>
      <tbody>
        {itens.map((x) => (
          <tr key={x.nome}>
            <th scope="row">{x.nome}</th>
            <td className="num">{fmtPct1(x.pct)}</td>
            <td>{x.nota}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const META_MARCO: Record<number, number> = { 7: 12, 12: 30, 17: 50, 22: 70, 25: 100 }

function Marcos({ r }: { r: Restauracao }) {
  if (r.marcos.length === 0) return null
  return (
    <>
      <table className="marcos">
        <caption className="bloco-resumo">Marcos do ProFloresta+: chance de entregar cada um</caption>
        <thead>
          <tr>
            <th scope="col">Ano</th>
            <th scope="col">Meta acumulada</th>
            <th scope="col">Chance de cumprir</th>
          </tr>
        </thead>
        <tbody>
          {r.marcos.map((m) => (
            <tr key={m.ano}>
              <th scope="row" className="num">
                {m.ano}
              </th>
              <td className="num">{META_MARCO[m.ano] !== undefined ? `${META_MARCO[m.ano]}%` : ""}</td>
              <td className="num">{fmtPct1(m.chancePct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="bloco-resumo">
        {r.marcosTodosPct !== null && <>Chance de cumprir todos: {fmtPct1(r.marcosTodosPct)}. </>}
        {r.multaEsperadaHa !== null && <>Multa esperada: {fmtReais(r.multaEsperadaHa)} por ha. </>}
        {r.rescisaoPct !== null && <>Chance de rescisão: {fmtPct1(r.rescisaoPct)}.</>}
      </p>
    </>
  )
}

function Dono({ r }: { r: Restauracao }) {
  const d = r.dono
  const partes: string[] = []
  if (d.rsHaAno !== null) partes.push(`Dono da terra: ${NOMES_DONO[d.forma]}, cerca de ${fmtReais(d.rsHaAno)} por ha por ano.`)
  if (d.forma !== "arrendamento" && d.aluguelRef !== null && d.tirAluguel !== null) {
    const queda = d.tirAluguel < r.tirProjetoPct.p50 - 0.05
    partes.push(
      queda
        ? `Com aluguel fixo de ${fmtReais(d.aluguelRef)} por ha por ano (Censo Agro 2017) o retorno sem financiamento cai de ${fmtPct1(r.tirProjetoPct.p50)} para ${fmtPct1(d.tirAluguel)}: o aluguel sai todo ano, antes de haver crédito.`
        : `Com aluguel fixo de ${fmtReais(d.aluguelRef)} por ha por ano (Censo Agro 2017) o retorno sem financiamento ficaria em ${fmtPct1(d.tirAluguel)}, mas o dono não divide o risco da captura.`,
    )
  }
  if (d.tirDuasFases !== null && d.forma !== "duas_fases")
    partes.push(`Aceite em duas fases (pagamento pequeno até o leilão): ${fmtPct1(d.tirDuasFases)}.`)
  if (partes.length === 0) return null
  return <p className="bloco-resumo">{partes.join(" ")}</p>
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
  const cen = descricaoCenario(r.cenario)
  const curva = r.capturaModelo === "curva"
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
            <Linha
              rotulo="Carbono tirado do ar"
              f={r.capturaHaAno}
              fmt={fmtNum1}
              unidade="t por ha por ano"
              ajuda={curva ? "média em 40 anos, em curva: nada nos anos 1 e 2, pico no ano 14" : "com chuva e solo"}
            />
            {r.creditoContratoHa ? (
              <Linha
                rotulo="Crédito até o ano 25"
                f={r.creditoContratoHa}
                fmt={fmtNum1}
                unidade="t por ha"
                ajuda="depois dos descontos, no prazo do contrato"
              />
            ) : (
              <Linha
                rotulo="Crédito que sobra"
                f={r.creditoHaAno}
                fmt={fmtNum1}
                unidade="t por ha por ano"
                ajuda="menos linha de base, reserva de risco e incerteza"
              />
            )}
            <Linha rotulo="Valor presente" f={r.vplHa} fmt={fmtReais} unidade="por ha" ajuda={cen.taxa} />
            <Linha rotulo="Retorno sem financiamento" f={r.tirProjetoPct} fmt={fmtPct1} unidade="ao ano" />
            <Linha
              rotulo="Retorno com financiamento"
              f={r.tirAlavancadaPct}
              fmt={fmtPct1}
              unidade="ao ano"
              ajuda={r.divida ? `Fundo Clima, ${fmtInt(r.divida.fracao * 100)}% do investimento` : cen.financiamento}
            />
            <Linha rotulo="Dinheiro próprio no pior momento" f={r.picoCapitalHa} fmt={fmtReais} unidade="por ha" />
          </dl>

          <p className="bloco-resumo">
            Linha de base: sem projeto, cerca de {fmtInt(r.regeneraSozinhaPct)}% deste pasto viraria mata sozinho em{" "}
            {curva ? 40 : 25} anos. Esse carbono não vira crédito: o desconto é de {fmtInt(r.descontoLinhaBasePct)}% da
            captura
            {r.linhaBaseFonte === "padrao" ? " (taxa padrão; ainda sem a medida do município)" : " (medido nos pastos parecidos do município)"}.
          </p>
          <Descontos r={r} />
          <Marcos r={r} />
          <Dono r={r} />
          {r.precoEquilibrioUsd !== null && (
            <p className="bloco-resumo">
              Preço que paga o projeto {cen.taxa}: cerca de US$ {fmtNum1(r.precoEquilibrioUsd)} por crédito
              {r.custoCreditoUsd !== null && <> (custo por crédito vendido: US$ {fmtNum1(r.custoCreditoUsd)})</>}.
            </p>
          )}

          {r.lote && (
            <p className="bloco-resumo">
              {r.lote.imoveis > 1
                ? `Junto com ${fmtInt(r.lote.imoveis - 1)} ${r.lote.imoveis === 2 ? "vizinha" : "vizinhas"}, são ${fmtHa(r.lote.ha)} e cerca de ${fmtInt(r.lote.creditosNoPrazo)} créditos até o ano 25.`
                : `Sozinha, são ${fmtHa(r.lote.ha)} e cerca de ${fmtInt(r.lote.creditosNoPrazo)} créditos até o ano 25.`}{" "}
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
          Cenário {cen.nome}. {cen.texto} Faixa de P10 a P90 por sorteio do custo e da captura; o P50 é o caminho do meio.
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
