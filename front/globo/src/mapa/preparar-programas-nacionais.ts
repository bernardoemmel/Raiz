/** Adaptador privado do MapLibre 6.15.0, conferido por versão, hash e testes no build.
 * Antecipa as quatro variantes assim que um bucket fornece a configuração real,
 * antes dos desenhos desse frame, evitando intercalar consultas de link e draws.
 * Nenhum desenho, framebuffer, stencil, loaded ou idle é substituído.
 */
import type { Map as MapaGL, Painter } from "maplibre-gl"

export const VERSAO_PREPARO_NACIONAL = "6.15.0"
type ArgumentosRender = Parameters<Painter["render"]>
type Estilo = ArgumentosRender[0]
type Camada = Estilo["_layers"][string]
type Variante = Parameters<Painter["programCache"]["getProgram"]>[0]
type Configuracao = NonNullable<Variante["programConfiguration"]>
type ConstrutorConfiguracao = new (camada: Camada, zoom: number, filtro: (propriedade: string) => boolean) => Configuracao
interface BucketNacional {
  programConfigurations?: { get(id: string): Configuracao }
  text?: { programConfigurations: { get(id: string): Configuracao } }
  icon?: { segments: { get(): unknown[] }; hasVisibleVertices: boolean }
  iconsInText?: boolean
}

const IDS_NACIONAIS = new Set([
  "background", "earth", "water", "boundaries_country", "estados-preenchimento", "estados-sem-dados",
  "estados-linha", "estado-sobre", "estado-escolhido", "water_label_ocean", "places_country",
  "estados-rotulo-sem-dados", "estados-rotulo",
])
const pintura = (camada: Camada, nome: string): unknown => (camada.paint as { get(nome: string): unknown }).get(nome)
const constante = (camada: Camada, nome: string, fallback: unknown): unknown =>
  (pintura(camada, nome) as { constantOr(fallback: unknown): unknown }).constantOr(fallback)

// O texto nacional permite fontes/tamanhos por seção, mas não imagens nem overrides de paint.
function textoSemImagem(valor: unknown): boolean {
  if (Array.isArray(valor)) return valor[0] !== "image" && valor.every(textoSemImagem)
  if (valor !== null && typeof valor === "object")
    return Object.entries(valor).every(([nome, conteudo]) => ["font-scale", "text-font"].includes(nome) && textoSemImagem(conteudo))
  return valor === null || ["string", "number", "boolean"].includes(typeof valor)
}

function preparar(pintor: Painter, [estilo, transformacao, dados]: ArgumentosRender): "aguardando" | "recusado" | "pronto" {
  const projecao = dados.projectionShaderVariant
  if (pintor.context.gl.isContextLost() || estilo.map.terrain || pintor.renderToTexture || estilo.map.showCollisionBoxes || estilo.map.vertices ||
    dados.showTileBoundaries || dados.showPadding || dados.showOverdrawInspector || estilo.projection?.name !== "mercator" || dados.useSubdivision ||
    dados.isRenderingGlobe || !projecao || projecao.name !== "mercator") return "recusado"
  if (dados.sky && (dados.sky["sky-color"].a !== 0 || dados.sky["horizon-color"].a !== 0)) return "recusado"
  if (estilo._order.some(id => !IDS_NACIONAIS.has(id))) return "recusado"
  const camadas = estilo._order.map(id => estilo._layers[id]).filter(camada => !camada.isHidden(transformacao.zoom))
  const simbolo = estilo._layers["estados-rotulo-sem-dados"]
  if (!simbolo || simbolo.type !== "symbol") return "recusado"
  for (const camada of camadas) {
    if (!["background", "fill", "line", "symbol"].includes(camada.type) || camada.hasOffscreenPass()) return "recusado"
    if (camada.type === "symbol") {
      const icone = camada.getLayoutProperty("icon-image")
      if ((icone !== undefined && icone !== null && icone !== "") || !textoSemImagem(camada.getLayoutProperty("text-field"))) return "recusado"
    }
    if (camada.type === "background" && pintura(camada, "background-opacity") !== 0) return "recusado"
    if (camada.type === "fill" && (pintura(camada, "fill-antialias") || pintura(camada, "fill-layer-opacity") !== 1 || constante(camada, "fill-pattern", 1))) return "recusado"
    if (camada.type === "line" && (pintura(camada, "line-layer-opacity") !== 1 || constante(camada, "line-pattern", 1) ||
      constante(camada, "line-dasharray", 1) || pintura(camada, "line-gradient"))) return "recusado"
  }
  let Construtor: ConstrutorConfiguracao | undefined
  for (const camada of camadas) {
    if (camada.type === "background") continue
    const fonte = estilo.tileManagers[camada.source]
    if (!fonte) continue
    for (const coordenada of fonte.getVisibleCoordinates(camada.type === "symbol")) {
      const bucket = fonte.getTile(coordenada)?.getBucket(camada) as BucketNacional | undefined
      if (!bucket) continue
      if (bucket.iconsInText || (bucket.icon?.segments.get().length && bucket.icon.hasVisibleVertices)) return "recusado"
      const configuracao = camada.type === "symbol" ? bucket.text?.programConfigurations.get(camada.id) : bucket.programConfigurations?.get(camada.id)
      if (configuracao) Construtor = configuracao.constructor as ConstrutorConfiguracao
    }
  }
  // Não agenda frames nem espera um prazo: tiles pendentes já provocam os próximos renders.
  if (!Construtor) return "aguardando"
  const variantes: Variante[] = []
  const chaves = new Set<string>()
  const adicionar = (nome: string, configuracao?: Configuracao) => {
    const chave = nome + (configuracao?.cacheKey ?? "")
    if (chaves.has(chave)) return
    chaves.add(chave)
    variantes.push({ name: nome, programConfiguration: configuracao, projectionShaderVariant: projecao,
      showOverdrawInspector: dados.showOverdrawInspector, useTerrain: false, defines: [] })
  }
  adicionar("clippingMask")
  // A camada estadual fixa estabiliza os bytes do SDF usados também pelo aquecedor.
  // A ordem de desenho continua sendo a ordem original do estilo.
  const configuracaoSimbolo = new Construtor(simbolo, transformacao.zoom, propriedade => propriedade.startsWith("text"))
  const mesmosNomes = (a: string[], b: string[]) => {
    const aa = [...a].sort(), bb = [...b].sort()
    return aa.length === bb.length && aa.every((nome, indice) => nome === bb[indice])
  }
  for (const camada of camadas.filter(camada => camada.type !== "background")) {
    const filtro = camada.type === "symbol" ? (propriedade: string) => propriedade.startsWith("text") : () => true
    const configuracao = new Construtor(camada, transformacao.zoom, filtro)
    if (!configuracao.cacheKey || configuracao.cacheKey.split("/").filter(Boolean).some(chave => !chave.startsWith("u_")) ||
      configuracao.getBinderAttributes().length) {
      configuracao.destroy()
      return "recusado"
    }
    if (camada.type === "symbol") {
      if (configuracao.cacheKey !== configuracaoSimbolo.cacheKey || configuracaoSimbolo.getBinderAttributes().length ||
        !mesmosNomes(configuracao.defines(), configuracaoSimbolo.defines()) ||
        !mesmosNomes(configuracao.getBinderUniforms(), configuracaoSimbolo.getBinderUniforms())) return "recusado"
      adicionar("symbolSDF", configuracaoSimbolo)
    } else adicionar(camada.type, configuracao)
  }
  // Só depois de conferir TODAS as configurações: nenhum preparo parcial em estilo desconhecido.
  for (const variante of variantes) pintor.programCache.getProgram(variante)
  return "pronto"
}

/** Opt-in somente no mapa nacional. O caminho nativo permanece para estilos não conferidos. */
export function instalarPreparoProgramasNacionais(mapa: Pick<MapaGL, "painter" | "version">): () => void {
  if (mapa.version !== VERSAO_PREPARO_NACIONAL) return () => {}
  const pintor = mapa.painter
  const original = pintor.render
  let ativo = true
  const restaurar = () => {
    ativo = false
    if (pintor.render === adaptado) pintor.render = original
  }
  const adaptado: Painter["render"] = function (this: Painter, ...argumentos) {
    if (ativo) {
      try { if (preparar(this, argumentos) !== "aguardando") restaurar() }
      // Uma estrutura não reconhecida volta ao renderizador nativo, inclusive seus diagnósticos de GL.
      catch { restaurar() }
    }
    return original.apply(this, argumentos)
  }
  pintor.render = adaptado
  return restaurar
}
