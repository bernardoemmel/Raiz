import { useMemo, useState } from "react"
import { fonteAcerto, METRICAS_ACERTO, type MetricaAcerto } from "../../../compartilhado/acerto"
import { useCarga } from "../dados"
import { Cabecalho } from "../partes/Cabecalho"
import { Estado } from "../partes/Estado"
import "./acerto-modelo.css"

const ALVOS: Record<string, { nome: string; unidade: string }> = {
  area_ha: { nome: "Área", unidade: "ha" },
  restauracao_custo_rs_ha: { nome: "Custo da restauração", unidade: "R$/ha" },
  restauracao_captura_tco2_ha_ano: { nome: "Captura de carbono", unidade: "tCO2/ha/ano" },
  restauracao_credito_liquido_tco2_ha_ano: { nome: "Crédito líquido", unidade: "tCO2/ha/ano" },
}
const nomeAlvo = (alvo: string) => ALVOS[alvo]?.nome ?? alvo.replaceAll("_", " ")
const unidadeMetrica = (alvo: string, metrica: string) => {
  const unidade = ALVOS[alvo]?.unidade
  return unidade && ["wis", "ae", "ae_mediana", "eq"].includes(metrica) ? ` ${metrica === "eq" ? `(${unidade})²` : unidade}` : ""
}
const consultar = fonteAcerto({ api: import.meta.env.VITE_RAIZ_API, base: import.meta.env.BASE_URL })
const numero = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 })
const percentual = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 })
const data = (v: string) => new Date(`${v.slice(0, 10)}T12:00:00Z`).toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" })

export function AcertoModelo() {
  const [tentativa, setTentativa] = useState(0)
  const [modelo, setModelo] = useState("")
  const [alvo, setAlvo] = useState("")
  const [versao, setVersao] = useState("")
  const carga = useCarga(consultar, [tentativa])
  const resumo = carga.dado
  const modelos = useMemo(() => [...new Set(resumo?.versoes.map((v) => v.modelo))].sort(), [resumo])
  const alvos = useMemo(() => [...new Set(resumo?.versoes.filter((v) => !modelo || v.modelo === modelo).map((v) => v.alvo))].sort(), [resumo, modelo])
  const versoes = useMemo(() => [...new Set(resumo?.versoes.filter((v) => (!modelo || v.modelo === modelo) && (!alvo || v.alvo === alvo)).map((v) => v.versao))].sort(), [resumo, modelo, alvo])
  const linhas = resumo?.versoes.filter((v) => (!modelo || v.modelo === modelo) && (!alvo || v.alvo === alvo) && (!versao || v.versao === versao)) ?? []
  return <>
    <Cabecalho atual="acerto" />
    <main id="conteudo" tabIndex={-1} className="pagina acerto-modelo">
      <h1>Acerto do modelo</h1>
      <p className="frase">Quanto as previsões de cada versão se aproximaram do que foi observado no mundo real.</p>
      <p>As notas usam observações na data-alvo de cada previsão, com fonte e registro congelado. Avaliações ao vivo e retrospectivas aparecem separadas.</p>
      <details className="acerto-leitura"><summary>Como ler as notas</summary><p>Crédito, custo e área usam erros na unidade do alvo. Previsões de categoria usam a parcela correta. Uma chance precisa ser avaliada também pelo erro de probabilidade: acertar uma categoria não basta.</p><p>A faixa P10 a P90 deve conter aproximadamente 80% das observações ao longo do tempo. Uma única nota não resume modelos que fazem tarefas diferentes. Sem um período de medição estruturado, só a data-alvo exata confirma o mesmo horizonte. Medições antecipadas ou tardias e eventos sem janela comprovada ficam fora. Essa cobertura restrita não representa todas as observações. Grupos ainda sem resultado, com menos de cinco imóveis ou com tipos incompatíveis não são misturados.</p></details>
      <div aria-live="polite" aria-busy={carga.carregando}>
        {carga.carregando ? <Estado tipo="carregando" titulo="Consultando o aprendizado" /> : carga.erro ? <Estado tipo="erro" titulo="Não foi possível consultar o aprendizado agora."><p>Os resultados não foram substituídos por zero.</p><button className="botao" onClick={() => setTentativa((t) => t + 1)}>Tentar de novo</button></Estado> : !resumo?.versoes.length ? <Estado tipo="vazio" titulo="Ainda não há comparações reais publicáveis.">
          <p>O painel aguarda observações na data-alvo e registros que comprovem a cronologia. Dados de outro período ou sem essa prova ficam fora, sem receber nota zero. Cada grupo precisa de pelo menos {resumo?.minimo_imoveis ?? 5} imóveis distintos para preservar os dados individuais. Um grupo sem evidência suficiente não recebe nota zero.</p>
          <p>{resumo?.gerado_em ? `Última conferência do aprendizado: ${data(resumo.gerado_em)}.` : "Ainda não há uma publicação do aprendizado ligada a este site."}</p>
        </Estado> : <>
          <p className="acerto-fonte">Fonte: {resumo.fonte}. Resumo gerado em <time dateTime={resumo.gerado_em!}>{data(resumo.gerado_em!)}</time>. Nenhuma fazenda ou proprietário é identificado.</p>
          <form className="acerto-filtros" aria-label="Filtrar o acerto" onSubmit={(e) => e.preventDefault()}>
            <label className="campo">Modelo<select aria-label="Modelo" value={modelo} onChange={(e) => { setModelo(e.target.value); setAlvo(""); setVersao("") }}><option value="">Todos os modelos</option>{modelos.map((m) => <option key={m}>{m}</option>)}</select></label>
            <label className="campo">O que foi previsto<select aria-label="O que foi previsto" value={alvo} onChange={(e) => { setAlvo(e.target.value); setVersao("") }}><option value="">Todos os alvos</option>{alvos.map((a) => <option key={a} value={a}>{nomeAlvo(a)}</option>)}</select></label>
            <label className="campo">Versão<select aria-label="Versão" value={versao} onChange={(e) => setVersao(e.target.value)}><option value="">Todas as versões</option>{versoes.map((v) => <option key={v}>{v}</option>)}</select></label>
          </form>
          <p role="status">{linhas.length} {linhas.length === 1 ? "grupo de comparação" : "grupos de comparação"}.</p>
          <p className="aviso">Compare o mesmo alvo e horizonte. Versões podem ter sido observadas em imóveis e períodos diferentes; estas médias não provam que uma versão seja melhor. As observações disponíveis podem não representar todas as fazendas. A troca do modelo exige a avaliação própria de campeão e desafiante.</p>
          <div className="acerto-grupos">{linhas.map((v) => <section className="acerto-grupo" key={`${v.modelo}-${v.versao}-${v.alvo}-${v.horizonte_dias}-${v.tipo}-${v.avaliacao}`} aria-label={`${v.modelo}, versão ${v.versao}, ${v.alvo}`}>
            <h2>{v.modelo} <span>versão {v.versao}</span></h2>
            <p><strong>{v.avaliacao === "backtest" ? "Avaliação retrospectiva" : "Avaliação ao vivo"}</strong>. {v.avaliacao === "backtest" ? "Reexecução declarada no registro; esta nota não comprova separação entre treino e teste nem acerto em operação ao vivo." : "O registro imutável comprova congelamento antes do dia observado. O gabarito corresponde à data-alvo do horizonte."}</p>
            <p><strong>{nomeAlvo(v.alvo)}</strong>. Horizonte de {numero.format(v.horizonte_dias)} dias.</p>
            <p>{numero.format(v.comparacoes)} comparações em {numero.format(v.imoveis_observados)} imóveis distintos. Uma fazenda pode ter mais de uma previsão.</p>
            {v.imoveis_observados < 30 && <p className="aviso">Evidência inicial: menos de 30 imóveis observados. A nota pode mudar bastante com novas observações.</p>}
            <dl className="acerto-medidas">{Object.entries(v.metricas).map(([nome, valor]) => {
              const m = METRICAS_ACERTO[nome as MetricaAcerto]
              return <div key={nome}><dt>{m.nome}</dt><dd><strong>{m.percentual ? percentual.format(valor!) : numero.format(valor!)}{unidadeMetrica(v.alvo, nome)}</strong><small>{m.ajuda}</small></dd></div>
            })}</dl>
            <p className="acerto-fonte">Cortes das previsões: <time dateTime={v.primeiro_corte}>{data(v.primeiro_corte)}</time> a <time dateTime={v.ultimo_corte}>{data(v.ultimo_corte)}</time>. Última observação: <time dateTime={v.ultima_observacao}>{data(v.ultima_observacao)}</time>. Fonte: aprendizado da Raíz, pareamento com gabaritos registrados.</p>
          </section>)}</div>
        </>}
      </div>
    </main>
  </>
}
