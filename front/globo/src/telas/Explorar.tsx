import type { SituacaoBasica } from "../../../compartilhado/dados/basico"
import { PainelMunicipioBasico } from "../partes/PainelMunicipioBasico"
import { useEffect, useMemo, useRef, useState } from "react"
import { codigosEmLeilao } from "../../../compartilhado/calendario"
import { calendario } from "../calendario"
import { ufDoCodigo } from "../../../compartilhado/formato"
import type { Foco } from "../../../compartilhado/funil-etapas"
import { fonte, useCarga } from "../dados"
import { MapaBrasil, type CamadaAssunto, type GeoMunicipio } from "../mapa/MapaBrasil"
import { Cabecalho } from "../partes/Cabecalho"
import { PainelBrasil } from "../partes/PainelBrasil"
import { PainelMunicipio } from "../partes/PainelMunicipio"
import { linkEstado, linkMunicipio } from "../rota"

type Altura = "baixa" | "meia" | "alta"
const ALTURAS: Altura[] = ["baixa", "meia", "alta"]

/** quanto a gaveta cobre do mapa no celular, para o voo enquadrar o município acima dela */
function cobertura(altura: Altura): number {
  if (!matchMedia("(max-width: 700px)").matches) return 0
  const h = window.innerHeight
  return altura === "baixa" ? 132 : altura === "meia" ? Math.round(h * 0.48) : Math.round(h * 0.86)
}

/**
 * A tela de entrada: o mapa plano do Brasil com a busca fixa no topo. Sem nada escolhido, o Brasil com cada estado
 * pintado pelo que a Raíz já leu (completo, incompleto com a contagem, ou ainda não processado). Tocar num estado
 * aproxima e carrega só as fazendas aptas dele, agrupadas; com município (pela busca ou por um toque), o mapa voa até
 * ele, pinta as fazendas pela situação e abre o painel com o funil em barras ligado ao mapa. O mesmo mapa fica montado
 * o tempo todo: trocar de estado ou de município não recarrega nada além das camadas dele.
 */
export function Explorar({ municipio, uf }: { municipio: string | null; uf: string | null }) {
  const brasil = useCarga(() => fonte.geo.brasil(), [])
  const estados = useCarga(() => fonte.estados(), [])
  const municipios = useCarga(() => fonte.municipios(), [])
  // o estado em foco: o escolhido, ou o do município aberto; os pontos são só dele
  const ufFoco = municipio ? ufDoCodigo(municipio) : uf
  const leiloes = useCarga(() => municipio ? calendario.leiloes({ estado: ufFoco || undefined }) : Promise.resolve(null), [municipio, ufFoco])
  const emLeilao = useMemo(() => codigosEmLeilao(leiloes.dado?.eventos ?? []), [leiloes.dado])
  const pontos = useCarga(() => (ufFoco ? fonte.pontos(ufFoco) : Promise.resolve([])), [ufFoco])
  const funil = useCarga(() => (municipio ? fonte.municipio(municipio) : Promise.resolve(null)), [municipio])
  const imoveis = useCarga(() => (municipio ? fonte.imoveis(municipio) : Promise.resolve(null)), [municipio])
  const basicos = useCarga(() => (municipio && fonte.basicos ? fonte.basicos(municipio) : Promise.resolve(null)), [municipio])
  const [situacaoBasica, setSituacaoBasica] = useState<SituacaoBasica | null>(null)
  const geoMunicipio = useCarga<GeoMunicipio | null>(async () => {
    if (!municipio) return null
    const [m, i, ti, uc, rios, terraPublica, base] = await Promise.all([
      fonte.geo.camada(municipio, "municipio"),
      fonte.geo.camada(municipio, "imoveis"),
      fonte.geo.camada(municipio, "ti"),
      fonte.geo.camada(municipio, "uc"),
      fonte.geo.camada(municipio, "rios"),
      fonte.geo.camada(municipio, "terra_publica").catch(() => null), // só a API tem; a amostra não
      fonte.geo.base(municipio),
    ])
    return { municipio: m, imoveis: i, ti, uc, rios, terraPublica, base }
  }, [municipio])

  const [foco, setFoco] = useState<Foco>(null)
  const [camada, setCamada] = useState<CamadaAssunto>("situacao")
  const [destaque, setDestaque] = useState<string | null>(null)
  // no celular, sem município o mapa ocupa quase tudo (Brasil ou estado); com município a gaveta sobe até a metade
  const [altura, setAltura] = useState<Altura>(municipio ? "meia" : "baixa")
  const [margem, setMargem] = useState(() => cobertura(municipio ? "meia" : "baixa"))

  // novo município: o funil volta a mostrar tudo
  const [ultimo, setUltimo] = useState(municipio)
  if (ultimo !== municipio) {
    setUltimo(municipio)
    setFoco(null)
    setSituacaoBasica(null)
    setCamada("situacao")
    if (!municipio) setAltura("baixa")
    else if (altura === "baixa") setAltura("meia")
  }

  useEffect(() => {
    const medir = () => setMargem(cobertura(altura))
    medir()
    window.addEventListener("resize", medir)
    return () => window.removeEventListener("resize", medir)
  }, [altura])

  const processados = useMemo(() => new Set((municipios.dado ?? []).map((m) => m.cod_ibge)), [municipios.dado])
  const listas = useMemo(() => new Set((estados.dado?.estados ?? []).flatMap((e) => e.com_lista)), [estados.dado])
  const feicao = municipio ? brasil.dado?.municipios?.features.find((f) => String(f.properties.cod_ibge) === municipio) : undefined
  const centro = useMemo<[number, number] | null>(() => {
    if (!feicao) return null
    let x0 = Infinity,
      y0 = Infinity,
      x1 = -Infinity,
      y1 = -Infinity
    const andar = (c: unknown): void => {
      if (Array.isArray(c) && typeof c[0] === "number") {
        x0 = Math.min(x0, c[0])
        x1 = Math.max(x1, c[0])
        y0 = Math.min(y0, c[1] as number)
        y1 = Math.max(y1, c[1] as number)
      } else if (Array.isArray(c)) c.forEach(andar)
    }
    andar(feicao.geometry.coordinates)
    return [(x0 + x1) / 2, (y0 + y1) / 2]
  }, [feicao])

  // gaveta: toque na alça sobe um degrau (e da mais alta volta para a baixa); arrastar escolhe a mais perto
  const arraste = useRef<{ y: number; inicio: number } | null>(null)
  const soltar = (y: number) => {
    const a = arraste.current
    arraste.current = null
    if (!a) return
    const dy = a.y - y
    if (Math.abs(dy) < 8) return setAltura(ALTURAS[(ALTURAS.indexOf(altura) + 1) % ALTURAS.length])
    const k = ALTURAS.indexOf(altura) + (dy > 0 ? 1 : -1) * (Math.abs(dy) > window.innerHeight * 0.3 ? 2 : 1)
    setAltura(ALTURAS[Math.max(0, Math.min(2, k))])
  }

  return (
    <div className="explorar">
      <Cabecalho atual="mapa" linkMapa="#/" />
      <div className="explorar-corpo">
        <aside
          className={`painel-lateral gaveta-${altura}`}
          aria-label={municipio ? "Painel do município" : uf ? "O estado na Raíz" : "O Brasil na Raíz"}
        >
          <button
            type="button"
            className="gaveta-alca"
            aria-label={altura === "alta" ? "Recolher o painel" : "Abrir mais o painel"}
            onPointerDown={(e) => {
              arraste.current = { y: e.clientY, inicio: Date.now() }
              e.currentTarget.setPointerCapture(e.pointerId)
            }}
            onPointerUp={(e) => soltar(e.clientY)}
            onPointerCancel={() => (arraste.current = null)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault()
                setAltura(ALTURAS[(ALTURAS.indexOf(altura) + 1) % ALTURAS.length])
              }
            }}
          >
            <span aria-hidden="true" />
          </button>
          <div className="painel-rolagem">
            {municipio && !geoMunicipio.carregando && !geoMunicipio.dado?.imoveis?.features.length && (
              <p className="aviso" role="status">
                {brasil.dado?.cobertura?.acesso === "restrito" && brasil.dado.cobertura.com_desenho.includes(municipio)
                  ? "O desenho das fazendas deste município está na base. Para consultar uma fazenda, abra a ficha com acesso pago."
                  : "O desenho das fazendas deste município ainda não está disponível."}
                {listas.has(municipio) && " Os dados e a lista continuam disponíveis."}
              </p>
            )}
            {municipio && estados.dado?.acesso === "publico_basico" ? (
              <PainelMunicipioBasico
                key={municipio}
                nome={funil.dado?.municipio ?? (feicao?.properties.nome as string | undefined) ?? "Município"}
                uf={ufFoco ?? ""}
                centro={centro}
                funil={funil.dado ?? null}
                imoveis={basicos.carregando ? undefined : basicos.dado ?? null}
                situacao={situacaoBasica}
                mudarSituacao={setSituacaoBasica}
                aoPassar={setDestaque}
                emLeilao={emLeilao}
                atualizadoEm={estados.dado.estados.find((e) => e.uf === ufFoco)?.atualizado_em ?? estados.dado.gerado_em}
              />
            ) : municipio ? (
              <PainelMunicipio
                cod={municipio}
                nome={(feicao?.properties.nome as string | undefined) ?? null}
                uf={(feicao?.properties.uf as string | undefined) ?? null}
                centro={centro}
                funil={funil.carregando ? undefined : (funil.dado ?? null)}
                imoveis={imoveis.carregando ? undefined : (imoveis.dado ?? null)}
                foco={foco}
                aoFocar={(f) => setFoco(f)}
                camada={camada}
                mudarCamada={setCamada}
                aoPassar={setDestaque}
                emLeilao={emLeilao}
              />
            ) : (
              <PainelBrasil
                municipios={municipios.dado}
                comLista={listas}
                estados={estados.dado}
                uf={uf}
                pontos={uf ? pontos.dado : undefined}
                carregando={municipios.carregando || estados.carregando}
                cobertura={brasil.dado?.cobertura}
              />
            )}
          </div>
        </aside>
        <MapaBrasil
          brasil={brasil.dado}
          processados={processados}
          comLista={listas}
          estados={estados.dado}
          pontos={pontos.dado ?? []}
          uf={uf}
          municipio={municipio}
          geoMunicipio={geoMunicipio.carregando ? null : (geoMunicipio.dado ?? null)}
          imoveis={imoveis.dado ?? null}
          basicos={basicos.dado ?? null}
          situacaoBasica={situacaoBasica}
          foco={foco}
          camada={camada}
          destaque={destaque}
          emLeilao={emLeilao}
          margemBaixo={margem}
          aoEscolherMunicipio={(cod) => (location.hash = linkMunicipio(cod))}
          aoEscolherEstado={(sigla) => (location.hash = linkEstado(sigla))}
        />
      </div>
    </div>
  )
}
