/**
 * Com VITE_RAIZ_API, usa as rotas autenticadas de pedidos/tipos.ts. Sem ela, consulta o cenário publicado no
 * Release e guarda só os critérios no navegador. A simulação antiga permanece explícita para testes e não é a
 * fonte do site. O pedido executado de verdade fica no servidor.
 */

import type { FonteDeDados } from "../dados/fonte"
import { bool, num } from "../dados/colunas"
import { pontoDentro } from "../rotulos-mapa"
import {
  candidatoDe,
  CAMPOS_PADRAO,
  cobrancaDe,
  grupoDe,
  IDS_OPCOES,
  montarPedido,
  mudarOnda,
  simularAndamento,
  type Candidato,
  type PedidoGuardado,
} from "./exemplo"
import type { Andamento, CamposPedido, Cobranca, IdOpcao, MudancaLote, Pedido, ResumoPedido, Sessao } from "./tipos"
import { tituloDoPedido } from "./texto"
import { lerPublicacaoLote } from "./release"

export interface FontePedidos {
  /** resposta de exemplo (sem back-end): a tela avisa */
  readonly exemplo: boolean
  /** Consulta local ao resumo público do Release, sem autenticação simulada nem ações comerciais. */
  readonly publica?: boolean
  sessao(): Sessao | null
  /** manda o link de entrada por e-mail; no exemplo, devolve o link para abrir direto */
  entrar(email: string): Promise<{ enviado: boolean; link_exemplo?: string }>
  confirmar(token: string): Promise<Sessao>
  sair(): void
  listar(): Promise<ResumoPedido[]>
  criar(campos: CamposPedido): Promise<Pedido>
  pedido(id: string): Promise<Pedido | null>
  mudarLote(id: string, m: MudancaLote): Promise<Pedido>
  solicitarInteresse(id: string, opcao: IdOpcao): Promise<Pedido>
  andamento(id: string): Promise<Andamento | null>
  reservar(id: string): Promise<Cobranca>
  reserva(id: string): Promise<Cobranca | null>
  /** só no exemplo: faz de conta que o banco avisou o pagamento (no back-end, quem avisa é o banco) */
  pagarExemplo?(id: string): Promise<Cobranca>
}

// ---- guarda no navegador (sessão; e os pedidos, no exemplo) ----------------------------------------------------------

/** localStorage pode não existir (aba anônima, bloqueio): cai na memória e a tela continua funcionando */
function guarda() {
  const memoria = new Map<string, string>()
  return {
    ler(chave: string): string | null {
      try {
        return localStorage.getItem(chave)
      } catch {
        return memoria.get(chave) ?? null
      }
    },
    gravar(chave: string, valor: string | null) {
      try {
        if (valor === null) localStorage.removeItem(chave)
        else localStorage.setItem(chave, valor)
      } catch {
        if (valor === null) memoria.delete(chave)
        else memoria.set(chave, valor)
      }
    },
  }
}

const CHAVE_SESSAO = "raiz.sessao"

function sessaoGuardada(g: ReturnType<typeof guarda>): Sessao | null {
  try {
    const s = JSON.parse(g.ler(CHAVE_SESSAO) ?? "null") as Sessao | null
    return s?.token && s.email ? s : null
  } catch {
    return null
  }
}

// ---- API de verdade ---------------------------------------------------------------------------------------------------

export function fontePedidosApi(api: string): FontePedidos {
  const raiz = api.endsWith("/") ? api : api + "/"
  const g = guarda()
  async function pedir<T>(caminho: string, corpo?: unknown): Promise<T | null> {
    const s = sessaoGuardada(g)
    const r = await fetch(raiz + caminho, {
      method: corpo === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", ...(s ? { Authorization: `Bearer ${s.token}` } : {}) },
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    })
    if (r.status === 404) return null
    if (r.status === 401) {
      g.gravar(CHAVE_SESSAO, null)
      throw new Error("A sessão acabou. Entre de novo pelo link no e-mail.")
    }
    if (!r.ok) throw new Error(`${r.status} em ${caminho}`)
    return r.status === 204 ? (null as T) : ((await r.json()) as T)
  }
  const exigir = <T>(v: T | null, o_que: string): T => {
    if (v === null) throw new Error(`A API não respondeu ${o_que}`)
    return v
  }
  return {
    exemplo: false,
    sessao: () => sessaoGuardada(g),
    async entrar(email) {
      await pedir("entrar", { email })
      return { enviado: true }
    },
    async confirmar(token) {
      const s = exigir(await pedir<Sessao>("entrar/confirmar", { token }), "o link de entrada")
      g.gravar(CHAVE_SESSAO, JSON.stringify(s))
      return s
    },
    sair: () => g.gravar(CHAVE_SESSAO, null),
    listar: async () => (await pedir<ResumoPedido[]>("pedidos")) ?? [],
    criar: async (campos) => exigir(await pedir<Pedido>("pedidos", campos), "o pedido"),
    pedido: (id) => pedir<Pedido>(`pedidos/${encodeURIComponent(id)}`),
    mudarLote: async (id, m) => exigir(await pedir<Pedido>(`pedidos/${encodeURIComponent(id)}/lote`, m), "a mudança no lote"),
    solicitarInteresse: async (id, opcao) =>
      exigir(await pedir<Pedido>(`pedidos/${encodeURIComponent(id)}/solicitar-interesse`, { opcao }), "o pedido de interesse"),
    andamento: (id) => pedir<Andamento>(`pedidos/${encodeURIComponent(id)}/andamento`),
    reservar: async (id) => exigir(await pedir<Cobranca>(`pedidos/${encodeURIComponent(id)}/reservar`, {}), "a reserva"),
    reserva: (id) => pedir<Cobranca>(`pedidos/${encodeURIComponent(id)}/reserva`),
  }
}

// ---- resposta de exemplo, no navegador ------------------------------------------------------------------------------

const CHAVE_PEDIDOS = "raiz.exemplo.pedidos"

const aleatorio = (n: number) => {
  const b = new Uint8Array(n)
  crypto.getRandomValues(b)
  return [...b].map((x) => (x % 36).toString(36)).join("")
}

export function fontePedidosExemplo(fonte: FonteDeDados, agora: () => Date = () => new Date()): FontePedidos {
  const g = guarda()
  const onda = Number(g.ler("raiz.exemplo.onda_ms"))
  if (onda > 0) mudarOnda(onda)

  let candidatos: Promise<Candidato[]> | null = null
  /** fazendas aptas dos municípios que têm o contorno das fazendas no mapa */
  function carregarCandidatos(): Promise<Candidato[]> {
    candidatos ??= (async () => {
      const cods = await fonte.geo.comContorno()
      const listas = await Promise.all(
        cods.map(async (cod) => {
          const [imoveis, geo] = await Promise.all([fonte.imoveis(cod), fonte.geo.camada(cod, "imoveis")])
          const centro = new Map<string, [number, number]>()
          for (const f of geo?.features ?? []) {
            const p = pontoDentro(f.geometry)
            if (p) centro.set(String(f.properties.cod_imovel), p)
          }
          return (imoveis ?? []).map((i) => candidatoDe(i, centro.get(i.cod_imovel) ?? null)).filter((c): c is Candidato => !!c)
        }),
      )
      return listas.flat()
    })()
    candidatos.catch(() => (candidatos = null))
    return candidatos
  }

  const ler = (): Record<string, PedidoGuardado & { email: string }> => {
    try {
      return JSON.parse(g.ler(CHAVE_PEDIDOS) ?? "{}")
    } catch {
      return {}
    }
  }
  const gravar = (todos: Record<string, PedidoGuardado & { email: string }>) => g.gravar(CHAVE_PEDIDOS, JSON.stringify(todos))
  const meu = (id: string) => {
    const s = sessaoGuardada(g)
    const p = ler()[id]
    return s && p && p.email === s.email ? p : null
  }
  async function dadosAgora(): Promise<Record<string, string>> {
    const e = await fonte.estados()
    return Object.fromEntries(e.estados.filter((x) => x.atualizado_em).map((x) => [x.uf, x.atualizado_em!]))
  }
  async function montar(p: PedidoGuardado): Promise<Pedido> {
    return montarPedido(p, await carregarCandidatos(), agora(), await dadosAgora())
  }
  const exigirSessao = () => {
    const s = sessaoGuardada(g)
    if (!s) throw new Error("Entre para ver seus pedidos.")
    return s
  }

  return {
    exemplo: true,
    sessao: () => sessaoGuardada(g),
    async entrar(email) {
      // sem back-end não há e-mail: o link vem na resposta, para abrir direto
      return { enviado: true, link_exemplo: `#/entrar/${aleatorio(6)}.${btoa(encodeURIComponent(email.trim().toLowerCase())).replace(/=+$/, "")}` }
    },
    async confirmar(token) {
      const [, codigo] = token.split(".")
      const email = codigo ? decodeURIComponent(atob(codigo)) : ""
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) throw new Error("Este link de entrada não vale. Peça outro.")
      const s = { token: aleatorio(24), email }
      g.gravar(CHAVE_SESSAO, JSON.stringify(s))
      return s
    },
    sair: () => g.gravar(CHAVE_SESSAO, null),
    async listar() {
      const s = exigirSessao()
      const meus = Object.values(ler()).filter((p) => p.email === s.email)
      const pedidos = await Promise.all(meus.map((p) => montar(p)))
      const cands = await carregarCandidatos()
      return pedidos
        .map((p): ResumoPedido => {
          const g2 = meus.find((m) => m.id === p.id)!
          const opcao = p.opcoes.find((o) => o.id === p.opcao_escolhida)
          const a = g2.solicitado && opcao ? simularAndamento(g2, opcao, cands, p.campos, agora()) : null
          return {
            id: p.id,
            criado_em: p.criado_em,
            titulo: tituloDoPedido(p.campos),
            status: p.status,
            reservado_ate: p.reservado_ate,
            com_interesse: a ? Math.min(1, a.com_interessado / Math.max(1, a.meta)) : null,
            alertas: p.alertas.length,
          }
        })
        .sort((a, b) => b.criado_em.localeCompare(a.criado_em))
    },
    async criar(campos) {
      const s = exigirSessao()
      const id = aleatorio(8)
      const p: PedidoGuardado & { email: string } = {
        id,
        criado_em: agora().toISOString(),
        campos,
        edicoes: {},
        solicitado: null,
        reserva: null,
        dados_de: await dadosAgora(),
        email: s.email,
      }
      gravar({ ...ler(), [id]: p })
      return montar(p)
    },
    async pedido(id) {
      exigirSessao()
      const p = meu(id)
      return p ? montar(p) : null
    },
    async mudarLote(id, m) {
      const p = meu(id)
      if (!p) throw new Error("Pedido não encontrado.")
      if (p.solicitado) throw new Error("A busca de interesse já começou: o lote não muda mais por aqui.")
      const ed = p.edicoes[m.opcao] ?? { tiradas: [], trocas: [] }
      if (m.acao === "tirar") ed.tiradas = [...new Set([...ed.tiradas, m.cod_imovel])]
      else {
        const atual = await montar(p)
        const reservas = atual.opcoes.find((o) => o.id === m.opcao)?.itens.filter((i) => i.papel === "reserva") ?? []
        const entra = m.por ?? reservas[0]?.cod_imovel
        if (!entra) throw new Error("Não há fazenda de reserva para trocar.")
        ed.trocas = [...ed.trocas.filter((t) => t.sai !== m.cod_imovel), { sai: m.cod_imovel, entra }]
      }
      p.edicoes[m.opcao] = ed
      gravar({ ...ler(), [id]: p })
      return montar(p)
    },
    async solicitarInteresse(id, opcao) {
      const p = meu(id)
      if (!p) throw new Error("Pedido não encontrado.")
      if (!IDS_OPCOES.includes(opcao)) throw new Error("Opção desconhecida.")
      p.solicitado ??= { opcao, em: agora().toISOString() }
      gravar({ ...ler(), [id]: p })
      return montar(p)
    },
    andamento,
    async reservar(id) {
      const p = meu(id)
      if (!p) throw new Error("Pedido não encontrado.")
      const a = await andamento(id)
      if (!a || !a.grupo_pronto_em) throw new Error("O grupo ainda não fechou.")
      if (!p.reserva) {
        const c = cobrancaDe(p, await hectaresDoGrupo(a))
        p.reserva = { criada_em: agora().toISOString(), pago_em: null, valor_brl: c.valor_brl, hectares: c.hectares }
      }
      gravar({ ...ler(), [id]: p })
      return cobrancaDe(p, await hectaresDoGrupo(a))
    },
    async reserva(id) {
      const p = meu(id)
      if (!p) return null
      const a = await andamento(id)
      // antes de pedir a reserva, só o valor e o prazo (sem o Pix)
      if (!p.reserva && !a?.grupo_pronto_em) return null
      return cobrancaDe(p, a ? await hectaresDoGrupo(a) : 0)
    },
    async pagarExemplo(id) {
      const p = meu(id)
      if (!p?.reserva) throw new Error("Abra a reserva antes.")
      p.reserva.pago_em ??= agora().toISOString()
      gravar({ ...ler(), [id]: p })
      const a = await andamento(id)
      return cobrancaDe(p, a ? await hectaresDoGrupo(a) : 0)
    },
  }

  async function andamento(id: string): Promise<Andamento | null> {
    const p = meu(id)
    if (!p?.solicitado) return null
    const pedido = await montar(p)
    const opcao = pedido.opcoes.find((o) => o.id === p.solicitado!.opcao)!
    const a = simularAndamento(p, opcao, await carregarCandidatos(), p.campos, agora())
    return { ...a, status: pedido.status === "reservado" || pedido.status === "reserva_vencida" ? pedido.status : a.status }
  }

  async function hectaresDoGrupo(a: Andamento): Promise<number> {
    const grupo = new Set(grupoDe(a))
    return a.fazendas.filter((f) => grupo.has(f.cod_imovel)).reduce((s, f) => s + f.hectares, 0)
  }
}

/** Resumo do cenário do Release. Guarda só critérios de consulta; nunca simula contato, reserva ou pagamento. */
export function fontePedidosRelease(base: string, fonte: FonteDeDados, agora: () => Date = () => new Date()): FontePedidos {
  const g = guarda()
  const chave = "raiz.consultas.release.v1"
  const raiz = base.endsWith("/") ? base : base + "/"
  type Consulta = { id: string; criado_em: string; campos: CamposPedido }
  const ler = (): Record<string, Consulta> => {
    try { return JSON.parse(g.ler(chave) ?? "{}") } catch { return {} }
  }
  const bloquear = async (): Promise<never> => { throw new Error("Esta consulta pública não inicia contato nem reserva. Essa etapa ficará para a fase final, na área autenticada.") }
  async function montar(c: Consulta): Promise<Pedido> {
    const resposta = await fetch(`${raiz}amostra/lote_PA_central_r11.json`)
    if (!resposta.ok) throw new Error("Não foi possível ler a publicação dos lotes. Tente novamente.")
    const publicacao = lerPublicacaoLote(await resposta.json())
    if (publicacao.estado === "ausente") {
      const municipios = (await fonte.municipios()).filter((m) => (!c.campos.onde.ufs.length || c.campos.onde.ufs.includes(m.uf)) && (!c.campos.onde.municipios.length || c.campos.onde.municipios.includes(m.cod_ibge)))
      const somaCompleta = (coluna: string): number | null => {
        let soma = 0
        for (const m of municipios) {
          const linha = m.linha ?? {}
          const valor = num(linha, coluna)
          if (bool(linha, "dados_suprimidos") === true || valor === null) return null
          soma += valor
        }
        return soma
      }
      const fazendas = somaCompleta("imoveis"), hectares = somaCompleta("ha_carbono")
      publicacao.cobertura = {
        municipios: municipios.length,
        estados: new Set(municipios.map((m) => m.uf)).size,
        fazendas, hectares,
        ...(fazendas === null || hectares === null ? { observacao: "O total não está disponível: há municípios com dados suprimidos ou valores ainda não publicados. As contagens de municípios e estados permanecem conhecidas." } : {}),
      }
    }
    return {
      ...c, status: "lote_montado", publicacao,
      // Compatibilidade do envelope da API. A UI pública usa exclusivamente publicacao (nulos são desconhecidos).
      base: { fazendas: 0, hectares: 0, creditos: { p10: 0, p50: 0, p90: 0 }, por_caminho: [], por_interesse: [], alcanca_meta: false, falta: 0, afrouxar: [], observacao: publicacao.aviso },
      opcoes: [], opcao_escolhida: null, reservado_ate: null, alertas: [],
      versao_modelo: publicacao.modelo_versao ?? "aguardando-publicacao", exemplo: false,
    }
  }
  return {
    exemplo: false, publica: true, sessao: () => null, sair: () => {}, entrar: bloquear, confirmar: bloquear,
    listar: async () => Object.values(ler()).map((c) => ({ id: c.id, criado_em: c.criado_em, titulo: tituloDoPedido(c.campos), status: "lote_montado", reservado_ate: null, com_interesse: null, alertas: 0 })),
    async criar(campos) {
      const c = { id: aleatorio(10), criado_em: agora().toISOString(), campos }
      const p = await montar(c)
      g.gravar(chave, JSON.stringify({ ...ler(), [c.id]: c }))
      return p
    },
    async pedido(id) { const c = ler()[id]; return c ? montar(c) : null },
    mudarLote: bloquear, solicitarInteresse: bloquear, andamento: async () => null, reservar: bloquear, reserva: async () => null,
  }
}

/** Com API, o solver autenticado; sem ela, somente os números publicados no Release. */
export function escolherFontePedidos(env: { VITE_RAIZ_API?: string; VITE_RAIZ_DADOS_BASE?: string; BASE_URL?: string }, fonte: FonteDeDados): FontePedidos {
  return env.VITE_RAIZ_API ? fontePedidosApi(env.VITE_RAIZ_API) : fontePedidosRelease(env.VITE_RAIZ_DADOS_BASE || env.BASE_URL || "/", fonte)
}

export { CAMPOS_PADRAO }
