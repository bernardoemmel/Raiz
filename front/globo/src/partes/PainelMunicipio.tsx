import { useMemo, useState } from "react"
import { escreverCsv } from "../../../compartilhado/dados/csv"
import type { FunilMunicipio, Imovel } from "../../../compartilhado/dados"
import {
  MOTIVOS,
  SITUACOES,
  etapaDe,
  etapasDoFunil,
  etapasDoResumo,
  fraseDoMunicipio,
  noFoco,
  situacaoDe,
  type Foco,
} from "../../../compartilhado/funil-etapas"
import { fmtInt, UFS } from "../../../compartilhado/formato"
import { ESCALA_FOGO, PERIODO_FOGO } from "../../../compartilhado/satelite"
import { frenteDe, tituloDe } from "../filtros"
import type { CamadaAssunto } from "../mapa/MapaBrasil"
import { Estado } from "./Estado"
import { FunilBarras, type Unidade } from "./FunilBarras"
import { Download } from "./Icones"
import { MiniBrasil } from "./MiniBrasil"
import { Projeto } from "./Projeto"
import { TabelaFazendas } from "./TabelaFazendas"

interface Props {
  cod: string
  nome: string | null
  uf: string | null
  centro: [number, number] | null
  funil: FunilMunicipio | null | undefined
  imoveis: Imovel[] | null | undefined
  foco: Foco
  aoFocar: (f: Foco) => void
  camada: CamadaAssunto
  mudarCamada: (c: CamadaAssunto) => void
  aoPassar: (cod: string | null) => void
}

const CAMADAS: { id: CamadaAssunto | "uso"; rotulo: string; desligada?: string }[] = [
  { id: "situacao", rotulo: "Situação" },
  { id: "titulo", rotulo: "Título" },
  { id: "fogo", rotulo: "Fogo" },
  { id: "uso", rotulo: "Uso da terra", desligada: "Mata, pasto e lavoura dentro de cada fazenda chegam com o back-end." },
]

function baixarCsv(nome: string, lista: Imovel[]) {
  const colunas = ["cod_imovel", "municipio", "uf", "ha", "m_fiscal", "situacao", "etapa", "motivo_saida", "carbono_ha", "carbono_tco2_ano", "titulo"]
  const linhas = lista.map((i) => {
    const { etapa, motivo } = etapaDe(i)
    return {
      cod_imovel: i.cod_imovel,
      municipio: i.municipio,
      uf: i.uf,
      ha: i.ha.toFixed(2),
      m_fiscal: i.m_fiscal ?? "",
      situacao: situacaoDe(i),
      etapa,
      motivo_saida: motivo ?? "",
      carbono_ha: i.apta ? i.carbono_ha.toFixed(2) : "0",
      carbono_tco2_ano: i.apta ? Math.round(i.carbono_tco2_ano) : 0,
      titulo: tituloDe(i),
    }
  })
  const a = document.createElement("a")
  a.href = URL.createObjectURL(new Blob([escreverCsv(colunas, linhas)], { type: "text/csv;charset=utf-8" }))
  a.download = nome
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

/** O que cada cor do mapa quer dizer, em uma frase ou numa lista curta (guia, item 2.5). */
function Legenda({ camada, foco, imoveis }: { camada: CamadaAssunto; foco: Foco; imoveis: Imovel[] }) {
  if (foco?.lado === "fora") {
    const motivos = [...new Set(imoveis.filter((i) => noFoco(i, foco)).map((i) => etapaDe(i).motivo).filter(Boolean))]
    return (
      <ul className="legenda-lista" aria-label="Por que saíram">
        {motivos.map((m) => (
          <li key={m}>
            <i style={{ background: MOTIVOS[m!].cor }} />
            {MOTIVOS[m!].rotulo}
          </li>
        ))}
        <li>
          <i className="apagada" />
          As outras fazendas, em cinza claro
        </li>
      </ul>
    )
  }
  if (camada === "titulo")
    return (
      <p className="legenda-frase">
        Verde-escuro é matrícula no SIGEF, verde-claro é lote de assentamento e amarelo é posse sem matrícula.
      </p>
    )
  if (camada === "fogo")
    return (
      <ul className="legenda-lista" aria-label={`Fogo, ${PERIODO_FOGO}`}>
        <li>
          <i className="contorno" style={{ borderColor: ESCALA_FOGO[0][1] }} />
          Fogo em 1 a 2 anos ({PERIODO_FOGO})
        </li>
        <li>
          <i className="contorno" style={{ borderColor: ESCALA_FOGO[1][1] }} />3 a 5 anos
        </li>
        <li>
          <i className="contorno" style={{ borderColor: ESCALA_FOGO[2][1] }} />6 anos ou mais
        </li>
        <li>
          <i className="circulo" />
          Queimou em 2025, o tamanho é a área
        </li>
      </ul>
    )
  return (
    <ul className="legenda-lista" aria-label="Situação">
      {SITUACOES.map((s) => (
        <li key={s.id}>
          <i className={s.cruzada ? "cruzada" : undefined} style={{ background: s.cruzada ? undefined : s.cor }} />
          <span>
            <strong>{s.rotulo}</strong>: {s.texto}
          </span>
        </li>
      ))}
      {foco && (
        <li>
          <i className="apagada" />
          Fora da etapa escolhida, em cinza claro
        </li>
      )}
    </ul>
  )
}

export function PainelMunicipio(props: Props) {
  const { cod, nome, uf, centro, funil, imoveis, foco, aoFocar, camada, mudarCamada, aoPassar } = props
  const [unidade, setUnidade] = useState<Unidade>("imoveis")
  const [projeto, setProjeto] = useState(false)
  const etapas = useMemo(
    () => (imoveis ? etapasDoFunil(imoveis) : funil ? etapasDoResumo(funil) : null),
    [imoveis, funil],
  )
  const lista = useMemo(() => {
    if (!imoveis) return []
    const base = foco ? imoveis.filter((i) => noFoco(i, foco)) : imoveis.filter((i) => i.apta)
    return [...base].sort((a, b) => (b.apta ? b.carbono_ha : 0) - (a.apta ? a.carbono_ha : 0))
  }, [imoveis, foco])
  const nomeMun = funil?.municipio ?? nome ?? "Município"
  const sigla = funil?.uf ?? uf ?? ""
  const ufNome = UFS[sigla] ?? sigla

  return (
    <div className="painel-conteudo">
      <ol className="migalhas" aria-label="Onde você está">
        <li>
          <a href="#/">Brasil</a>
        </li>
        {ufNome && <li>{ufNome}</li>}
        <li aria-current="page">{nomeMun}</li>
      </ol>
      <div className="painel-titulo">
        <h1>{nomeMun}</h1>
        <MiniBrasil
          uf={sigla}
          lon={centro?.[0]}
          lat={centro?.[1]}
          titulo={`Fica ${ufNome ? `no estado ${ufNome === "Pará" ? "do Pará" : `de ${ufNome}`}` : "no Brasil"}`}
          className="mini-titulo"
        />
      </div>

      {funil === undefined && imoveis === undefined ? (
        <Estado tipo="carregando" titulo={`Carregando ${nomeMun}`} />
      ) : !funil && !imoveis ? (
        <Estado tipo="vazio" titulo="Este município ainda não foi processado pela Raíz.">
          <p>
            {ufNome && !["Pará"].includes(ufNome)
              ? `${ufNome} ainda não foi lido. Por enquanto, a Raíz cobre o Pará.`
              : "O funil aparece aqui quando o motor rodar o município."}
          </p>
        </Estado>
      ) : (
        <>
          <p className="frase">{fraseDoMunicipio(funil ?? null, etapas ?? [], fmtInt)}</p>

          {imoveis && (
            <div className="camadas" role="radiogroup" aria-label="Mostrar no mapa">
              {CAMADAS.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  role="radio"
                  aria-checked={camada === c.id}
                  disabled={!!c.desligada}
                  title={c.desligada ?? "MapBiomas coleção 11, 30 m, 2025; CAR e SIGEF da amostra do motor"}
                  onClick={() => c.id !== "uso" && mudarCamada(c.id)}
                >
                  {c.rotulo}
                </button>
              ))}
            </div>
          )}
          {imoveis && <Legenda camada={camada} foco={foco} imoveis={imoveis} />}

          {etapas && <FunilBarras etapas={etapas} foco={foco} aoFocar={aoFocar} unidade={unidade} mudarUnidade={setUnidade} />}

          {imoveis ? (
            <section className="secao-painel" aria-labelledby="lista-titulo">
              <div className="secao-cabeca">
                <h2 id="lista-titulo">{foco ? "Fazendas da seleção" : "Fazendas aptas"}</h2>
                <div className="acoes">
                  <button
                    type="button"
                    className="botao"
                    disabled={!lista.length}
                    onClick={() => baixarCsv(`raiz_${cod}_${foco ? `${foco.etapa}_${foco.lado}` : "aptas"}.csv`, lista)}
                  >
                    <Download size={20} aria-hidden="true" /> Baixar planilha
                  </button>
                  <button type="button" className="botao principal" disabled={!lista.some((i) => i.apta)} onClick={() => setProjeto(true)}>
                    Montar projeto
                  </button>
                </div>
              </div>
              {lista.length ? (
                <TabelaFazendas lista={lista} aoPassar={aoPassar} />
              ) : (
                <Estado tipo="vazio" titulo={funil?.aptas_carbono === 0 ? `Nenhuma fazenda apta em ${nomeMun}.` : "Nenhuma fazenda nesta seleção."} />
              )}
            </section>
          ) : (
            <Estado tipo="vazio" titulo="A lista por fazenda ainda não foi processada.">
              <p>O funil acima vem do resumo do motor. As fazendas aparecem no mapa e aqui quando o motor rodar o município.</p>
            </Estado>
          )}
        </>
      )}
      <p className="rodape-painel">
        Dados públicos: Cadastro Ambiental Rural (CAR), PRODES e TerraBrasilis (INPE), MapBiomas, Ibama e SIGEF (INCRA).
        Carbono bruto, antes de descontar linha de base e vazamento.
      </p>
      {projeto && imoveis && (
        <Projeto
          lista={lista.filter((i) => i.apta)}
          frente={frenteDe("carbono")}
          municipio={nomeMun}
          fechar={() => setProjeto(false)}
          baixar={() => baixarCsv(`raiz_${cod}_projeto.csv`, lista.filter((i) => i.apta))}
        />
      )}
    </div>
  )
}
