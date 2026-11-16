import { ServidorHexagonos } from "./servidor-hexagonos"
import type { RequisicaoHexagonos } from "./protocolo-hexagonos"

const arquivo = new URL(`${import.meta.env.BASE_URL}geo/agregados_brasil.geojson`, globalThis.location.origin).href
const servidor = new ServidorHexagonos(arquivo, resposta => globalThis.postMessage(resposta))
globalThis.onmessage = (evento: MessageEvent<RequisicaoHexagonos>) => { void servidor.receber(evento.data) }
