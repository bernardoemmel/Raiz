import { Marker, type Map as MapaGL } from "maplibre-gl"
import { descreverGrupo, raioGrupo, rotulosGrupo, type GrupoMapa } from "./grupos"

interface MarcadorGrupo {
  marcador: Marker
  botao: HTMLButtonElement
  contagem: HTMLSpanElement
  hectares: HTMLSpanElement
  grupo: GrupoMapa
}

/** Só os grupos visíveis têm DOM; o índice e suas somas continuam no worker do MapLibre. */
export class MarcadoresGrupos {
  private readonly visiveis = new Map<string, MarcadorGrupo>()

  private readonly mapa: MapaGL
  private readonly abrir: (grupo: GrupoMapa) => void

  constructor(mapa: MapaGL, abrir: (grupo: GrupoMapa) => void) { this.mapa = mapa; this.abrir = abrir }

  atualizar(grupos: GrupoMapa[]) {
    const chaves = new Set(grupos.map(grupo => grupo.chave))
    for (const [chave, item] of this.visiveis) {
      if (!chaves.has(chave)) { item.marcador.remove(); this.visiveis.delete(chave) }
    }
    for (const grupo of grupos) {
      let item = this.visiveis.get(grupo.chave)
      if (!item) {
        const botao = document.createElement("button")
        botao.type = "button"
        botao.className = "cartografia-grupo"
        const contagem = document.createElement("span"), hectares = document.createElement("span")
        botao.append(contagem, document.createTextNode(" "), hectares)
        item = { botao, contagem, hectares, grupo,
          marcador: new Marker({ element: botao, anchor: "center" }).setLngLat(grupo.centro).addTo(this.mapa) }
        const atual = item
        botao.addEventListener("click", evento => {
          evento.stopPropagation()
          // O grupo pode se dividir e remover este botão durante a aproximação.
          if (document.activeElement === botao) this.mapa.getCanvas().focus({ preventScroll: true })
          this.abrir(atual.grupo)
        })
        this.visiveis.set(grupo.chave, item)
      } else if (item.grupo.centro[0] !== grupo.centro[0] || item.grupo.centro[1] !== grupo.centro[1]) item.marcador.setLngLat(grupo.centro)
      item.grupo = grupo
      item.botao.style.setProperty("--diametro-grupo", `${raioGrupo(grupo) * 2}px`)
      const [contagem, hectares] = rotulosGrupo(grupo)
      item.botao.setAttribute("aria-label", `${contagem} ${hectares}. ${descreverGrupo(grupo)} Aproximar.`)
      if (item.contagem.textContent !== contagem) item.contagem.textContent = contagem
      if (item.hectares.textContent !== hectares) item.hectares.textContent = hectares
    }
  }

  limpar() {
    for (const item of this.visiveis.values()) item.marcador.remove()
    this.visiveis.clear()
  }
}
