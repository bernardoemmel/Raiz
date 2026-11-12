import { X } from "lucide-react"
import { useMemo, useState } from "react"
import { fmtInt, UFS } from "../../../compartilhado/formato"
import { CAMPOS_PADRAO, marcosDo } from "../../../compartilhado/pedidos/exemplo"
import {
  ROTULO_CAMINHO,
  ROTULO_CRONOGRAMA,
  ROTULO_EXCLUSAO,
  ROTULO_INTERESSE_FILTRO,
  ROTULO_META,
  ROTULO_METODO,
} from "../../../compartilhado/pedidos/texto"
import type { CaminhoTerra, CamposPedido, Cronograma, Exclusao, FiltroInteresse, Metodo, TipoMeta } from "../../../compartilhado/pedidos/tipos"
import { fonte, useCarga } from "../dados"
import { MapaDesenho } from "../mapa/MapaDesenho"
import { pedidos } from "../pedidos"
import { Cabecalho } from "../partes/Cabecalho"
import { AvisoExemplo } from "../partes/pedido/AvisoExemplo"
import { linkPedido, linkPedidos } from "../rota"

const BIOMAS = ["Amazônia", "Cerrado", "Mata Atlântica", "Caatinga", "Pantanal", "Pampa"]

const DICA_INTERESSE: Record<FiltroInteresse, string> = {
  qualquer: "O lote sai da base inteira; a Raíz busca o aceite dos donos depois.",
  interessados: "Só fazendas cujo dono já disse que tem interesse. A base fica menor.",
  com_aceite: "Só fazendas com aceite registrado do dono (fase 1). A base fica bem menor.",
}

/** número escrito do jeito brasileiro ("1.000.000") de volta para número */
const lerNumero = (s: string): number | null => {
  const t = s.replace(/\./g, "").replace(",", ".").trim()
  if (!t) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : null
}

/**
 * Novo pedido (cena-alvo): formulário curto com os campos da cena e os valores padrão preenchidos (1 milhão de créditos,
 * cronograma ProFloresta+, Amazônia). O essencial fica à vista; dinheiro, métodos, terra, forma do lote e exclusões
 * ficam em "Mais filtros", já preenchidos.
 */
export function NovoPedido() {
  const [c, setC] = useState<CamposPedido>(() => structuredClone(CAMPOS_PADRAO))
  const [metaTexto, setMetaTexto] = useState(fmtInt(CAMPOS_PADRAO.meta.valor))
  const [desenhar, setDesenhar] = useState(false)
  const [raio, setRaio] = useState(false)
  const [mun, setMun] = useState("")
  const [enviando, setEnviando] = useState(false)
  const [erro, setErro] = useState<string | null>(null)
  const brasil = useCarga(() => fonte.geo.brasil(), [])
  const municipios = useCarga(() => fonte.municipios(), [])
  const opcoesMun = useMemo(() => new Map((municipios.dado ?? []).map((m) => [`${m.municipio} (${m.uf})`, m])), [municipios.dado])

  const mudar = (f: (x: CamposPedido) => void) =>
    setC((atual) => {
      const novo = structuredClone(atual)
      f(novo)
      return novo
    })
  const alternar = <T,>(lista: T[], v: T) => (lista.includes(v) ? lista.filter((x) => x !== v) : [...lista, v])

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    const meta = lerNumero(metaTexto)
    if (!meta || meta <= 0) return setErro("Diga a meta: um número maior que zero.")
    if (!c.metodos.length) return setErro("Escolha pelo menos um método de restauração.")
    if (!c.terra.length) return setErro("Escolha pelo menos um caminho da terra.")
    if (desenhar && (c.onde.poligono?.length ?? 0) < 4) return setErro("Marque pelo menos 3 cantos da área no mapa, ou desligue o desenho.")
    if (raio && !(c.onde.raio && c.onde.raio.km > 0)) return setErro("Para o raio, diga latitude, longitude e quantos quilômetros.")
    const campos: CamposPedido = {
      ...c,
      meta: { ...c.meta, valor: meta },
      marcos_proprios: c.cronograma === "proprio" ? (c.marcos_proprios ?? marcosDo({ ...c, cronograma: "profloresta" })) : undefined,
      onde: { ...c.onde, poligono: desenhar ? c.onde.poligono : null, raio: raio ? c.onde.raio : null },
    }
    setErro(null)
    setEnviando(true)
    try {
      const p = await pedidos.criar(campos)
      location.hash = linkPedido(p.id)
    } catch (err) {
      setErro((err as Error).message)
      setEnviando(false)
    }
  }

  const cantos = c.onde.poligono ? Math.max(0, c.onde.poligono.length - 1) : 0
  return (
    <div className="tela-pedidos">
      <Cabecalho atual="pedidos" />
      <main className="pagina pagina-media">
        <ol className="migalhas" aria-label="Onde você está">
          <li>
            <a href={linkPedidos}>Meus pedidos</a>
          </li>
          <li aria-current="page">Novo pedido</li>
        </ol>
        <h1>Novo pedido</h1>
        <p className="frase">Diga o que precisa. A Raíz mostra na hora quanto existe na base e monta o melhor lote em três opções.</p>
        <AvisoExemplo ativo={pedidos.exemplo} />

        <form className="formulario pedido-form" onSubmit={enviar} noValidate>
          <section aria-labelledby="np-quanto">
            <h2 id="np-quanto">Quanto e quando</h2>
            <div className="campos-linha">
              <label className="campo">
                <span>Meta</span>
                <select value={c.meta.tipo} onChange={(e) => mudar((x) => (x.meta.tipo = e.target.value as TipoMeta))}>
                  {(Object.keys(ROTULO_META) as TipoMeta[]).map((t) => (
                    <option key={t} value={t}>
                      {ROTULO_META[t].nome}
                    </option>
                  ))}
                </select>
              </label>
              <label className="campo">
                <span>Quantidade ({ROTULO_META[c.meta.tipo].unidade})</span>
                <input
                  inputMode="numeric"
                  value={metaTexto}
                  onChange={(e) => setMetaTexto(e.target.value)}
                  onBlur={() => {
                    const n = lerNumero(metaTexto)
                    if (n) setMetaTexto(fmtInt(n))
                  }}
                />
              </label>
            </div>
            <fieldset className="campo-grupo">
              <legend>Cronograma</legend>
              {(Object.keys(ROTULO_CRONOGRAMA) as Cronograma[]).map((k) => (
                <label key={k} className="opcao">
                  <input type="radio" name="cronograma" checked={c.cronograma === k} onChange={() => mudar((x) => (x.cronograma = k))} />
                  <span>{ROTULO_CRONOGRAMA[k]}</span>
                </label>
              ))}
            </fieldset>
            {c.cronograma === "proprio" && (
              <table className="marcos-proprios">
                <caption>Quanto da meta até cada ano</caption>
                <thead>
                  <tr>
                    <th scope="col">Ano</th>
                    <th scope="col">% da meta</th>
                  </tr>
                </thead>
                <tbody>
                  {(c.marcos_proprios ?? marcosDo({ ...c, cronograma: "profloresta" })).map((m, k) => (
                    <tr key={k}>
                      <td>
                        <input
                          aria-label={`Ano do marco ${k + 1}`}
                          inputMode="numeric"
                          value={m.ano}
                          onChange={(e) =>
                            mudar((x) => {
                              const l = x.marcos_proprios ?? marcosDo({ ...x, cronograma: "profloresta" })
                              l[k] = { ...l[k], ano: Number(e.target.value) || 0 }
                              x.marcos_proprios = l
                            })
                          }
                        />
                      </td>
                      <td>
                        <input
                          aria-label={`Porcentagem da meta no marco ${k + 1}`}
                          inputMode="numeric"
                          value={Math.round(m.fracao * 100)}
                          onChange={(e) =>
                            mudar((x) => {
                              const l = x.marcos_proprios ?? marcosDo({ ...x, cronograma: "profloresta" })
                              l[k] = { ...l[k], fracao: Math.min(1, (Number(e.target.value) || 0) / 100) }
                              x.marcos_proprios = l
                            })
                          }
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section aria-labelledby="np-onde">
            <h2 id="np-onde">Onde</h2>
            <fieldset className="campo-grupo">
              <legend>Bioma</legend>
              <div className="opcoes-linha">
                {BIOMAS.map((b) => (
                  <label key={b} className="opcao">
                    <input type="checkbox" checked={c.onde.biomas.includes(b)} onChange={() => mudar((x) => (x.onde.biomas = alternar(x.onde.biomas, b)))} />
                    <span>{b}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="campos-linha">
              <label className="campo">
                <span>Estados (sem nenhum: todos)</span>
                <select
                  value=""
                  onChange={(e) => e.target.value && mudar((x) => (x.onde.ufs = [...new Set([...x.onde.ufs, e.target.value])]))}
                >
                  <option value="">Escolher um estado</option>
                  {Object.entries(UFS)
                    .sort((a, b) => a[1].localeCompare(b[1], "pt-BR"))
                    .map(([uf, nome]) => (
                      <option key={uf} value={uf} disabled={c.onde.ufs.includes(uf)}>
                        {nome}
                      </option>
                    ))}
                </select>
              </label>
              <label className="campo">
                <span>Municípios</span>
                <input
                  list="np-municipios"
                  value={mun}
                  placeholder="Nome do município"
                  onChange={(e) => {
                    const m = opcoesMun.get(e.target.value)
                    if (m) {
                      mudar((x) => (x.onde.municipios = [...new Set([...x.onde.municipios, m.cod_ibge])]))
                      setMun("")
                    } else setMun(e.target.value)
                  }}
                />
                <datalist id="np-municipios">
                  {[...opcoesMun.keys()].map((k) => (
                    <option key={k} value={k} />
                  ))}
                </datalist>
              </label>
            </div>
            {(c.onde.ufs.length > 0 || c.onde.municipios.length > 0) && (
              <ul className="fichas-escolhidas" aria-label="Lugares escolhidos">
                {c.onde.ufs.map((uf) => (
                  <li key={uf}>
                    {UFS[uf]}
                    <button type="button" aria-label={`Tirar ${UFS[uf]}`} onClick={() => mudar((x) => (x.onde.ufs = x.onde.ufs.filter((u) => u !== uf)))}>
                      <X size={16} aria-hidden="true" />
                    </button>
                  </li>
                ))}
                {c.onde.municipios.map((cod) => {
                  const m = [...opcoesMun.values()].find((x) => x.cod_ibge === cod)
                  return (
                    <li key={cod}>
                      {m ? `${m.municipio} (${m.uf})` : cod}
                      <button type="button" aria-label="Tirar o município" onClick={() => mudar((x) => (x.onde.municipios = x.onde.municipios.filter((u) => u !== cod)))}>
                        <X size={16} aria-hidden="true" />
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
            <label className="opcao">
              <input type="checkbox" checked={raio} onChange={() => setRaio(!raio)} />
              <span>Num raio de uma planta ou fábrica</span>
            </label>
            {raio && (
              <div className="campos-linha">
                {(["lat", "lon", "km"] as const).map((k) => (
                  <label key={k} className="campo">
                    <span>{k === "lat" ? "Latitude" : k === "lon" ? "Longitude" : "Raio (km)"}</span>
                    <input
                      inputMode="decimal"
                      value={c.onde.raio?.[k] ?? ""}
                      onChange={(e) =>
                        mudar((x) => {
                          x.onde.raio = { lat: x.onde.raio?.lat ?? 0, lon: x.onde.raio?.lon ?? 0, km: x.onde.raio?.km ?? 50, [k]: lerNumero(e.target.value) ?? 0 }
                        })
                      }
                    />
                  </label>
                ))}
              </div>
            )}
            <label className="opcao">
              <input type="checkbox" checked={desenhar} onChange={() => setDesenhar(!desenhar)} />
              <span>Desenhar a área no mapa</span>
            </label>
            {desenhar && (
              <div className="desenho">
                <p className="legenda-frase">Toque no mapa para marcar os cantos da área. A partir de 3 cantos, a área se fecha sozinha.</p>
                {brasil.dado && (
                  <MapaDesenho
                    base={brasil.dado.base}
                    pontos={(c.onde.poligono ?? []).slice(0, -1)}
                    mudar={(p) => mudar((x) => (x.onde.poligono = p.length ? [...p, p[0]] : null))}
                  />
                )}
                <div className="acoes">
                  <span className="legenda-frase">{cantos === 1 ? "1 canto" : `${cantos} cantos`}</span>
                  <button type="button" className="botao" disabled={!cantos} onClick={() => mudar((x) => {
                    const p = (x.onde.poligono ?? []).slice(0, -2)
                    x.onde.poligono = p.length ? [...p, p[0]] : null
                  })}>
                    Desfazer o último canto
                  </button>
                  <button type="button" className="botao" disabled={!cantos} onClick={() => mudar((x) => (x.onde.poligono = null))}>
                    Apagar o desenho
                  </button>
                </div>
              </div>
            )}
            <label className="opcao">
              <input type="checkbox" checked={c.onde.so_fornecedores_cadeia} onChange={() => mudar((x) => (x.onde.so_fornecedores_cadeia = !x.onde.so_fornecedores_cadeia))} />
              <span>Só fornecedores da minha cadeia (meta FLAG; precisa da lista da sua cadeia)</span>
            </label>
          </section>

          <section aria-labelledby="np-interesse">
            <h2 id="np-interesse">Interesse do dono</h2>
            <fieldset className="campo-grupo">
              <legend className="sr">Interesse do dono</legend>
              {(Object.keys(ROTULO_INTERESSE_FILTRO) as FiltroInteresse[]).map((k) => (
                <label key={k} className="opcao opcao-dica">
                  <input type="radio" name="interesse" checked={c.interesse === k} onChange={() => mudar((x) => (x.interesse = k))} />
                  <span>
                    <strong>{ROTULO_INTERESSE_FILTRO[k]}</strong>
                    <small>{DICA_INTERESSE[k]}</small>
                  </span>
                </label>
              ))}
            </fieldset>
          </section>

          <details className="mais-filtros">
            <summary>Mais filtros: dinheiro, métodos, terra, forma do lote e exclusões (já preenchidos)</summary>
            <section aria-labelledby="np-dinheiro">
              <h3 id="np-dinheiro">Dinheiro</h3>
              <div className="campos-linha">
                <CampoNumero rotulo="Custo máximo (US$ por crédito)" vazio="sem limite" valor={c.dinheiro.custo_max_usd_credito} mudar={(v) => mudar((x) => (x.dinheiro.custo_max_usd_credito = v))} />
                <CampoNumero rotulo="TIR mínima (% ao ano)" vazio="sem mínimo" valor={c.dinheiro.tir_min === null ? null : c.dinheiro.tir_min * 100} mudar={(v) => mudar((x) => (x.dinheiro.tir_min = v === null ? null : v / 100))} />
                <CampoNumero rotulo="Preço de venda (US$ por crédito)" valor={c.dinheiro.preco_venda_usd} mudar={(v) => mudar((x) => (x.dinheiro.preco_venda_usd = v ?? 0))} />
                <CampoNumero rotulo="Parte financiada (%)" valor={c.dinheiro.fracao_financiada * 100} mudar={(v) => mudar((x) => (x.dinheiro.fracao_financiada = (v ?? 0) / 100))} />
              </div>
            </section>
            <fieldset className="campo-grupo">
              <legend>Métodos aceitos</legend>
              <div className="opcoes-linha">
                {(Object.keys(ROTULO_METODO) as Metodo[]).map((k) => (
                  <label key={k} className="opcao">
                    <input type="checkbox" checked={c.metodos.includes(k)} onChange={() => mudar((x) => (x.metodos = alternar(x.metodos, k)))} />
                    <span>{ROTULO_METODO[k]}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset className="campo-grupo">
              <legend>Terra aceita (caminho da terra)</legend>
              <div className="opcoes-linha">
                {(Object.keys(ROTULO_CAMINHO) as CaminhoTerra[]).map((k) => (
                  <label key={k} className="opcao">
                    <input type="checkbox" checked={c.terra.includes(k)} onChange={() => mudar((x) => (x.terra = alternar(x.terra, k)))} />
                    <span>{ROTULO_CAMINHO[k]}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <section aria-labelledby="np-forma">
              <h3 id="np-forma">Forma do lote</h3>
              <div className="campos-linha">
                <CampoNumero rotulo="Distância máxima entre fazendas (km)" vazio="sem limite" valor={c.forma.distancia_max_km} mudar={(v) => mudar((x) => (x.forma.distancia_max_km = v))} />
                <CampoNumero rotulo="Máximo de donos" vazio="sem limite" valor={c.forma.max_donos} mudar={(v) => mudar((x) => (x.forma.max_donos = v))} />
                <CampoNumero rotulo="Área mínima contígua (ha)" vazio="sem mínimo" valor={c.forma.area_min_contigua_ha} mudar={(v) => mudar((x) => (x.forma.area_min_contigua_ha = v))} />
              </div>
              <p className="legenda-frase">Fazenda pequena nunca sai por tamanho: entra agrupada com as vizinhas.</p>
            </section>
            <fieldset className="campo-grupo">
              <legend>Excluir</legend>
              <div className="opcoes-linha">
                {(Object.keys(ROTULO_EXCLUSAO) as Exclusao[]).map((k) => (
                  <label key={k} className="opcao">
                    <input type="checkbox" checked={c.exclusoes.includes(k)} onChange={() => mudar((x) => (x.exclusoes = alternar(x.exclusoes, k)))} />
                    <span>{ROTULO_EXCLUSAO[k]}</span>
                  </label>
                ))}
              </div>
            </fieldset>
          </details>

          {erro && (
            <p className="erro-campo" role="alert">
              {erro}
            </p>
          )}
          <div className="acoes">
            <button className="botao principal grande" type="submit" disabled={enviando}>
              {enviando ? "Montando o lote" : "Ver o que existe e montar o lote"}
            </button>
            {enviando && <span className="girando" aria-hidden="true" />}
          </div>
        </form>
      </main>
    </div>
  )
}

function CampoNumero({ rotulo, valor, mudar, vazio }: { rotulo: string; valor: number | null; mudar: (v: number | null) => void; vazio?: string }) {
  const [texto, setTexto] = useState(valor === null ? "" : String(valor).replace(".", ","))
  return (
    <label className="campo">
      <span>{rotulo}</span>
      <input
        inputMode="decimal"
        placeholder={vazio}
        value={texto}
        onChange={(e) => {
          setTexto(e.target.value)
          mudar(lerNumero(e.target.value))
        }}
      />
    </label>
  )
}
