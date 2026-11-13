import { afterEach, describe, expect, it, vi } from "vitest"
import type { Geo } from "../../../compartilhado/dados"
import type { RequisicaoGrupos, RespostaGrupos } from "./protocolo-grupos"
import { ServidorGrupos } from "./servidor-grupos"
import { WorkerGrupos } from "./worker-grupos"

const url = "https://raiz.example/Raiz/geo/agregados_brasil.geojson"
const dados: Geo = { type: "FeatureCollection", features: [
  { type: "Feature", geometry: { type: "Point", coordinates: [-50, -6] }, properties: { h3: "850000000000001", fazendas: 8, potencial_ha: 1.5, nome: "NAO-PUBLICAR" } },
] }
const consulta = (id: number, geracao = 1): RequisicaoGrupos => ({ acao: "consultar", id, geracao, bbox: [-70, -30, -30, 10], zoom: 3 })

describe("protocolo dos agregados", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("conserva o contexto global exigido pelo fetch nativo do navegador", async () => {
    vi.stubGlobal("fetch", function (this: unknown) {
      if (this !== globalThis) throw new TypeError("Illegal invocation")
      return Promise.resolve(new Response(JSON.stringify(dados)))
    })
    const respostas: RespostaGrupos[] = []
    const servidor = new ServidorGrupos(url, resposta => respostas.push(resposta))
    await servidor.receber({ acao: "carregar", id: 1, geracao: 1, entrada: { url } })
    expect(respostas).toEqual([{ id: 1, geracao: 1, tipo: "pronto" }])
  })

  it("lê somente a URL pública, sem credenciais nem redirecionamento, e devolve apenas grupos", async () => {
    const respostas: RespostaGrupos[] = []
    const transporte = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(dados)))
    const servidor = new ServidorGrupos(url, r => respostas.push(r), transporte)
    await servidor.receber({ acao: "carregar", id: 1, geracao: 1, entrada: { url } })
    expect(transporte).toHaveBeenCalledWith(url, expect.objectContaining({ credentials: "omit", redirect: "error", signal: expect.any(AbortSignal) }))
    expect(respostas).toEqual([{ id: 1, geracao: 1, tipo: "pronto" }])
    await servidor.receber(consulta(2))
    expect(respostas[1]).toMatchObject({ tipo: "grupos", grupos: [{ fazendas: 8, hectares: 1.5 }] })
    for (const proibido of ["NAO-PUBLICAR", "features", "properties", "geometry", "nome"]) expect(JSON.stringify(respostas)).not.toContain(proibido)
    let geracao = 1
    for (const arquivo of [url + "?token=segredo", "https://outro.example/privado", "https://usuario:senha@raiz.example/Raiz/geo/agregados_brasil.geojson"]) {
      const anterior = transporte.mock.calls.length
      await servidor.receber({ acao: "carregar", id: ++geracao, geracao, entrada: { url: arquivo } })
      expect(transporte).toHaveBeenCalledTimes(anterior)
      expect(respostas.at(-1)).toMatchObject({ geracao, tipo: "erro" })
    }
  })

  it("não publica corpo ou URL do erro503, nem conserva o índice anterior após falha", async () => {
    const respostas: RespostaGrupos[] = []
    const servidor = new ServidorGrupos(url, r => respostas.push(r), vi.fn<typeof fetch>().mockResolvedValue(new Response("CORPO-PRIVADO", { status: 503 })))
    await servidor.receber({ acao: "carregar", id: 1, geracao: 1, entrada: { geo: dados } })
    await servidor.receber({ acao: "carregar", id: 2, geracao: 2, entrada: { url } })
    await servidor.receber(consulta(3, 2))
    expect(respostas.map(r => r.tipo)).toEqual(["pronto", "erro", "erro"])
    expect(JSON.stringify(respostas)).not.toContain("CORPO-PRIVADO")
    expect(JSON.stringify(respostas)).not.toContain(url)
  })

  it("aborta leitura substituída e ignora resposta tardia mesmo quando transporte ignora abort", async () => {
    const respostas: RespostaGrupos[] = []
    let concluir!: (r: Response) => void
    const transporte = vi.fn<typeof fetch>().mockImplementation(() => new Promise(resolve => { concluir = resolve }))
    const servidor = new ServidorGrupos(url, r => respostas.push(r), transporte)
    const antiga = servidor.receber({ acao: "carregar", id: 1, geracao: 1, entrada: { url } })
    const sinal = transporte.mock.calls[0][1]!.signal!
    await servidor.receber({ acao: "carregar", id: 2, geracao: 2, entrada: { geo: null } })
    expect(sinal.aborted).toBe(true)
    concluir(new Response(JSON.stringify(dados)))
    await antiga
    await servidor.receber(consulta(3, 2))
    await servidor.receber(consulta(4, 1))
    expect(respostas).toEqual([
      { id: 2, geracao: 2, tipo: "pronto" }, { id: 3, geracao: 2, tipo: "grupos", grupos: [] },
      { id: 4, geracao: 1, tipo: "erro", mensagem: "A consulta foi substituída.", cancelado: true },
    ])
  })
})

class WorkerFalso {
  static ultimo: WorkerFalso
  onmessage: ((evento: MessageEvent<RespostaGrupos>) => void) | null = null
  onerror: (() => void) | null = null
  onmessageerror: (() => void) | null = null
  enviados: RequisicaoGrupos[] = []
  encerrado = false
  constructor() { WorkerFalso.ultimo = this }
  postMessage(pedido: RequisicaoGrupos) { this.enviados.push(pedido) }
  terminate() { this.encerrado = true }
  responder(resposta: RespostaGrupos) { this.onmessage?.({ data: resposta } as MessageEvent<RespostaGrupos>) }
}

describe("cliente do worker", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("correlaciona consultas concorrentes e expansão, rejeitando todas as respostas de geração antiga", async () => {
    vi.stubGlobal("Worker", WorkerFalso)
    const cliente = new WorkerGrupos(), worker = WorkerFalso.ultimo
    const carga = cliente.carregar({ url })
    worker.responder({ ...worker.enviados[0], tipo: "pronto" })
    await carga
    const a = cliente.consultar([-70, -30, -30, 10], 3), b = cliente.consultar([-50, -10, -40, 0], 5)
    worker.responder({ id: 3, geracao: 1, tipo: "grupos", grupos: [] })
    worker.responder({ id: 2, geracao: 1, tipo: "grupos", grupos: [] })
    await expect(a).resolves.toEqual([])
    await expect(b).resolves.toEqual([])
    const expansao = cliente.aproximar(123)
    const rejeitada = expect(expansao).rejects.toMatchObject({ name: "AbortError" })
    const nova = cliente.carregar({ geo: null })
    worker.responder({ id: 4, geracao: 1, tipo: "zoom", zoom: 10 })
    worker.responder({ id: 5, geracao: 2, tipo: "pronto" })
    await rejeitada
    await nova
    const zoom = cliente.aproximar(456)
    worker.responder({ id: 6, geracao: 2, tipo: "zoom", zoom: 11 })
    await expect(zoom).resolves.toBe(11)
    cliente.destruir()
  })

  it("termina o worker e rejeita pendências na desmontagem ou erro de execução", async () => {
    vi.stubGlobal("Worker", WorkerFalso)
    const cliente = new WorkerGrupos(), worker = WorkerFalso.ultimo
    const carga = cliente.carregar({ url })
    const rejeitada = expect(carga).rejects.toMatchObject({ name: "AbortError" })
    cliente.destruir()
    cliente.destruir()
    await rejeitada
    expect(worker.encerrado).toBe(true)
    await expect(cliente.consultar([-180, -90, 180, 90], 2)).rejects.toMatchObject({ name: "AbortError" })
    const outro = new WorkerGrupos()
    const falha = outro.carregar({ url })
    WorkerFalso.ultimo.onerror?.()
    await expect(falha).rejects.toThrow("Não foi possível abrir")
    expect(WorkerFalso.ultimo.encerrado).toBe(true)
    await expect(outro.consultar([-180, -90, 180, 90], 2)).rejects.toThrow("Não foi possível abrir")
    await expect(outro.carregar({ geo: null })).rejects.toThrow("Não foi possível abrir")
  })
})
