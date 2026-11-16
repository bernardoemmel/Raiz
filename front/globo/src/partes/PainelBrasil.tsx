import type { EstadoDados, Estados, FunilMunicipio, PontoFazenda } from "../../../compartilhado/dados"
import { doEstado, fmtHa, fmtInt, UFS } from "../../../compartilhado/formato"
import { numerosDoBrasil } from "../../../compartilhado/funil-etapas"
import { linkEstado, linkMunicipio } from "../rota"
import { Estado } from "./Estado"
import { MiniBrasil } from "./MiniBrasil"
import { PainelCobertura } from "./PainelCobertura"
import type { CoberturaMapa } from "../../../compartilhado/dados/cobertura-mapa"
import type { ReactNode } from "react"

interface Props {
  municipios: FunilMunicipio[] | undefined
  comLista: Set<string>
  estados: Estados | undefined
  /** com estado escolhido, o painel é dele */
  uf: string | null
  /** fazendas aptas do estado escolhido, como estão no mapa */
  pontos: PontoFazenda[] | undefined
  carregando: boolean
  carregandoResumo?: boolean
  cobertura?: CoberturaMapa
  carregandoCobertura?: boolean
  andamento?: ReactNode
}

/** "Todos os 144 municípios"; "5 de 246 municípios"; "Ainda não processado" */
function situacaoDoEstado(e: EstadoDados): string {
  if (e.situacao === "sem_dados") return "Ainda não processado"
  if (e.situacao === "completo") return `Completo: todos os ${fmtInt(e.municipios_ibge)} municípios`
  if (e.municipios >= e.municipios_ibge) return `Todos os ${fmtInt(e.municipios_ibge)} municípios com dados`
  return `${fmtInt(e.municipios)} de ${fmtInt(e.municipios_ibge)} municípios`
}

/**
 * Detalhes em Sobre os dados: cobertura, resumos do motor e municípios com área medida.
 * Com um estado escolhido, restringe o resumo a ele e informa o que falta processar.
 */
export function PainelBrasil({ municipios, comLista, estados, uf, pontos, carregando, carregandoResumo = carregando, cobertura, carregandoCobertura, andamento }: Props) {
  if (uf) return <PainelEstado uf={uf} municipios={municipios} comLista={comLista} estados={estados} pontos={pontos} cobertura={cobertura} andamento={andamento} />
  if (!municipios) return <div className="painel-conteudo">
    <TituloBrasil />
    <div className={carregandoResumo ? "resumo-brasil-carregando" : undefined}>
      <Estado tipo={carregandoResumo ? "carregando" : "erro"} titulo={carregandoResumo ? "Lendo os municípios processados" : "Não foi possível ler o resumo dos municípios"} />
    </div>
    <PainelCobertura key="cobertura" cobertura={cobertura} carregando={carregandoCobertura} />
    {andamento}
  </div>
  if (!municipios.length)
    return (
      <div className="painel-conteudo"><TituloBrasil /><Estado tipo="vazio" titulo="Nenhum município processado ainda.">
        <p>O mapa mostra os estados assim que o motor rodar o primeiro.</p>
      </Estado><PainelCobertura key="cobertura" cobertura={cobertura} carregando={carregandoCobertura} />{andamento}</div>
    )
  const comDado = (estados?.estados ?? []).filter((e) => e.situacao !== "sem_dados")
  const semDado = (estados?.estados.length ?? 0) - comDado.length
  return (
    <div className="painel-conteudo">
      <TituloBrasil />
      <FraseResumo municipios={municipios} mostrarEstados />
      <Numeros municipios={municipios} />
      <PainelCobertura key="cobertura" cobertura={cobertura} carregando={carregandoCobertura} />
      {andamento}
      {comDado.length > 0 && (
        <section className="secao-painel" aria-labelledby="estados-titulo">
          <h2 id="estados-titulo">Dados disponíveis no mapa</h2>
          <ol className="lista-municipios lista-estados">
            {comDado.map((e) => (
              <li key={e.uf}>
                <a href={linkEstado(e.uf)}>
                  <span>
                    <strong>{e.nome}</strong>
                    <small>{situacaoDoEstado(e)}</small>
                  </span>
                  <span className={`selo ${e.situacao === "completo" ? "ok" : "neutro"}`}>{e.situacao === "completo" ? "Completo" : "Dados parciais"}</span>
                </a>
              </li>
            ))}
          </ol>
          {semDado > 0 && (
            <p className="legenda-frase">
              {semDado === 1 ? "Um estado ainda não tem resumo do motor" : `Os outros ${fmtInt(semDado)} estados ainda não têm resumo do motor`}.
              A cobertura dos cadastros agregados é independente desse resumo.
            </p>
          )}
        </section>
      )}
      <TopMunicipios municipios={municipios} comLista={comLista} />
      <p className="legenda-frase">
        A escala verde dos hexágonos mostra a quantidade de cadastros do CAR: tons mais claros indicam mais cadastros.
        Não é uma classificação de aptidão. Toque num hexágono para aproximar; a etiqueta informa os hectares conhecidos e quando a medida é parcial.
      </p>
      {carregando && <span className="sr">Carregando</span>}
    </div>
  )
}

function TituloBrasil() {
  return <div className="painel-titulo"><MiniBrasil uf={null} titulo="Onde estamos: Brasil" className="mini-titulo" /><h1>Resumo da análise do território</h1></div>
}

function PainelEstado({ uf, municipios, comLista, estados, cobertura, andamento }: Omit<Props, "uf" | "carregando"> & { uf: string }) {
  const e = estados?.estados.find((x) => x.uf === uf)
  const nome = e?.nome ?? UFS[uf] ?? uf
  const migalhas = (
    <ol className="migalhas" aria-label="Onde você está">
      <li>
        <a href="#/">Brasil</a>
      </li>
      <li aria-current="page">{nome}</li>
    </ol>
  )
  if (!e || !municipios)
    return (
      <div className="painel-conteudo">
        {migalhas}
        {andamento}
        <Estado tipo="carregando" titulo={`Lendo ${nome}`} />
      </div>
    )
  if (e.situacao === "sem_dados")
    return (
      <div className="painel-conteudo">
        {migalhas}
        <h1>{nome}</h1>
        {andamento}
        <PainelCobertura cobertura={cobertura} uf={uf} />
        <Estado tipo="vazio" titulo={`O estado ${doEstado(uf)} ainda não foi processado pela Raíz.`}>
          <p>
            Os {fmtInt(e.municipios_ibge)} municípios aparecem aqui assim que o motor rodar o estado. Até lá, o mapa
            mantém a base escura. Isso não significa ausência de cadastros ou de área para restaurar.
          </p>
        </Estado>
      </div>
    )
  const doUf = municipios.filter((m) => m.uf === uf)
  const faltam = Math.max(0, e.municipios_ibge - e.municipios)
  return (
    <div className="painel-conteudo">
      {migalhas}
      <h1>{nome}</h1>
      {andamento}
      <p className={`estado-situacao ${e.situacao}`}>
        {e.situacao === "completo"
          ? `Completo: todos os ${fmtInt(e.municipios_ibge)} municípios ${doEstado(uf)} já foram processados.`
          : faltam === 0
            ? `Todos os ${fmtInt(e.municipios_ibge)} municípios têm dados. O Release ainda registra o conjunto estadual como parcial.`
            : `${fmtInt(e.municipios)} de ${fmtInt(e.municipios_ibge)} municípios têm dados. ${
                faltam === 1 ? "Falta o resumo de 1 município." : `Faltam os resumos de ${fmtInt(faltam)} municípios.`
              } O conjunto estadual é parcial.`}
        {e.atualizado_em && ` Dados de ${new Date(e.atualizado_em).toLocaleDateString("pt-BR")}.`}
      </p>
      <PainelCobertura cobertura={cobertura} uf={uf} />
      {doUf.length > 0 ? (
        <>
          <FraseResumo municipios={doUf} />
          <Numeros municipios={doUf} />
          <TopMunicipios municipios={doUf} comLista={comLista} />
        </>
      ) : (
        <p className="frase">
          Os municípios já lidos têm a lista por fazenda, mas ainda não o resumo do estado. Toque num deles no mapa.
        </p>
      )}
      <p className="legenda-frase">
        De longe, cada hexágono reúne cadastros do CAR, incluindo imóveis ainda não aptos. Os hectares conhecidos podem cobrir apenas parte da célula.
        Ao aproximar, aparecem os limites disponíveis do CAR; no detalhe, o mosaico histórico serve de contexto. Toque num município para consultar seus dados.
      </p>
    </div>
  )
}

/** O resumo de aptidão e o cadastro cartográfico podem ter escopos e datas diferentes. */
function FraseResumo({ municipios, mostrarEstados = false }: { municipios: FunilMunicipio[]; mostrarEstados?: boolean }) {
  const n = numerosDoBrasil(municipios)
  const ufs = new Set(municipios.map((m) => m.uf)).size
  return <>
    <p className="frase">
      Resumo de aptidão disponível em {fmtInt(n.municipios)} {n.municipios === 1 ? "município" : "municípios"}
      {mostrarEstados ? ` de ${fmtInt(ufs)} ${ufs === 1 ? "estado" : "estados"}` : ""}: {fmtInt(n.imoveis)} imóveis do Cadastro Ambiental Rural (CAR).
      {" "}{fmtInt(n.prontas)} {n.prontas === 1 ? "fazenda tem" : "fazendas têm"} área apta e matrícula identificada
      {n.faltaTitulo > 0 ? ` e ${n.faltaTitulo === 1 ? "outra" : "outras"} ${fmtInt(n.faltaTitulo)} ${n.faltaTitulo === 1 ? "tem" : "têm"} área apta sem matrícula identificada` : ""}.
      Isso não comprova interesse do dono nem disponibilidade para venda.
    </p>
    <p className="legenda-frase">Fonte: resumos municipais do motor. A data específica desses resumos não foi informada no pacote. A cobertura atual dos desenhos pode abranger mais municípios.</p>
  </>
}

/** Medidas reais do resumo; as cores seguem o tema do analista. */
function Numeros({ municipios }: { municipios: FunilMunicipio[] }) {
  const n = numerosDoBrasil(municipios)
  return (
    <dl className="numeros">
      <div>
        <dt>Imóveis lidos</dt>
        <dd className="num">{fmtInt(n.imoveis)}</dd>
      </div>
      <div>
        <dt>Fazendas aptas</dt>
        <dd className="num">{fmtInt(n.aptas)}</dd>
      </div>
      <div>
        <dt>Podem voltar a ser mata</dt>
        <dd className="num destaque">{fmtHa(n.ha)}</dd>
      </div>
    </dl>
  )
}

function TopMunicipios({ municipios, comLista }: { municipios: FunilMunicipio[]; comLista: Set<string> }) {
  const top = [...municipios].sort((a, b) => b.ha_carbono - a.ha_carbono).slice(0, 8)
  return (
    <section className="secao-painel" aria-labelledby="top-titulo">
      <h2 id="top-titulo">Municípios com mais área para restaurar</h2>
      <ol className="lista-municipios">
        {top.map((m) => (
          <li key={m.cod_ibge}>
            <a href={linkMunicipio(m.cod_ibge)}>
              <span>
                <strong>{m.municipio}</strong>
                <small>{comLista.has(m.cod_ibge) ? "Lista por fazenda pronta" : "Funil pronto, lista a caminho"}</small>
              </span>
              <span className="num">{fmtHa(m.ha_carbono)}</span>
            </a>
          </li>
        ))}
      </ol>
    </section>
  )
}
