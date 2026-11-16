import { useEffect, useState } from "react"
import { buscarProcessamento, urlProcessamento, type ProcessamentoEstados } from "../../compartilhado/dados/processamento-estados"

export interface CargaProcessamento {
  dado?: ProcessamentoEstados
  erro: boolean
  carregando: boolean
  agora: number
}

type Visibilidade = Pick<Document, "visibilityState" | "addEventListener" | "removeEventListener">

/** Uma consulta por vez, sem atividade em aba oculta e sem respostas após desmontar. */
export function acompanharProcessamento(
  url: string,
  notificar: (carga: CargaProcessamento) => void,
  documento: Visibilidade = document,
  ler = buscarProcessamento,
): () => void {
  let vivo = true
  let dado: ProcessamentoEstados | undefined
  let controle: AbortController | undefined
  let proxima: ReturnType<typeof setTimeout> | undefined
  let retomar = false
  const visivel = () => documento.visibilityState !== "hidden"

  async function consultar() {
    if (!vivo || !visivel()) return
    if (controle) { retomar = true; return }
    retomar = false
    const atual = controle = new AbortController()
    let expirou = false
    const prazo = setTimeout(() => { expirou = true; atual.abort() }, 20_000)
    notificar({ dado, erro: false, carregando: !dado, agora: Date.now() })
    try {
      const recebido = await ler(url, atual.signal)
      if (!vivo || atual.signal.aborted) return
      dado = recebido
      notificar({ dado, erro: false, carregando: false, agora: Date.now() })
    } catch {
      if (vivo && (!atual.signal.aborted || expirou)) notificar({ dado, erro: true, carregando: false, agora: Date.now() })
    } finally {
      clearTimeout(prazo)
      controle = undefined
      if (vivo && visivel()) {
        proxima = setTimeout(consultar, retomar ? 0 : 30_000)
        retomar = false
      }
    }
  }

  function visibilidade() {
    clearTimeout(proxima)
    if (!visivel()) { controle?.abort(); return }
    void consultar()
  }

  documento.addEventListener("visibilitychange", visibilidade)
  void consultar()
  return () => {
    vivo = false
    clearTimeout(proxima)
    controle?.abort()
    documento.removeEventListener("visibilitychange", visibilidade)
  }
}

export function useProcessamentoEstados(ativo = true): CargaProcessamento {
  const [carga, setCarga] = useState<CargaProcessamento>(() => ({ erro: false, carregando: true, agora: Date.now() }))
  useEffect(() => {
    if (ativo) return acompanharProcessamento(urlProcessamento(import.meta.env), setCarga)
  }, [ativo])
  // A contagem "agora" vence no prazo da fonte mesmo se a próxima consulta estiver lenta.
  useEffect(() => {
    if (!ativo) return
    const vencimentos = (carga.dado?.estados ?? []).map((e) => e.valido_ate ? Date.parse(e.valido_ate) : NaN).filter((t) => t > carga.agora)
    if (!vencimentos.length) return
    const atraso = Math.min(2_147_483_647, Math.max(1, Math.min(...vencimentos) - Date.now() + 1))
    const prazo = setTimeout(() => setCarga((atual) => ({ ...atual, agora: Date.now() })), atraso)
    return () => clearTimeout(prazo)
  }, [ativo, carga.dado, carga.agora])
  return carga
}
