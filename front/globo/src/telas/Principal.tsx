import { useCallback, useMemo, useState, type Ref } from "react"
import type { FunilMunicipio, Imovel } from "../../../compartilhado/dados"
import { escreverCsv } from "../../../compartilhado/dados/csv"
import { fmtInt, UFS } from "../../../compartilhado/formato"
import { ordenarFiltrar, type Modo, type OrdemRestauracao } from "../../../compartilhado/restauracao"
import { fonte, useCarga } from "../dados"
import { aplicar, FILTROS_INICIAIS, frenteDe, tituloDe, type Filtros as F } from "../filtros"
import { MapaMunicipio, type MapaApi } from "../mapa/MapaMunicipio"
import { Cabecalho } from "../partes/Cabecalho"
import { Filtros, type Camadas } from "../partes/Filtros"
import { Funil, type Etapa } from "../partes/Funil"
import { IconeBaixar } from "../partes/Icones"
import { ListaFazendas } from "../partes/ListaFazendas"
import { Projeto } from "../partes/Projeto"
import { linkMunicipio } from "../rota"

const TODOS_TITULOS: F["titulos"] = ["matricula", "assentamento", "posse"]
const PRESETS: Record<string, F> = {
  aptas: { frente: "carbono", titulos: TODOS_TITULOS, semDesmate: "10" },
  matricula: { frente: "carbono", titulos: ["matricula"], semDesmate: "10" },
  agrupar: { frente: "agrupar", titulos: TODOS_TITULOS, semDesmate: "10" },
}
const igual = (a: F, b: F) =>
  a.frente === b.frente && a.semDesmate === b.semDesmate && [...a.titulos].sort().join() === [...b.titulos].sort().join()

function baixarCsv(nome: string, lista: Imovel[], f: F) {
  const frente = frenteDe(f.frente)
  const colunas = [
    "cod_imovel",
    "municipio",
    "uf",
    "ha",
    "m_fiscal",
    "frente_motor",
    "categoria",
    "area_da_frente_ha",
    "carbono_ha",
    "carbono_tco2_ano",
    "titulo",
    "f_matricula",
    "desm_pos2016_ha",
    "alerta_pos2020_ha",
    "status_imovel",
    "modo_restauracao",
    "custo_restauracao_ha_p50",
    "credito_liquido_tco2_ha_ano",
    "vpl_rs_ha_p50",
    "tir_alavancada_pct_p50",
    "valor_desenvolvedor_rs",
    "grupo_id",
  ]
  const linhas = lista.map((i) => ({
    cod_imovel: i.cod_imovel,
    municipio: i.municipio,
    uf: i.uf,
    ha: i.ha.toFixed(2),
    m_fiscal: i.m_fiscal ?? "",
    frente_motor: i.frente ?? "",
    categoria: i.categoria,
    area_da_frente_ha: frente.area(i).toFixed(2),
    carbono_ha: i.carbono_ha.toFixed(2),
    carbono_tco2_ano: Math.round(i.carbono_tco2_ano),
    titulo: tituloDe(i),
    f_matricula: i.f_matricula.toFixed(3),
    desm_pos2016_ha: (i.desm_pos2016_ha ?? 0).toFixed(2),
    alerta_pos2020_ha: i.alerta_pos2020_ha.toFixed(2),
    status_imovel: i.status_imovel ?? "",
    modo_restauracao: i.linha.modo_restauracao ?? "",
    custo_restauracao_ha_p50: i.linha.custo_restauracao_ha_p50 ?? "",
    credito_liquido_tco2_ha_ano: i.linha.credito_liquido_tco2_ha_ano ?? "",
    vpl_rs_ha_p50: i.linha.vpl_rs_ha_p50 ?? "",
    tir_alavancada_pct_p50: i.linha.tir_alavancada_pct_p50 ?? "",
    valor_desenvolvedor_rs: i.linha.valor_desenvolvedor_rs ?? "",
    grupo_id: i.linha.grupo_id ?? "",
  }))
  const blob = new Blob([escreverCsv(colunas, linhas)], { type: "text/csv;charset=utf-8" })
  const a = document.createElement("a")
  a.href = URL.createObjectURL(blob)
  a.download = nome
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

function etapas(funil: FunilMunicipio, imoveis: Imovel[] | null | undefined, filtros: F, escolher: (f: F) => void): Etapa[] {
  const total = funil.imoveis || 1
  const agrupar = imoveis
    ? { n: imoveis.filter((i) => i.apta && (i.assentamento || i.pequena)).length, sub: "aptas pequenas ou em assentamento" }
    : { n: funil.para_agrupar, sub: "lotes de assentamento para projeto agrupado" }
  const comDado = !!imoveis
  return [
    { id: "imoveis", rotulo: "Imóveis no CAR", numero: funil.imoveis, sub: "todo o município", fracao: 1, ativo: false },
    {
      id: "sem_problema",
      rotulo: "Sem problema",
      numero: funil.sem_problema,
      sub: "sem embargo, TI ou desmate recente",
      fracao: funil.sem_problema / total,
      ativo: false,
    },
    {
      id: "aptas",
      rotulo: "Aptas ao carbono",
      numero: funil.aptas_carbono,
      sub: `${fmtInt(funil.ha_carbono)} ha para restaurar`,
      fracao: funil.aptas_carbono / total,
      ativo: comDado && igual(filtros, PRESETS.aptas),
      aoEscolher: comDado ? () => escolher(PRESETS.aptas) : undefined,
    },
    {
      id: "matricula",
      rotulo: "Com matrícula",
      numero: funil.aptas_com_matricula,
      sub: `${fmtInt(funil.ha_carbono_matricula)} ha prontos para contrato`,
      fracao: funil.aptas_com_matricula / total,
      ativo: !comDado || igual(filtros, PRESETS.matricula),
      aoEscolher: comDado ? () => escolher(PRESETS.matricula) : undefined,
      dica: "Pelo menos metade do CAR com parcela SIGEF com matrícula. A matrícula ainda se confere no cartório.",
    },
    {
      id: "agrupar",
      rotulo: "Para agrupar",
      numero: agrupar.n,
      sub: agrupar.sub,
      fracao: agrupar.n / total,
      ativo: comDado && igual(filtros, PRESETS.agrupar),
      aoEscolher: comDado ? () => escolher(PRESETS.agrupar) : undefined,
    },
  ]
}

interface Props {
  municipio: string
  /** abertura em curso: o mapa começa longe e os números contam quando ela termina */
  abertura?: { mapa: Ref<MapaApi>; revelado: boolean; aoMapaPronto: () => void }
}

export function Principal({ municipio, abertura }: Props) {
  const funil = useCarga(() => fonte.municipio(municipio), [municipio])
  const imoveis = useCarga(() => fonte.imoveis(municipio), [municipio])
  const outro = useCarga(async () => {
    const cods = (await fonte.municipiosComImoveis()).filter((c) => c !== municipio)
    const m = cods.length ? await fonte.municipio(cods[0]) : null
    return m ? { nome: m.municipio, link: linkMunicipio(m.cod_ibge) } : null
  }, [municipio])

  const [filtros, setFiltros] = useState<F>(FILTROS_INICIAIS)
  const [camadas, setCamadas] = useState<Camadas>({ fogo: false, secundaria: false, alertas: true, areas: true, rios: true })
  const [destaque, setDestaque] = useState<string | null>(null)
  const [projeto, setProjeto] = useState(false)
  const [ordem, setOrdem] = useState<OrdemRestauracao>("area")
  const [modo, setModo] = useState<Modo | null>(null)

  const dados = imoveis.dado ?? null
  const frente = frenteDe(filtros.frente)
  const lista = useMemo(
    () => (dados ? ordenarFiltrar(aplicar(dados, filtros), ordem, modo) : null),
    [dados, filtros, ordem, modo],
  )
  const passa = useMemo(() => (lista ? new Set(lista.map((i) => i.cod_imovel)) : null), [lista])
  const pequenas = useMemo(() => dados?.filter((i) => i.apta && (i.pequena || i.assentamento)).length ?? 0, [dados])
  const f = funil.dado
  const nomeArquivo = `raiz_${f?.municipio.normalize("NFD").replace(/[^\w]+/g, "_").toLowerCase() ?? municipio}_${frente.id}.csv`
  const baixar = useCallback(() => lista && baixarCsv(nomeArquivo, lista, filtros), [lista, nomeArquivo, filtros])
  const revelado = abertura ? abertura.revelado : true

  return (
    <>
      <Cabecalho atual="mapa" linkMapa={linkMunicipio(municipio)} />
      <main className="pagina">
        <div className="cabeca">
          <div>
            <ol className="migalhas" aria-label="Onde você está">
              <li>Brasil</li>
              {f && <li>{UFS[f.uf] ?? f.uf}</li>}
              <li aria-current="page">{f?.municipio ?? "…"}</li>
            </ol>
            <h1>Onde dá para restaurar, com dono e título</h1>
            <p>
              {f ? fmtInt(f.imoveis) : "…"} imóveis do CAR cruzados com PRODES, MapBiomas, Ibama, SIGEF, terras
              indígenas, UCs e alertas de desmatamento.
            </p>
          </div>
          <div className="acoes">
            <button type="button" className="botao" onClick={baixar} disabled={!lista?.length}>
              <IconeBaixar /> Baixar planilha
            </button>
            <button type="button" className="botao principal" onClick={() => setProjeto(true)} disabled={!lista?.length}>
              Montar projeto com a seleção
            </button>
          </div>
        </div>

        {f ? (
          <Funil etapas={etapas(f, dados, filtros, setFiltros)} modo={!abertura ? "final" : revelado ? "contar" : "zero"} />
        ) : (
          <p className="aviso-filtro">{funil.carregando ? "Carregando o funil…" : "Este município não está na amostra."}</p>
        )}

        <div className="corpo">
          <Filtros filtros={filtros} mudar={setFiltros} camadas={camadas} mudarCamadas={setCamadas} imoveis={dados} />
          <MapaMunicipio
            ref={abertura?.mapa}
            cod={municipio}
            imoveis={dados}
            passa={passa}
            camadas={camadas}
            frente={frente}
            destaque={destaque}
            comecaLonge={!!abertura}
            aoPronto={abertura?.aoMapaPronto}
          />
          <ListaFazendas
            titulo={filtros.frente === "agrupar" ? "Pequenas e assentamentos" : "Fazendas aptas"}
            frente={frente}
            lista={imoveis.carregando && !dados ? [] : lista}
            funil={f}
            pequenas={pequenas}
            selecionado={destaque}
            aoPassar={setDestaque}
            verPequenas={() => setFiltros(PRESETS.agrupar)}
            outroMunicipio={outro.dado}
            ordem={ordem}
            mudarOrdem={setOrdem}
            modo={modo}
            mudarModo={setModo}
          />
        </div>

        <p className="rodape">
          Números do motor da Raíz ({fonte.nome === "amostra" ? "amostra em dados/amostra" : "API"}). Polígonos do
          CAR/SICAR; terras indígenas, UCs e rios do INPE TerraBrasilis; mapa base © OpenStreetMap (Protomaps). Carbono
          bruto, antes de descontar linha de base e vazamento. Nenhum nome, CPF ou CNPJ é usado nesta tela.
        </p>
      </main>
      {projeto && lista && f && (
        <Projeto lista={lista} frente={frente} municipio={f.municipio} fechar={() => setProjeto(false)} baixar={baixar} />
      )}
    </>
  )
}
