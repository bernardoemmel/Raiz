import type { GrupoMapa } from "./grupos"
import type { CaixaGrupos, EntradaGrupos, RequisicaoGrupos, RespostaGrupos } from "./protocolo-grupos"

export type { CaixaGrupos, EntradaGrupos } from "./protocolo-grupos"

interface Pendente {
  resolver: (valor: RespostaGrupos) => void
  rejeitar: (erro: Error) => void
}
const cancelamento = () => new DOMException("A consulta foi substituída.", "AbortError")

/** A interface só recebe grupos do enquadramento e o zoom de expansão; o índice fica no worker. */
export class WorkerGrupos {
  private readonly worker: Worker
  private readonly pendentes = new Map<number, Pendente>()
  private geracao = 0
  private sequencia = 0
  private encerrado = false
  private erroFatal: Error | null = null

  constructor() {
    this.worker = new Worker(new URL("./grupos.worker.ts", import.meta.url), { type: "module" })
    this.worker.onmessage = (evento: MessageEvent<RespostaGrupos>) => {
      const resposta = evento.data
      if (resposta.geracao !== this.geracao) return
      const pendente = this.pendentes.get(resposta.id)
      if (!pendente) return
      this.pendentes.delete(resposta.id)
      if (resposta.tipo === "erro") pendente.rejeitar(resposta.cancelado ? cancelamento() : new Error(resposta.mensagem))
      else pendente.resolver(resposta)
    }
    const falhou = () => {
      if (this.encerrado) return
      this.erroFatal = new Error("Não foi possível abrir os agregados públicos.")
      this.cancelar(this.erroFatal)
      this.destruir()
    }
    this.worker.onerror = falhou
    this.worker.onmessageerror = falhou
  }

  private cancelar(erro: Error) {
    for (const pendente of this.pendentes.values()) pendente.rejeitar(erro)
    this.pendentes.clear()
  }

  private enviar(pedido: RequisicaoGrupos): Promise<RespostaGrupos> {
    if (this.encerrado) return Promise.reject(this.erroFatal ?? cancelamento())
    return new Promise((resolver, rejeitar) => {
      this.pendentes.set(pedido.id, { resolver, rejeitar })
      try { this.worker.postMessage(pedido) }
      catch { this.pendentes.delete(pedido.id); rejeitar(new Error("Não foi possível consultar os agregados públicos.")) }
    })
  }

  async carregar(entrada: EntradaGrupos): Promise<void> {
    this.cancelar(cancelamento())
    const resposta = await this.enviar({ id: ++this.sequencia, geracao: ++this.geracao, acao: "carregar", entrada })
    if (resposta.tipo !== "pronto") throw new Error("Resposta dos agregados inválida.")
  }

  async consultar(bbox: CaixaGrupos, zoom: number): Promise<GrupoMapa[]> {
    const resposta = await this.enviar({ id: ++this.sequencia, geracao: this.geracao, acao: "consultar", bbox, zoom })
    if (resposta.tipo !== "grupos") throw new Error("Resposta dos agregados inválida.")
    return resposta.grupos
  }

  async aproximar(clusterId: number): Promise<number> {
    const resposta = await this.enviar({ id: ++this.sequencia, geracao: this.geracao, acao: "aproximar", cluster: clusterId })
    if (resposta.tipo !== "zoom") throw new Error("Resposta dos agregados inválida.")
    return resposta.zoom
  }

  destruir(): void {
    if (this.encerrado) return
    this.encerrado = true
    this.worker.terminate()
    this.cancelar(cancelamento())
  }
}
