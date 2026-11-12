import { useMemo, useState } from "react"
import { boisPorAno, camposDeFutebol, fraseIndice, frasePosicao, mediana } from "../../../compartilhado/comparacoes"
import type { Imovel } from "../../../compartilhado/dados"
import { colunaConhecida, NOMES_COLUNAS } from "../../../compartilhado/dados/contrato"
import { escreverCsv } from "../../../compartilhado/dados/csv"
import { abreviarCar, fmt1, fmtDestaque, fmtHa, fmtInt, fmtModulos, fmtPct, STATUS_CAR, UFS } from "../../../compartilhado/formato"
import { motivos } from "../../../compartilhado/motivos"
import { situacaoTitulo } from "../../../compartilhado/titulo"
import { fonte, useCarga } from "../dados"
import { MapaImovel } from "../mapa/MapaImovel"
import { Cabecalho } from "../partes/Cabecalho"
import { CaixaDeFatos } from "../partes/CaixaDeFatos"
import { Estado } from "../partes/Estado"
import { Download, IconeSituacao } from "../partes/Icones"
import { Satelite } from "../partes/Satelite"
import { consumirVoo, linkMunicipio } from "../rota"

const URL_PRODUTOR: string =
  import.meta.env.VITE_RAIZ_URL_PRODUTOR ?? (import.meta.env.DEV ? "http://localhost:5174/" : "/produtor/")

interface Numero {
  id: string
  rotulo: string
  valor: string
  unidade: string
  /** no máximo uma comparação por número (guia, item 1.6): a local quando houver, senão a concreta */
  comparacao: string | null
}

function numerosGrandes(i: Imovel, todos: Imovel[] | null, municipio: string, tco2Municipio: number | null): Numero[] {
  const onde = municipio
  const area = i.apta ? i.carbono_ha : 0
  const aptas = (todos ?? []).filter((x) => x.apta).map((x) => x.carbono_ha)
  const pctFloresta = (x: Imovel) => (x.ha > 0 ? x.floresta_rem_ha / x.ha : 0)
  const lista: Numero[] = [
    {
      id: "restaurar",
      rotulo: "Pode voltar a ser mata",
      valor: fmtInt(area),
      unidade: "ha",
      comparacao:
        area > 0
          ? ((todos &&
              (frasePosicao(
                area,
                todos.map((x) => (x.apta ? x.carbono_ha : 0)),
                onde,
              ) ??
                fraseIndice(area, mediana(aptas), `mediana das aptas de ${onde}`))) ||
            camposDeFutebol(area))
          : "Sem área apta agora.",
    },
  ]
  if (i.apta && i.carbono_tco2_ano > 0)
    lista.push({
      id: "carbono",
      rotulo: "Gás carbônico tirado do ar",
      valor: fmtDestaque(i.carbono_tco2_ano),
      unidade: "t por ano",
      comparacao: tco2Municipio
        ? `${i.carbono_tco2_ano / tco2Municipio < 0.01 ? fmt1((100 * i.carbono_tco2_ano) / tco2Municipio) + "%" : fmtPct(i.carbono_tco2_ano / tco2Municipio)} do carbono de todas as aptas de ${onde}`
        : boisPorAno(i.carbono_tco2_ano),
    })
  lista.push({
    id: "floresta",
    rotulo: "Floresta em pé",
    valor: fmtInt(i.floresta_rem_ha),
    unidade: `ha, ${fmtPct(pctFloresta(i))} do imóvel`,
    comparacao: todos
      ? (() => {
          const med = mediana(todos.map(pctFloresta))
          const f = fraseIndice(pctFloresta(i), med, `mediana de ${onde}`)
          return f ? `${f} (${fmtPct(med)} de floresta)` : null
        })()
      : null,
  })
  lista.push({
    id: "tamanho",
    rotulo: "Tamanho do imóvel",
    valor: fmtInt(i.ha),
    unidade: i.m_fiscal !== null ? `ha, ${fmtModulos(i.m_fiscal)} fiscais` : "ha",
    comparacao: (todos && frasePosicao(i.ha, todos.map((x) => x.ha), onde)) || camposDeFutebol(i.ha),
  })
  return lista
}

function baixarLinha(i: Imovel) {
  const colunas = Object.keys(i.linha)
  const blob = new Blob([escreverCsv(colunas, [i.linha])], { type: "text/csv;charset=utf-8" })
  const a = document.createElement("a")
  a.href = URL.createObjectURL(blob)
  a.download = `raiz_${i.cod_imovel}.csv`
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

export function Fazenda({ car }: { car: string }) {
  const ficha = useCarga(() => fonte.ficha(car), [car])
  const [voar] = useState(() => consumirVoo(car))
  const i = ficha.dado?.imovel
  const cod = i?.cod_ibge ?? ""
  const contexto = useCarga(async () => {
    if (!cod) return null
    const [funil, imoveis, municipio, vizinhos, ti, rios, base] = await Promise.all([
      fonte.municipio(cod),
      fonte.imoveis(cod),
      fonte.geo.camada(cod, "municipio"),
      fonte.geo.camada(cod, "imoveis"),
      fonte.geo.camada(cod, "ti"),
      fonte.geo.camada(cod, "rios"),
      // o mapa base único do Brasil; sem ele, o recorte do município
      fonte.geo.brasil().then(async (b) => b.base ?? (await fonte.geo.base(cod))),
    ])
    return { funil, imoveis, municipio, vizinhos, ti, rios, base }
  }, [cod])
  const certidoes = useCarga(() => fonte.certidoes(car), [car])
  const c = contexto.dado

  const numeros = useMemo(
    () => (i ? numerosGrandes(i, c?.imoveis ?? null, i.municipio, c?.funil?.tco2_ano_aptas ?? null) : []),
    [i, c],
  )

  if (ficha.carregando)
    return (
      <>
        <Cabecalho atual="fazenda" />
        <main className="pagina">
          <Estado tipo="carregando" titulo="Carregando a ficha da fazenda" />
        </main>
      </>
    )
  if (!ficha.dado || !i)
    return (
      <>
        <Cabecalho atual="fazenda" />
        <main className="pagina">
          {ficha.erro ? (
            <Estado tipo="erro" titulo="Não deu para abrir a ficha agora.">
              <p>Confira a conexão e recarregue a página.</p>
            </Estado>
          ) : (
            <Estado tipo="vazio" titulo="Imóvel não encontrado.">
              <p>
                O código <code>{car}</code> não está nos dados da Raíz. Confira o código ou procure pelo município na
                busca acima. <a href="#/">Voltar ao mapa</a>
              </p>
            </Estado>
          )}
        </main>
      </>
    )

  const titulo = situacaoTitulo(i)
  const lista = motivos(i)
  const bloqueios = lista.filter((m) => m.bloqueia && !m.ok)
  const novas = Object.keys(i.linha).filter((k) => !colunaConhecida(k))
  const status = i.status_imovel ? STATUS_CAR[i.status_imovel] ?? i.status_imovel : null
  const certs = certidoes.dado ?? []

  return (
    <>
      <Cabecalho atual="fazenda" linkMapa={linkMunicipio(cod)} />
      <main className="pagina ficha">
        <div className="cabeca">
          <div>
            <ol className="migalhas" aria-label="Onde você está">
              <li>Brasil</li>
              <li>{UFS[i.uf] ?? i.uf}</li>
              <li>
                <a href={linkMunicipio(cod)}>{i.municipio}</a>
              </li>
              <li aria-current="page">CAR {abreviarCar(i.cod_imovel)}</li>
            </ol>
            <h1>
              {i.apta ? (
                <>
                  {fmtHa(i.carbono_ha)} para restaurar
                </>
              ) : (
                <>Sem área apta agora</>
              )}
            </h1>
            <p>
              Imóvel de {fmtHa(i.ha)}
              {i.m_fiscal !== null && <> e {fmtModulos(i.m_fiscal)} fiscais</>}
              {i.bioma && <>, no bioma {i.bioma}</>}.
              {status && (
                <>
                  {" "}
                  Cadastro Ambiental Rural (CAR) {status}
                  {i.condicao && <>: {i.condicao.charAt(0).toLowerCase() + i.condicao.slice(1)}</>}.
                </>
              )}
            </p>
            <div className="selos">
              {i.apta ? <span className="selo ok">Apta ao carbono</span> : <span className="selo ruim">Fora do funil</span>}
              <span className={"selo " + titulo.tom}>{titulo.rotulo}</span>
              {i.pequena && <span className="selo neutro">Pequena: entra em projeto agrupado</span>}
              {i.alerta_pos2020_ha <= 1 ? (
                <span className="selo ok">0 alertas desde 2020</span>
              ) : (
                <span className="selo ruim">Alerta em {i.alerta_ultimo_ano ?? "depois de 2020"}</span>
              )}
            </div>
            <p className="codigo-car">
              Código do CAR: <code>{i.cod_imovel}</code>
            </p>
          </div>
          <div className="acoes">
            <a className="botao" href={linkMunicipio(cod)}>
              Voltar ao mapa
            </a>
            <button type="button" className="botao" onClick={() => baixarLinha(i)}>
              <Download size={20} aria-hidden="true" /> Baixar dados
            </button>
            <a className="botao principal" href={`${URL_PRODUTOR}?car=${encodeURIComponent(i.cod_imovel)}`} target="_blank" rel="noopener">
              Ficha do produtor<span className="sr"> (abre em outra aba)</span>
            </a>
          </div>
        </div>

        <div className="ficha-topo">
          {contexto.carregando ? (
            <div className="mapa-caixa mapa-imovel">
              <div className="mapa-carregando">Carregando o mapa de {i.municipio}…</div>
            </div>
          ) : (
            <MapaImovel
              aneis={ficha.dado.aneis}
              cod={i.cod_imovel}
              ha={i.ha}
              uf={i.uf}
              municipioNome={i.municipio}
              municipio={c?.municipio ?? null}
              voar={voar}
              base={c?.base ?? null}
              vizinhos={c?.vizinhos ?? null}
              ti={c?.ti ?? null}
              rios={c?.rios ?? null}
            />
          )}
          <section className="painel grandes" aria-label="Números grandes">
            {numeros.map((n) => (
              <div key={n.id} className="grande">
                <div className="grande-rotulo">{n.rotulo}</div>
                <div className="grande-valor num">
                  {n.valor} <span>{n.unidade}</span>
                </div>
                {n.comparacao && (
                  <div className="grande-comparacao">{n.comparacao.charAt(0).toUpperCase() + n.comparacao.slice(1)}</div>
                )}
              </div>
            ))}
          </section>
        </div>

        <CaixaDeFatos imovel={i} />

        <Satelite imovel={i} />

        <div className="ficha-duas">
          <section className="painel bloco" aria-labelledby="motivos-titulo">
            <h2 id="motivos-titulo">{i.apta ? "Por que é apta" : "Por que não é apta agora"}</h2>
            {!i.apta && bloqueios.length > 0 && (
              <p className="bloco-resumo">
                {bloqueios.length === 1 ? "Um item tira" : `${bloqueios.length} itens tiram`} a fazenda do funil hoje.
                Resolvido isso, ela volta sozinha na próxima rodada do motor.
              </p>
            )}
            <ul className="motivos">
              {lista.map((m) => (
                <li key={m.id} className={m.ok ? "ok" : m.bloqueia ? "ruim" : "atencao"}>
                  <IconeSituacao ok={m.ok} bloqueia={m.bloqueia} />
                  <div>
                    <div className="motivo-texto">{m.texto}</div>
                    <div className="motivo-detalhe num">{m.detalhe}</div>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          <section className="painel bloco" aria-labelledby="titulo-titulo">
            <h2 id="titulo-titulo">Título da terra</h2>
            <p className="titulo-situacao">
              <span className={"selo " + titulo.tom}>{titulo.rotulo}</span>
            </p>
            <p className="bloco-resumo">{titulo.texto}</p>
            <dl className="barras">
              {[
                { r: "Parcelas SIGEF", v: i.ha ? i.sigef_ha / i.ha : 0 },
                { r: "Com matrícula", v: i.f_matricula },
                { r: "Assentamento do INCRA", v: i.ha ? i.assentamento_ha / i.ha : 0 },
              ].map((b) => (
                <div key={b.r}>
                  <dt>{b.r}</dt>
                  <dd>
                    <span className="barra">
                      <i style={{ width: `${Math.min(100, b.v * 100)}%` }} />
                    </span>
                    <span className="num">{fmtPct(Math.min(1, b.v))}</span>
                  </dd>
                </div>
              ))}
            </dl>
            <h3>Para pedir a certidão</h3>
            {certs.length ? (
              <table className="certidoes">
                <thead>
                  <tr>
                    <th>Cartório (CNS)</th>
                    <th>Matrícula</th>
                    <th>Área sobre o CAR</th>
                  </tr>
                </thead>
                <tbody>
                  {certs.map((x) => (
                    <tr key={x.registro_cns + x.registro_matricula}>
                      <td>{x.registro_cns}</td>
                      <td>{x.registro_matricula}</td>
                      <td className="num">{x.ha_sobre_car ? fmtHa(x.ha_sobre_car) : "sem dado"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="bloco-resumo">
                {i.f_matricula > 0
                  ? "O cartório (CNS) e o número da matrícula saem do arquivo certidoes_<município>.csv do motor, que ainda não está na amostra deste município."
                  : "Sem parcela com matrícula: não há certidão a pedir. O caminho é regularizar a posse."}{" "}
                A certidão é registro público; quem pede e paga é o comprador.
              </p>
            )}
          </section>
        </div>

        <details className="painel bloco outros">
          <summary>
            Outros dados do motor ({Object.keys(i.linha).length} colunas
            {novas.length > 0 && `, ${novas.length} ${novas.length === 1 ? "nova" : "novas"}`})
          </summary>
          <table>
            <tbody>
              {Object.entries(i.linha).map(([k, v]) => (
                <tr key={k}>
                  <th scope="row">
                    {NOMES_COLUNAS[k] ?? k}
                    {NOMES_COLUNAS[k] && <code>{k}</code>}
                    {!colunaConhecida(k) && <span className="selo neutro">coluna nova</span>}
                  </th>
                  <td className="num">{v === "" ? "sem dado" : v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>

        <p className="rodape">
          Números do motor da Raíz. Carbono bruto, antes de descontar linha de base e vazamento. Comparações: campo de
          futebol de 105 × 68 m; metano de boi pelo fator do IPCC (56 kg de CH₄ por cabeça por ano, potencial 27).
          Nenhum nome, CPF ou CNPJ é usado nesta ficha.
        </p>
      </main>
    </>
  )
}
