import { latLngToCell } from "h3-js"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { Geo } from "../../../compartilhado/dados"
import { IndiceHexagonos } from "./hexagonos"
import type { RequisicaoHexagonos, RespostaHexagonos } from "./protocolo-hexagonos"
import { ServidorHexagonos } from "./servidor-hexagonos"
import { WorkerHexagonos } from "./worker-hexagonos"

const url = "https://raiz.example/Raiz/geo/agregados_brasil.geojson"
const dados: Geo = { type: "FeatureCollection", features: [
  { type: "Feature", geometry: { type: "Point", coordinates: [-50, -6] }, properties: { h3: latLngToCell(-6, -50, 5), fazendas: 8, potencial_ha: 1.5, nome: "NAO-PUBLICAR" } },
] }
const indice = new IndiceHexagonos(dados)
const resumo = indice.resumo
const resultado = indice.consultar([-70, -30, -30, 10], 3)
const consulta = (id: number, geracao = 1): RequisicaoHexagonos => ({ acao: "consultar", id, geracao, bbox: [-70, -30, -30, 10], zoom: 3 })
const area: Geo = { type: "FeatureCollection", features: [{ type: "Feature", properties: { cod_imovel: "AREA-PRIVADA", nome: "NAO-PUBLICAR" },
  geometry: { type: "Polygon", coordinates: [[[-50.001, -6.001], [-49.999, -6.001], [-49.999, -5.999], [-50.001, -5.999], [-50.001, -6.001]]] } }] }

describe("protocolo de hexágonos públicos", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("conserva o contexto global exigido pelo fetch nativo do navegador", async () => {
    vi.stubGlobal("fetch", function (this: unknown) {
      if (this !== globalThis) throw new TypeError("Illegal invocation")
      return Promise.resolve(new Response(JSON.stringify(dados)))
    })
    const respostas: RespostaHexagonos[] = []
    const servidor = new ServidorHexagonos(url, resposta => respostas.push(resposta))
    await servidor.receber({ acao: "carregar", id: 1, geracao: 1, entrada: url })
    expect(respostas).toEqual([{ id: 1, geracao: 1, tipo: "pronto", resumo }])
  })

  it("lê só a URL pública exata, sem credenciais/redirecionamento, e devolve a projeção pública", async () => {
    const respostas: RespostaHexagonos[] = []
    const transporte = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify(dados)))
    const servidor = new ServidorHexagonos(url, r => respostas.push(r), transporte)
    await servidor.receber({ acao: "carregar", id: 1, geracao: 1, entrada: url })
    expect(transporte).toHaveBeenCalledWith(url, expect.objectContaining({ credentials: "omit", redirect: "error", signal: expect.any(AbortSignal) }))
    await servidor.receber(consulta(2))
    expect(respostas[1]).toMatchObject({ tipo: "hexagonos", consulta: resultado })
    expect(JSON.stringify(respostas)).not.toContain("NAO-PUBLICAR")
    let geracao = 1
    for (const arquivo of [url + "?token=segredo", url + "#privado", "https://outro.example/privado", "https://usuario:senha@raiz.example/Raiz/geo/agregados_brasil.geojson"]) {
      await servidor.receber({ acao: "carregar", id: ++geracao, geracao, entrada: arquivo })
      expect(transporte).toHaveBeenCalledTimes(1)
      expect(respostas.at(-1)).toMatchObject({ geracao, tipo: "erro" })
    }
  })

  it("não expõe erros de transporte e descarta o índice anterior após uma carga com falha", async () => {
    const respostas: RespostaHexagonos[] = []
    const servidor = new ServidorHexagonos(url, r => respostas.push(r), vi.fn<typeof fetch>().mockResolvedValue(new Response("CORPO-PRIVADO", { status: 503 })))
    await servidor.receber({ acao: "carregar", id: 1, geracao: 1, entrada: dados })
    await servidor.receber({ acao: "carregar", id: 2, geracao: 2, entrada: url })
    await servidor.receber(consulta(3, 2))
    expect(respostas.map(r => r.tipo)).toEqual(["pronto", "erro", "erro"])
    expect(JSON.stringify(respostas)).not.toContain("CORPO-PRIVADO")
    expect(JSON.stringify(respostas)).not.toContain(url)
  })

  it("aborta a carga substituída e ignora a resposta tardia mesmo se o transporte ignorar o abort", async () => {
    const respostas: RespostaHexagonos[] = []
    let concluir!: (r: Response) => void
    const transporte = vi.fn<typeof fetch>().mockImplementation(() => new Promise(resolve => { concluir = resolve }))
    const servidor = new ServidorHexagonos(url, r => respostas.push(r), transporte)
    const antiga = servidor.receber({ acao: "carregar", id: 1, geracao: 1, entrada: url })
    const sinal = transporte.mock.calls[0][1]!.signal!
    await servidor.receber({ acao: "carregar", id: 2, geracao: 2, entrada: null })
    expect(sinal.aborted).toBe(true)
    concluir(new Response(JSON.stringify(dados)))
    await antiga
    await servidor.receber(consulta(3, 2))
    await servidor.receber(consulta(4, 1))
    expect(respostas.map(r => [r.id, r.tipo])).toEqual([[2, "pronto"], [3, "hexagonos"], [4, "erro"]])
    expect(respostas[1]).toMatchObject({ consulta: { geo: { features: [] }, hexagonos: [] } })
    expect(respostas[2]).toMatchObject({ cancelado: true })
  })

  it("retém só a autorização geométrica, reaplica na recarga e ignora autorização tardia de outra geração", async () => {
    const respostas: RespostaHexagonos[] = []
    const servidor = new ServidorHexagonos(url, r => respostas.push(r))
    await servidor.receber({ acao: "autorizar", id: 1, geracao: 0, geo: area })
    expect(respostas[0]).toEqual({ id: 1, geracao: 0, tipo: "autorizado" })
    await servidor.receber({ acao: "carregar", id: 2, geracao: 1, entrada: dados })
    await servidor.receber(consulta(3))
    expect(respostas.at(-1)).toMatchObject({ tipo: "hexagonos", consulta: { geo: { features: [{ properties: { selecionado: true } }] } } })
    await servidor.receber({ acao: "carregar", id: 4, geracao: 2, entrada: dados })
    await servidor.receber({ acao: "autorizar", id: 5, geracao: 1, geo: null })
    expect(respostas.at(-1)).toMatchObject({ tipo: "erro", cancelado: true })
    await servidor.receber(consulta(6, 2))
    expect(respostas.at(-1)).toMatchObject({ consulta: { geo: { features: [{ properties: { selecionado: true } }] } } })
    await servidor.receber({ acao: "autorizar", id: 7, geracao: 2, geo: null })
    await servidor.receber(consulta(8, 2))
    expect(respostas.at(-1)).toMatchObject({ consulta: { geo: { features: [{ properties: { selecionado: false } }] } } })
    for (const proibido of ["AREA-PRIVADA", "NAO-PUBLICAR", "cod_imovel", "nome"]) expect(JSON.stringify(respostas)).not.toContain(proibido)
  })

  it("uma autorização inválida retorna erro sanitizado e não derruba o índice público", async () => {
    const respostas: RespostaHexagonos[] = []
    const servidor = new ServidorHexagonos(url, r => respostas.push(r))
    await servidor.receber({ acao: "carregar", id: 1, geracao: 1, entrada: dados })
    await servidor.receber({ acao: "autorizar", id: 2, geracao: 1, geo: area })
    await servidor.receber({ acao: "autorizar", id: 3, geracao: 1, geo: dados })
    expect(respostas.at(-1)).toEqual({ id: 3, geracao: 1, tipo: "erro", mensagem: "Não foi possível aplicar a área autorizada." })
    await servidor.receber(consulta(4))
    expect(respostas.at(-1)).toMatchObject({ tipo: "hexagonos", consulta: { geo: { features: [{ properties: { selecionado: false, fazendas: 8 } }] } } })
  })
})

class WorkerFalso {
  static ultimo: WorkerFalso
  onmessage: ((evento: MessageEvent<RespostaHexagonos>) => void) | null = null
  onerror: (() => void) | null = null
  onmessageerror: (() => void) | null = null
  enviados: RequisicaoHexagonos[] = []
  encerrado = false
  constructor() { WorkerFalso.ultimo = this }
  postMessage(pedido: RequisicaoHexagonos) { this.enviados.push(pedido) }
  terminate() { this.encerrado = true }
  responder(resposta: RespostaHexagonos) { this.onmessage?.({ data: resposta } as MessageEvent<RespostaHexagonos>) }
}

describe("cliente do worker de hexágonos", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("correlaciona consultas concorrentes, preserva destaques explícitos e rejeita gerações antigas", async () => {
    vi.stubGlobal("Worker", WorkerFalso)
    const cliente = new WorkerHexagonos(), worker = WorkerFalso.ultimo
    const carga = cliente.carregar(url)
    worker.responder({ id: 1, geracao: 1, tipo: "pronto", resumo })
    await expect(carga).resolves.toEqual(resumo)
    const a = cliente.consultar([-70, -30, -30, 10], 3), b = cliente.consultar([-50, -10, -40, 0], 5, [String(dados.features[0].properties.h3)])
    expect(worker.enviados[2]).toMatchObject({ destaques: [dados.features[0].properties.h3] })
    worker.responder({ id: 3, geracao: 1, tipo: "hexagonos", consulta: resultado })
    worker.responder({ id: 2, geracao: 1, tipo: "hexagonos", consulta: resultado })
    await expect(a).resolves.toEqual(resultado)
    await expect(b).resolves.toEqual(resultado)
    const consultaAntiga = cliente.consultar([-70, -30, -30, 10], 3)
    const rejeitada = expect(consultaAntiga).rejects.toMatchObject({ name: "AbortError" })
    const nova = cliente.carregar(null)
    worker.responder({ id: 4, geracao: 1, tipo: "hexagonos", consulta: resultado })
    worker.responder({ id: 5, geracao: 2, tipo: "pronto", resumo: new IndiceHexagonos(null).resumo })
    await rejeitada
    await nova
    cliente.encerrar()
  })

  it("termina o worker e rejeita pendências na desmontagem e em erros fatais", async () => {
    vi.stubGlobal("Worker", WorkerFalso)
    const cliente = new WorkerHexagonos(), worker = WorkerFalso.ultimo
    const carga = cliente.carregar(url)
    const rejeitada = expect(carga).rejects.toMatchObject({ name: "AbortError" })
    cliente.encerrar()
    cliente.encerrar()
    await rejeitada
    expect(worker.encerrado).toBe(true)
    await expect(cliente.consultar([-180, -90, 180, 90], 2)).rejects.toMatchObject({ name: "AbortError" })
    const outro = new WorkerHexagonos()
    const falha = outro.carregar(url)
    WorkerFalso.ultimo.onerror?.()
    await expect(falha).rejects.toThrow("Não foi possível abrir")
    expect(WorkerFalso.ultimo.encerrado).toBe(true)
    await expect(outro.consultar([-180, -90, 180, 90], 2)).rejects.toThrow("Não foi possível abrir")
    await expect(outro.carregar(null)).rejects.toThrow("Não foi possível abrir")
  })

  it("envia a área somente ao worker e aguarda confirmação sem geometria na resposta", async () => {
    vi.stubGlobal("Worker", WorkerFalso)
    const cliente = new WorkerHexagonos(), worker = WorkerFalso.ultimo
    const autorizacao = cliente.autorizar(area)
    expect(worker.enviados[0]).toEqual({ id: 1, geracao: 0, acao: "autorizar", geo: area })
    worker.responder({ id: 1, geracao: 0, tipo: "autorizado" })
    await expect(autorizacao).resolves.toBeUndefined()
    const limpar = cliente.autorizar(null)
    worker.responder({ id: 2, geracao: 0, tipo: "autorizado" })
    await expect(limpar).resolves.toBeUndefined()
    cliente.encerrar()
  })
})
