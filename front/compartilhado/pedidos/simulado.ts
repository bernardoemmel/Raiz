/** Demonstração local, com o mesmo transporte/DTO da API. Nenhuma leitura de cadastro ou Release. */
import { fontePedidosApi, type FontePedidos } from "./fonte-pedidos"
import { CAMPOS_PADRAO } from "./exemplo"
import type { CamposPedido, IdOpcao, MudancaLote, Opcao, Pedido } from "./tipos"
import { tituloDoPedido } from "./texto"
import { fichaCreditoDemonstracao } from "./ficha-credito-demonstracao"
import { CHAVE_DEMONSTRACAO, type guarda } from "./sessao"

const TOKEN = "demonstracao-local-sem-valor-de-autenticacao"
const IDS: IdOpcao[] = ["barata", "segura", "compacta"]

/** Contornos artificiais: não são os limites de imóveis reais nem IDs do CAR. */
export function pedidoDemonstracao(campos: CamposPedido = structuredClone(CAMPOS_PADRAO)): Pedido {
  const opcoes: Opcao[] = IDS.map((id, i) => {
    const lon = -53.4 + i * 0.5, lat = -7.2
    const creditos = { p10: 900_000 + i * 60_000, p50: 1_100_000 + i * 30_000, p90: 1_300_000 + i * 20_000 }
    const hectares = 5_000 + i * 100
    return {
      id, creditos, hectares, fazendas: 2, pequenas: 1,
      ficha_credito: fichaCreditoDemonstracao({ id, creditos, hectares }),
      tir: { p10: 0.08, p50: 0.12 + i / 100, p90: 0.17 },
      custo_usd_credito: { p10: 18 + i, p50: 20 + i, p90: 24 + i },
      pico_caixa_usd: 500_000, marcos: [{ ano: 7, fracao: 0.12, chance: 0.8 }],
      multa_esperada_usd: 1_000, mistura_terra: [{ caminho: "matricula_a_conferir", fracao: 0.6 }, { caminho: "matricula_conferida", fracao: 0.4 }],
      metodos: [{ metodo: "regeneracao_assistida", fazendas: 2 }],
      alcanca_meta: true, falta: 0,
      destrava: [{ tipo: "regularizacao", texto: "Exemplo: conferir a matrícula e o georreferenciamento.", fazendas: 1, hectares: 750, creditos: 123_000, creditos_faixa: null, somavel: false }],
      o_que_falta: ["Pendência fictícia: conferir documento de uso da terra. Nenhuma venda está liberada."],
      itens: [0, 1].map((n) => ({
        cod_imovel: `DEMONSTRACAO-${i + 1}-${n + 1}`, cod_ibge: "0000000", municipio: "Local fictício", uf: "PA", papel: "lote",
        ficha_liberada: true, hectares: n === 0 ? hectares - 100 : 100,
        creditos: { p10: creditos.p10 / 2, p50: creditos.p50 / 2, p90: creditos.p90 / 2 },
        metodo: "regeneracao_assistida", caminho: n === 0 ? "matricula_a_conferir" : "matricula_conferida",
        custo_usd_credito: 20 + i, pequena: n === 1, interesse: "sem_contato", lon: lon + n * 0.16, lat,
        geometria: { type: "Polygon", coordinates: [[[lon + n * 0.16 - 0.07, lat - 0.08], [lon + n * 0.16 + 0.07, lat - 0.08], [lon + n * 0.16 + 0.07, lat + 0.08], [lon + n * 0.16 - 0.07, lat + 0.08], [lon + n * 0.16 - 0.07, lat - 0.08]]] },
      })),
    }
  })
  return {
    id: "demonstracao", criado_em: "2026-11-12T12:00:00Z", campos, status: "lote_montado", opcoes,
    base: { fazendas: 20, hectares: 20_000, creditos: { p10: 2_000_000, p50: 2_500_000, p90: 3_000_000 },
      por_caminho: [], por_interesse: [], alcanca_meta: true, falta: 0, afrouxar: [], observacao: "Base inteiramente fictícia para conhecer a tela." },
    opcao_escolhida: null, reservado_ate: null, alertas: [], versao_modelo: "demonstracao-ficticia-v1", exemplo: true,
  }
}

export function fontePedidosSimulada(armazenamento?: ReturnType<typeof guarda>): FontePedidos {
  let pedido = pedidoDemonstracao()
  let iniciada = false
  let inicioBusca: number | null = null
  const responder = (corpo: unknown, status = 200) => new Response(JSON.stringify(corpo), { status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } })
  const transporte: typeof fetch = async (entrada, init) => {
    const caminho = new URL(String(entrada)).pathname.replace(/^\//, "")
    const corpo = typeof init?.body === "string" ? JSON.parse(init.body) : null
    if (caminho === "entrar/confirmar" && init?.method === "POST") {
      if (corpo?.token !== "demonstracao") return responder({ erro: "Entrada de demonstração inválida." }, 401)
      iniciada = true
      return responder({ token: TOKEN, email: "demonstracao@example.invalid" })
    }
    if (new Headers(init?.headers).get("Authorization") !== `Bearer ${TOKEN}`) return responder({ erro: "Abra a demonstração antes de consultar o exemplo." }, 401)
    if (caminho === "pedidos" && init?.method === "POST") {
      pedido = pedidoDemonstracao(corpo as CamposPedido)
      iniciada = true
      return responder(pedido)
    }
    if (caminho === "pedidos") return responder(iniciada ? [{ id: pedido.id, criado_em: pedido.criado_em, titulo: tituloDoPedido(pedido.campos), status: pedido.status, reservado_ate: null, com_interesse: null, alertas: 0 }] : [])
    if (caminho === "pedidos/demonstracao") return responder(pedido)
    if (caminho === "pedidos/demonstracao/lote" && init?.method === "POST") {
      const m = corpo as MudancaLote
      if (m.acao !== "tirar") return responder({ erro: "A demonstração não tem fazendas de reserva." }, 409)
      const opcao = pedido.opcoes.find((o) => o.id === m.opcao)
      if (!opcao) return responder({ erro: "Opção desconhecida." }, 400)
      // A edição demonstra a interação; não recalcula nem se apresenta como resultado do solver.
      const removida = opcao.itens.find((f) => f.cod_imovel === m.cod_imovel)
      if (removida) {
        // A ficha é uma fotografia da composição; editar não inventa outra evidência/revisão.
        delete opcao.ficha_credito
        opcao.itens = opcao.itens.filter((f) => f !== removida)
        opcao.fazendas = opcao.itens.length
        opcao.pequenas = opcao.itens.filter((f) => f.pequena).length
        opcao.hectares -= removida.hectares ?? 0
        for (const q of ["p10", "p50", "p90"] as const) opcao.creditos[q] -= removida.creditos?.[q] ?? 0
        opcao.falta = Math.max(0, pedido.campos.meta.valor - opcao.creditos.p50)
        opcao.alcanca_meta = opcao.falta === 0
      }
      return responder(pedido)
    }
    // A demonstração corre as ondas na tela, com fazendas fictícias. Não há contato real nem cobrança.
    if (caminho === "pedidos/demonstracao/solicitar-interesse" && init?.method === "POST") {
      const opcao = (corpo as { opcao?: IdOpcao } | null)?.opcao
      if (!opcao || !IDS.includes(opcao)) return responder({ erro: "Opção desconhecida." }, 400)
      pedido = { ...pedido, opcao_escolhida: opcao, status: "buscando_interesse" }
      inicioBusca = Date.now()
      return responder(pedido)
    }
    if (caminho === "pedidos/demonstracao/andamento") {
      if (inicioBusca === null || !pedido.opcao_escolhida) return responder({ erro: "A busca ainda não começou." }, 404)
      const escolhida = pedido.opcoes.find((o) => o.id === pedido.opcao_escolhida)
      if (!escolhida) return responder({ erro: "Opção desconhecida." }, 400)
      const pronto = Date.now() - inicioBusca >= 700
      if (pronto) pedido = { ...pedido, status: "grupo_pronto" }
      return responder({
        pedido: pedido.id,
        status: pronto ? "grupo_pronto" : "buscando_interesse",
        meta: pedido.campos.meta.valor,
        com_interessado: pronto ? escolhida.creditos.p50 : 0,
        com_aceite: 0,
        com_contrato: 0,
        ondas: [{ numero: 1, data: new Date(inicioBusca).toISOString(), contatados: escolhida.fazendas, canais: ["demonstração"] }],
        contatados: escolhida.fazendas,
        recusas: 0,
        sem_resposta: pronto ? 0 : escolhida.fazendas,
        motivos: [],
        fazendas: escolhida.itens.map((f) => ({ ...f, interesse: pronto ? "interessado" : "contatado" })),
        grupo_pronto_em: pronto ? new Date(inicioBusca + 700).toISOString() : null,
        proxima_onda_em: pronto ? null : new Date(inicioBusca + 700).toISOString(),
        faltou: null,
      })
    }
    return responder({ erro: "Etapa indisponível na demonstração." }, 409)
  }
  const api = fontePedidosApi("https://demonstracao.invalid/", { transporte, chaveSessao: CHAVE_DEMONSTRACAO, armazenamento })
  return { ...api, exemplo: true }
}
