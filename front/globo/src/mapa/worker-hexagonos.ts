import type { CaixaHexagonos, ConsultaHexagonos, ResumoHexagonos } from "./hexagonos"
import type { Geo } from "../../../compartilhado/dados"
import type { EntradaHexagonos, RequisicaoHexagonos, RespostaHexagonos } from "./protocolo-hexagonos"

export type { EntradaHexagonos } from "./protocolo-hexagonos"
export type { CaixaHexagonos, ConsultaHexagonos, ResumoHexagonos } from "./hexagonos"

interface Pendente { resolver: (valor: RespostaHexagonos) => void; rejeitar: (erro: Error) => void }
const cancelamento = () => new DOMException("A consulta foi substituída.", "AbortError")

export class WorkerHexagonos {
  private readonly worker: Worker
  private readonly pendentes = new Map<number, Pendente>()
  private geracao = 0
  private sequencia = 0
  private encerrado = false
  private erroFatal: Error | null = null

  constructor() {
    this.worker = new Worker(new URL("./hexagonos.worker.ts", import.meta.url), { type: "module" })
    this.worker.onmessage = (evento: MessageEvent<RespostaHexagonos>) => {
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
      this.erroFatal = new Error("Não foi possível abrir os hexágonos públicos.")
      this.cancelar(this.erroFatal)
      this.encerrar()
    }
    this.worker.onerror = falhou
    this.worker.onmessageerror = falhou
  }

  private cancelar(erro: Error) {
    for (const pendente of this.pendentes.values()) pendente.rejeitar(erro)
    this.pendentes.clear()
  }

  private enviar(pedido: RequisicaoHexagonos): Promise<RespostaHexagonos> {
    if (this.encerrado) return Promise.reject(this.erroFatal ?? cancelamento())
    return new Promise((resolver, rejeitar) => {
      this.pendentes.set(pedido.id, { resolver, rejeitar })
      try { this.worker.postMessage(pedido) }
      catch { this.pendentes.delete(pedido.id); rejeitar(new Error("Não foi possível consultar os hexágonos públicos.")) }
    })
  }

  async carregar(entrada: EntradaHexagonos): Promise<ResumoHexagonos> {
    this.cancelar(cancelamento())
    const resposta = await this.enviar({ id: ++this.sequencia, geracao: ++this.geracao, acao: "carregar", entrada })
    if (resposta.tipo !== "pronto") throw new Error("Resposta dos hexágonos inválida.")
    return resposta.resumo
  }

  async consultar(bbox: CaixaHexagonos, zoom: number, destaques: readonly string[] = []): Promise<ConsultaHexagonos> {
    const resposta = await this.enviar({ id: ++this.sequencia, geracao: this.geracao, acao: "consultar", bbox, zoom, destaques })
    if (resposta.tipo !== "hexagonos") throw new Error("Resposta dos hexágonos inválida.")
    return resposta.consulta
  }

  async autorizar(geo: Geo | null): Promise<void> {
    const resposta = await this.enviar({ id: ++this.sequencia, geracao: this.geracao, acao: "autorizar", geo })
    if (resposta.tipo !== "autorizado") throw new Error("Resposta da área autorizada inválida.")
  }

  encerrar(): void {
    if (this.encerrado) return
    this.encerrado = true
    this.worker.terminate()
    this.cancelar(cancelamento())
  }
}
