import { LIMITE_AGREGADOS_NORMAL } from "../../../compartilhado/dados/agregados"
import { IndiceGrupos } from "./indice-grupos"
import type { EntradaGrupos, RequisicaoGrupos, RespostaGrupos } from "./protocolo-grupos"

/** Separado da entrada do worker para testar respostas tardias, falhas e cancelamento sem navegador. */
export class ServidorGrupos {
  private geracao = 0
  private indice: IndiceGrupos | null = null
  private carga: AbortController | null = null
  private readonly urlPublica: string
  private readonly responder: (resposta: RespostaGrupos) => void
  private readonly transporte: typeof fetch

  constructor(urlPublica: string, responder: (resposta: RespostaGrupos) => void, transporte: typeof fetch = fetch) {
    this.urlPublica = urlPublica
    this.responder = responder
    this.transporte = transporte
  }

  private async ler(entrada: EntradaGrupos, signal: AbortSignal): Promise<unknown> {
    if ("geo" in entrada) return entrada.geo
    const url = new URL(entrada.url, this.urlPublica)
    if (url.href !== this.urlPublica || url.username || url.password) throw new Error("Arquivo público inválido.")
    const resposta = await this.transporte(url.href, { signal, credentials: "omit", redirect: "error" })
    if (!resposta.ok) throw new Error("Agregados públicos indisponíveis.")
    const bytes = await resposta.arrayBuffer()
    if (bytes.byteLength > LIMITE_AGREGADOS_NORMAL) throw new Error("Agregados públicos acima do limite.")
    return JSON.parse(new TextDecoder().decode(bytes))
  }

  async receber(pedido: RequisicaoGrupos): Promise<void> {
    const { id, geracao } = pedido
    if (pedido.acao === "carregar" && geracao > this.geracao) {
      this.geracao = geracao
      this.indice = null
      this.carga?.abort()
      this.carga = new AbortController()
      const carga = this.carga
      try {
        const dados = await this.ler(pedido.entrada, carga.signal)
        if (carga.signal.aborted || geracao !== this.geracao) return
        this.indice = new IndiceGrupos(dados)
        this.responder({ id, geracao, tipo: "pronto" })
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
    try {
      if (!this.indice) throw new Error("Índice indisponível.")
      if (pedido.acao === "consultar")
        this.responder({ id, geracao, tipo: "grupos", grupos: this.indice.consultar(pedido.bbox, pedido.zoom) })
      else if (pedido.acao === "aproximar")
        this.responder({ id, geracao, tipo: "zoom", zoom: this.indice.aproximar(pedido.cluster) })
      else throw new Error("Carga repetida.")
    } catch {
      this.responder({ id, geracao, tipo: "erro", mensagem: "Não foi possível consultar os agregados públicos." })
    }
  }
}
