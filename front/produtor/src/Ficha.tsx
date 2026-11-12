import { Check, CircleAlert, TriangleAlert, WifiOff, X } from "lucide-preact"
import { useEffect, useRef, useState } from "preact/hooks"
import { BASE_HA, caixaDeFatos, PRAZO_ANOS } from "../../compartilhado/cenario"
import { boisPorAno, camposDeFutebol } from "../../compartilhado/comparacoes"
import { escolherFonte, type Ficha as DadosFicha } from "../../compartilhado/dados"
import { abreviarCar, fmtCompacto, fmtDestaque, fmtInt, fmtPct, UFS } from "../../compartilhado/formato"
import { COR, MAPA } from "../../compartilhado/cores"
import { svgMiniBrasil } from "../../compartilhado/mini-brasil"
import { motivos } from "../../compartilhado/motivos"
import { situacaoTitulo } from "../../compartilhado/titulo"

const fonte = escolherFonte(import.meta.env)
const CONTATO: string | undefined = import.meta.env.VITE_RAIZ_CONTATO

const maiuscula = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
const numero = (n: number) => (n >= 10_000 ? fmtCompacto(n) : fmtInt(n))

function IconeRaiz() {
  return (
    <svg width="24" height="24" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M16 29V12" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" />
      <path d="M16 15c0-5 3-8.5 9-9 0 5.5-3.5 9-9 9Z" fill="currentColor" />
      <path d="M16 19c0-4.5-3-7.5-8.5-8 0 5 3.3 8 8.5 8Z" fill="currentColor" opacity=".72" />
    </svg>
  )
}

/** Desenho do contorno da fazenda a partir do perímetro em polyline: aparece na hora, sem baixar mapa nenhum. */
function Contorno({ aneis }: { aneis: [number, number][][] }) {
  const L = 340
  const A = 210
  const pts = aneis.flat()
  const lat0 = pts.reduce((s, p) => s + p[1], 0) / pts.length
  const k = Math.cos((lat0 * Math.PI) / 180)
  const xs = pts.map((p) => p[0] * k)
  const ys = pts.map((p) => -p[1])
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  // o botão "toque para ver no mapa" ocupa os 70 px de baixo
  const esc = Math.min((L - 60) / (x1 - x0 || 1), (A - 100) / (y1 - y0 || 1))
  const ox = (L - (x1 - x0) * esc) / 2
  const oy = 16 + (A - 86 - 16 - (y1 - y0) * esc) / 2
  const d = aneis
    .map(
      (a) =>
        "M" +
        a.map(([lon, lat]) => `${(ox + (lon * k - x0) * esc).toFixed(1)},${(oy + (-lat - y0) * esc).toFixed(1)}`).join("L") +
        "Z",
    )
    .join("")
  return (
    <svg viewBox={`0 0 ${L} ${A}`} role="img" aria-label="Contorno da fazenda no CAR">
      <rect width={L} height={A} fill={MAPA.terra} />
      <path d={d} fill={COR.mata} fill-opacity=".22" stroke={COR.tinta} stroke-width="2.5" stroke-linejoin="round" />
    </svg>
  )
}

function MapaSobDemanda({ ficha }: { ficha: DadosFicha }) {
  const [estado, setEstado] = useState<"previa" | "carregando" | "aberto" | "erro">("previa")
  const caixa = useRef<HTMLDivElement>(null)
  const abrir = async () => {
    setEstado("carregando")
    try {
      // MapLibre e PMTiles só chegam aqui, no toque
      const [{ montarMapa }, base] = await Promise.all([
        import("./mapa"),
        fonte.geo.brasil().then(async (b) => b.base ?? (await fonte.geo.base(ficha.imovel.cod_ibge))),
      ])
      setEstado("aberto")
      requestAnimationFrame(() => caixa.current && montarMapa(caixa.current, ficha.aneis, base))
    } catch {
      setEstado("erro")
    }
  }
  if (!ficha.aneis.length) return <p class="miudo">O contorno desta fazenda ainda não foi baixado do CAR.</p>
  if (estado === "aberto") return <div class="mapa-vivo" ref={caixa} />
  return (
    <>
      <button type="button" class="mapa-previa" onClick={abrir} disabled={estado === "carregando"}>
        <Contorno aneis={ficha.aneis} />
        <span>{estado === "carregando" ? "Abrindo o mapa…" : "Toque para ver no mapa"}</span>
      </button>
      <p class="miudo">{estado === "erro" ? "Não deu para abrir o mapa agora. Tente de novo com sinal melhor." : "O mapa usa mais internet; o desenho acima não gasta nada."}</p>
    </>
  )
}

/** Onde fica, numa linha: o mini mapa do Brasil (64 px) com o ponto no município e a frase (guia, item 2.1, parte 8). */
function OndeFica({ ficha }: { ficha: DadosFicha }) {
  const i = ficha.imovel
  const c = ficha.caixa
  const svg = svgMiniBrasil({
    uf: i.uf,
    lon: c ? (c[0] + c[2]) / 2 : null,
    lat: c ? (c[1] + c[3]) / 2 : null,
    titulo: `Mapa do Brasil com o ponto em ${i.municipio}`,
  })
  const estado = UFS[i.uf] ?? i.uf
  return (
    <p class="onde-fica">
      <span class="mini-brasil" dangerouslySetInnerHTML={{ __html: svg }} />
      <span>
        Fica em {i.municipio}, {estado === "Pará" ? "no Pará" : `em ${estado}`}.
      </span>
    </p>
  )
}

function SemCodigo() {
  const [cod, setCod] = useState("")
  return (
    <main>
      <h1>Ficha da sua fazenda</h1>
      <p class="lead">Abra o link que a Raíz mandou para você, ou digite o código do CAR da fazenda.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (cod.trim()) location.search = "?car=" + encodeURIComponent(cod.trim().toUpperCase())
        }}
      >
        <label class="miudo" for="cod">
          Código do CAR (começa com a sigla do estado, por exemplo PA-)
        </label>
        <input id="cod" class="campo" value={cod} onInput={(e) => setCod((e.target as HTMLInputElement).value)} autoComplete="off" />
        <button class="botao" type="submit">
          Ver a ficha
        </button>
      </form>
    </main>
  )
}

export function Ficha() {
  const car = new URLSearchParams(location.search).get("car")
  const [ficha, setFicha] = useState<DadosFicha | null | undefined>(undefined)
  const [falhou, setFalhou] = useState(false)
  useEffect(() => {
    if (car)
      fonte.ficha(car).then(setFicha, () => {
        setFalhou(true)
        setFicha(null)
      })
  }, [car])

  const topo = (
    <header class="topo">
      <IconeRaiz /> Raíz <small>Ficha da sua fazenda</small>
    </header>
  )
  if (!car)
    return (
      <>
        {topo}
        <SemCodigo />
      </>
    )
  if (ficha === undefined)
    return (
      <>
        {topo}
        <main>
          <p class="estado">
            <span class="girando" aria-hidden="true" /> Carregando a ficha da sua fazenda.
          </p>
        </main>
      </>
    )
  if (ficha === null && falhou)
    return (
      <>
        {topo}
        <main>
          <h1>{navigator.onLine === false ? "Sem internet agora" : "Não deu para abrir a ficha"}</h1>
          <p class="aviso">
            {navigator.onLine === false ? <WifiOff size={24} aria-hidden="true" /> : <CircleAlert size={24} aria-hidden="true" />}
            <span>
              {navigator.onLine === false
                ? "Quando o sinal voltar, abra o link de novo. A ficha fica guardada no celular depois da primeira vez."
                : "Tente de novo daqui a pouco. Se continuar, fale com a Raíz."}
            </span>
          </p>
        </main>
      </>
    )
  if (ficha === null)
    return (
      <>
        {topo}
        <main>
          <h1>Não achamos esta fazenda</h1>
          <p class="lead">Confira o código do CAR no link. Se estiver certo, a fazenda ainda não passou pela Raíz.</p>
        </main>
      </>
    )

  const i = ficha.imovel
  const ctx = ficha.contexto
  const titulo = situacaoTitulo(i)
  const lista = motivos(i)
  const faltas = lista.filter((m) => !m.ok)
  const fatos = caixaDeFatos(i)
  const topoPct = 1 - ctx.posicao_carbono
  const textoTitulo: Record<string, string> = {
    matricula_a_conferir:
      i.f_matricula >= 0.5
        ? `O cadastro do INCRA (SIGEF) mostra matrícula em ${fmtPct(Math.min(1, i.f_matricula))} da área. Falta conferir no cartório; quem paga a certidão é o comprador, não você.`
        : `O cadastro do INCRA (SIGEF) mostra matrícula em só ${fmtPct(i.f_matricula)} da área; o resto pode ser posse. Vale conferir no cartório e regularizar o resto.`,
    matricula_conferida: "A matrícula da sua área já foi conferida no cartório.",
    assentamento: "Sua terra fica em assentamento do INCRA. Ela entra junto com as vizinhas, num projeto em grupo.",
    sem_matricula: "Não achamos matrícula da sua área no SIGEF. Antes de qualquer contrato, é preciso regularizar o título.",
  }

  return (
    <>
      {topo}
      <main>
        <p class="onde">
          {i.municipio}, {UFS[i.uf] ?? i.uf}. Cadastro Ambiental Rural (CAR) {abreviarCar(i.cod_imovel)}
        </p>
        {i.apta ? (
          <>
            <h1>
              <em>{Math.round(i.carbono_ha) === 1 ? "1 hectare" : `${fmtInt(i.carbono_ha)} hectares`}</em> da sua terra{" "}
              {Math.round(i.carbono_ha) === 1 ? "pode" : "podem"} virar mata de novo
            </h1>
            <p class="lead">
              {maiuscula(camposDeFutebol(i.carbono_ha))}. É pasto perto de floresta, onde a mata volta sozinha se o gado
              sair dali.
            </p>
            {topoPct <= 0.3 && ctx.n_imoveis >= 10 && (
              <p class="local">
                Das {fmtInt(ctx.n_imoveis)} fazendas de {ctx.municipio}, a sua está{" "}
                {topoPct < 0.015 ? "no 1%" : `entre os ${fmtPct(topoPct)}`} com mais área assim.
              </p>
            )}
          </>
        ) : (
          <>
            <h1>Hoje sua fazenda ainda não entra</h1>
            <p class="lead">Veja abaixo o que falta. Resolvido isso, ela pode entrar na próxima revisão.</p>
          </>
        )}

        {i.apta && i.carbono_tco2_ano > 0 && (
          <section class="cartao">
            <h2>Se a mata voltar</h2>
            <p>Por ano, ela tira do ar cerca de</p>
            <p class="grande num">{fmtDestaque(i.carbono_tco2_ano)} toneladas de gás carbônico</p>
            <p>É como sumir com {boisPorAno(i.carbono_tco2_ano)}.</p>
            <p class="miudo">Conta bruta, antes dos descontos que todo projeto de carbono faz.</p>
          </section>
        )}

        {i.apta && i.pequena && (
          <section class="cartao">
            <h2>Fazenda pequena não fica de fora</h2>
            <p>
              Sua fazenda tem até 4 módulos fiscais. Ela entra junto com fazendas vizinhas, num projeto em grupo, e cada
              uma recebe pela sua parte.
            </p>
          </section>
        )}

        <section class="cartao fatos" aria-labelledby="fatos">
          <h2 id="fatos">Caixa de fatos</h2>
          <p class="base">
            A cada {BASE_HA} hectares da sua fazenda, em {PRAZO_ANOS} anos
          </p>
          <table>
            <thead>
              <tr>
                <th>
                  <span style="position:absolute;left:-9999px">O que se mede</span>
                </th>
                <th>Não fazer nada</th>
                <th class="voltar">Deixar a mata voltar</th>
              </tr>
            </thead>
            <tbody>
              {fatos.linhas.map((l) => (
                <tr key={l.id}>
                  <th>{l.rotulo}</th>
                  <td class="num">
                    {numero(l.nada)}
                    <small>{l.unidade}</small>
                  </td>
                  <td class="num voltar">
                    {numero(l.restaurar)}
                    <small>{l.unidade}</small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p class="notas">"Não fazer nada" é a fazenda como está hoje, sem desmatar mais.</p>
        </section>

        <section class="cartao">
          <h2>Sua terra no papel</h2>
          <p>
            <span class={"selo " + titulo.tom}>{titulo.rotulo}</span>
          </p>
          <p>{textoTitulo[titulo.selo]}</p>
        </section>

        <section class="cartao">
          <h2>{faltas.length ? "O que precisa ficar em dia" : "Tudo em dia"}</h2>
          <ul class="lista">
            {lista.map((m) => (
              <li key={m.id} class={m.ok ? "ok" : m.bloqueia ? "ruim" : "atencao"}>
                {m.ok ? (
                  <Check size={24} class="icone" aria-hidden="true" />
                ) : m.bloqueia ? (
                  <X size={24} class="icone" aria-hidden="true" />
                ) : (
                  <TriangleAlert size={24} class="icone" aria-hidden="true" />
                )}
                <span>
                  {m.texto}
                  <br />
                  <span class="miudo">{m.detalhe}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section class="cartao">
          <h2>Onde fica</h2>
          <OndeFica ficha={ficha} />
          <MapaSobDemanda ficha={ficha} />
        </section>

        {CONTATO && (
          <a class="botao" href={CONTATO}>
            Quero conversar com a Raíz
          </a>
        )}

        <footer>
          <p>
            A Raíz usa só dados públicos: CAR, INPE, MapBiomas, Ibama e INCRA. Os números vêm de imagens de satélite e
            podem ter erro; a visita na fazenda confirma. Nesta página não aparece nome nem CPF de ninguém.
          </p>
        </footer>
      </main>
    </>
  )
}
