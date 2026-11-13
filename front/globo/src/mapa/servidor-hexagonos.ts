import { LIMITE_AGREGADOS_NORMAL } from "../../../compartilhado/dados/agregados"
import type { Geo } from "../../../compartilhado/dados"
import { IndiceHexagonos, projetarAreaAutorizada } from "./hexagonos"
import type { EntradaHexagonos, RequisicaoHexagonos, RespostaHexagonos } from "./protocolo-hexagonos"

/** Entrada isolada para testar URL pública, falhas e cargas substituídas sem abrir um navegador. */
export class ServidorHexagonos {
  private geracao = 0
  private indice: IndiceHexagonos | null = null
  private carga: AbortController | null = null
  private areaAutorizada: Geo | null = null
  private readonly urlPublica: string
  private readonly responder: (resposta: RespostaHexagonos) => void
  private readonly transporte: typeof fetch

  constructor(urlPublica: string, responder: (resposta: RespostaHexagonos) => void, transporte: typeof fetch = globalThis.fetch.bind(globalThis)) {
    this.urlPublica = urlPublica
    this.responder = responder
    this.transporte = transporte
  }

  private async ler(entrada: EntradaHexagonos, signal: AbortSignal): Promise<unknown> {
    if (typeof entrada !== "string") return entrada
    const url = new URL(entrada, this.urlPublica)
    if (url.href !== this.urlPublica || url.username || url.password) throw new Error("Arquivo público inválido.")
    const resposta = await this.transporte(url.href, { signal, credentials: "omit", redirect: "error" })
    if (!resposta.ok) throw new Error("Agregados públicos indisponíveis.")
    const bytes = await resposta.arrayBuffer()
    if (bytes.byteLength > LIMITE_AGREGADOS_NORMAL) throw new Error("Agregados públicos acima do limite.")
    return JSON.parse(new TextDecoder().decode(bytes))
  }

  async receber(pedido: RequisicaoHexagonos): Promise<void> {
    const { id, geracao } = pedido
    if (pedido.acao === "carregar" && geracao > this.geracao) {
      this.geracao = geracao
      this.indice = null
      this.carga?.abort()
      const carga = this.carga = new AbortController()
      try {
        const dados = await this.ler(pedido.entrada, carga.signal)
        if (carga.signal.aborted || geracao !== this.geracao) return
        this.indice = new IndiceHexagonos(dados)
        this.indice.destacarAutorizada(this.areaAutorizada)
        this.responder({ id, geracao, tipo: "pronto", resumo: this.indice.resumo })
      } catch {
        if (carga.signal.aborted || geracao !== this.geracao) return
        this.responder({ id, geracao, tipo: "erro", mensagem: "Não foi possível carregar os agregados públicos." })
      }
      return
    }
    if (geracao !== this.geracao) {
      this.responder({ id, geracao, tipo: "erro", mensagem: "A consulta foi substituída.", cancelado: true })
      return
    }
    if (pedido.acao === "autorizar") {
      // Falha fechada: trocar de pedido por uma geometria inválida não deixa o desenho anterior selecionado.
      this.areaAutorizada = null
      this.indice?.destacarAutorizada(null)
      try {
        const geo = projetarAreaAutorizada(pedido.geo)
        this.indice?.destacarAutorizada(geo)
        this.areaAutorizada = geo
        this.responder({ id, geracao, tipo: "autorizado" })
      } catch {
        this.responder({ id, geracao, tipo: "erro", mensagem: "Não foi possível aplicar a área autorizada." })
      }
      return
    }
    try {
      if (!this.indice || pedido.acao !== "consultar") throw new Error("Índice indisponível.")
      this.responder({ id, geracao, tipo: "hexagonos", consulta: this.indice.consultar(pedido.bbox, pedido.zoom, pedido.destaques) })
    } catch {
      this.responder({ id, geracao, tipo: "erro", mensagem: "Não foi possível consultar os hexágonos públicos." })
    }
  }
}
