import { ServidorGrupos } from "./servidor-grupos"
import type { RequisicaoGrupos } from "./protocolo-grupos"

const arquivo = new URL(`${import.meta.env.BASE_URL}geo/agregados_brasil.geojson`, globalThis.location.origin).href
const servidor = new ServidorGrupos(arquivo, resposta => globalThis.postMessage(resposta))
globalThis.onmessage = (evento: MessageEvent<RequisicaoGrupos>) => { void servidor.receber(evento.data) }
