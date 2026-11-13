import type { EstadoDados, Estados, FunilMunicipio, PontoFazenda } from "../../../compartilhado/dados"
import { doEstado, fmtHa, fmtInt, UFS } from "../../../compartilhado/formato"
import { fraseDoBrasil, numerosDoBrasil } from "../../../compartilhado/funil-etapas"
import { linkEstado, linkMunicipio } from "../rota"
import { Estado } from "./Estado"
import { MiniBrasil } from "./MiniBrasil"
import { PainelCobertura } from "./PainelCobertura"
import type { CoberturaMapa } from "../../../compartilhado/dados/cobertura-mapa"

interface Props {
  municipios: FunilMunicipio[] | undefined
  comLista: Set<string>
  estados: Estados | undefined
  /** com estado escolhido, o painel é dele */
  uf: string | null
  /** fazendas aptas do estado escolhido, como estão no mapa */
  pontos: PontoFazenda[] | undefined
  carregando: boolean
  cobertura?: CoberturaMapa
}

/** "Todos os 144 municípios"; "5 de 246 municípios"; "Ainda não processado" */
function situacaoDoEstado(e: EstadoDados): string {
  if (e.situacao === "sem_dados") return "Ainda não processado"
  if (e.situacao === "completo") return `Completo: todos os ${fmtInt(e.municipios_ibge)} municípios`
  if (e.municipios >= e.municipios_ibge) return `Todos os ${fmtInt(e.municipios_ibge)} municípios com dados`
  return `${fmtInt(e.municipios)} de ${fmtInt(e.municipios_ibge)} municípios`
}

/**
 * O Brasil na primeira tela (números do que a Raíz já leu, os estados e os municípios com mais área para restaurar) ou,
 * com um estado escolhido, o mesmo painel só daquele estado, dizendo se ele está completo.
 */
export function PainelBrasil({ municipios, comLista, estados, uf, pontos, carregando, cobertura }: Props) {
  if (uf) return <PainelEstado uf={uf} municipios={municipios} comLista={comLista} estados={estados} pontos={pontos} cobertura={cobertura} />
  if (!municipios) return <div className="painel-conteudo"><TituloBrasil /><Estado tipo="carregando" titulo="Lendo os municípios processados" /></div>
  if (!municipios.length)
    return (
      <Estado tipo="vazio" titulo="Nenhum município processado ainda.">
        <p>O mapa mostra os estados assim que o motor rodar o primeiro.</p>
      </Estado>
    )
  const n = numerosDoBrasil(municipios)
  const ufs = [...new Set(municipios.map((m) => UFS[m.uf] ?? m.uf))]
  const comDado = (estados?.estados ?? []).filter((e) => e.situacao !== "sem_dados")
  const semDado = (estados?.estados.length ?? 0) - comDado.length
  return (
    <div className="painel-conteudo">
      <TituloBrasil />
      <p className="frase">{fraseDoBrasil(n, ufs, fmtInt)}</p>
      <Numeros municipios={municipios} />
      <PainelCobertura cobertura={cobertura} />
      {comDado.length > 0 && (
        <section className="secao-painel" aria-labelledby="estados-titulo">
          <h2 id="estados-titulo">Estados</h2>
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
              {semDado === 1 ? "Um estado ainda não foi processado" : `Os outros ${fmtInt(semDado)} estados ainda não foram processados`}: ficam em cinza no
              mapa.
            </p>
          )}
        </section>
      )}
      <TopMunicipios municipios={municipios} comLista={comLista} />
      <p className="legenda-frase">
        No mapa, verde-claro indica estados com municípios processados e cinza é o que a Raíz ainda não leu.
        Toque num estado para aproximar e consultar o potencial conhecido por célula.
      </p>
      {carregando && <span className="sr">Carregando</span>}
    </div>
  )
}

function TituloBrasil() {
  return <div className="painel-titulo"><MiniBrasil uf={null} titulo="Onde estamos: Brasil" className="mini-titulo" /><h1>Onde dá para restaurar, com dono e título</h1></div>
}

function PainelEstado({ uf, municipios, comLista, estados, cobertura }: Omit<Props, "uf" | "carregando"> & { uf: string }) {
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
        <Estado tipo="carregando" titulo={`Lendo ${nome}`} />
      </div>
    )
  if (e.situacao === "sem_dados")
    return (
      <div className="painel-conteudo">
        {migalhas}
        <h1>{nome}</h1>
        <PainelCobertura cobertura={cobertura} uf={uf} />
        <Estado tipo="vazio" titulo={`O estado ${doEstado(uf)} ainda não foi processado pela Raíz.`}>
          <p>
            Os {fmtInt(e.municipios_ibge)} municípios aparecem aqui assim que o motor rodar o estado. Até lá, o mapa
            mostra o estado em cinza.
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
      <p className={`estado-situacao ${e.situacao}`}>
        {e.situacao === "completo"
          ? `Completo: todos os ${fmtInt(e.municipios_ibge)} municípios ${doEstado(uf)} já foram processados.`
          : faltam === 0
            ? `Todos os ${fmtInt(e.municipios_ibge)} municípios têm dados. O Release ainda registra o conjunto estadual como parcial.`
            : `${fmtInt(e.municipios)} de ${fmtInt(e.municipios_ibge)} municípios têm dados. ${
                faltam === 1 ? "Falta 1, em cinza no mapa." : `Faltam ${fmtInt(faltam)}, em cinza no mapa.`
              } O conjunto estadual é parcial.`}
        {e.atualizado_em && ` Dados de ${new Date(e.atualizado_em).toLocaleDateString("pt-BR")}.`}
      </p>
      <PainelCobertura cobertura={cobertura} uf={uf} />
      {doUf.length > 0 ? (
        <>
          <p className="frase">{fraseDoBrasil(numerosDoBrasil(doUf), [], fmtInt)}</p>
          <Numeros municipios={doUf} />
          <TopMunicipios municipios={doUf} comLista={comLista} />
        </>
      ) : (
        <p className="frase">
          Os municípios já lidos têm a lista por fazenda, mas ainda não o resumo do estado. Toque num deles no mapa.
        </p>
      )}
      <p className="legenda-frase">
        De longe, as células mostram potencial conhecido com cobertura parcial. Ao aproximar, aparecem os limites
        transparentes do CAR sobre o mosaico histórico. Toque num município para consultar seus dados.
      </p>
    </div>
  )
}

/** urucum só no número que mais importa para a ação: a área que pode voltar a ser mata */
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
