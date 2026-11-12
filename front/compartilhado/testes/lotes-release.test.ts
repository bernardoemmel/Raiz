import { afterEach, describe, expect, it, vi } from "vitest"
import type { FonteDeDados } from "../dados/fonte"
import type { FunilMunicipio } from "../dados/tipos"
import { CAMPOS_PADRAO } from "../pedidos/exemplo"
import { escolherFontePedidos, fontePedidosRelease } from "../pedidos/fonte-pedidos"
import { lerPublicacaoLote, projetarPublicacaoLote } from "../pedidos/release"

/** Estrutura real de raiz/restauracao_rodada.py; números pequenos identificam este teste sintético. */
function manifesto() {
  const resumo = {
    data: "2026-11-12", volume_creditos: 1000000, preco_contrato_usd: 55,
    titulares: 3, reservas: 2, pequenas: 4, ha_lote: 40,
    creditos_lote_faixa: { p10: 10, p50: 20, p90: 40 },
    faixa: { carteira: { p10: 12, p50: 21, p90: 32 } },
    custo_credito_usd_medio: 17,
    // Esta média não é a TIR do fluxo do lote. Não usá-la para substituir o fluxo ausente.
    tir_fazendas_media_pct: 91,
    economia: { tir_alavancada_pct: 13.2 },
    oferta: { fazendas: 30, ha: 600, fazendas_terra_pronta: 10, creditos_terra_pronta: 70 },
    certidoes: { certidoes_a_pedir: 2, fazendas_a_pedir: 1, ha_cobertos: 12, por_caminho: { matricula_a_conferir: { fazendas: 2, ha: 15 } }, pedir: ["CAR-PRIVADO"] },
    em_espera: { fazendas: 4, ha: 100, por_regularizacao: { falta_georreferenciamento: { fazendas: 3, ha: 70, creditos: 11 } } },
    // A mesma fazenda pode constar nas duas linhas. São potenciais retidos, não ganhos somáveis.
    o_que_destrava: [
      { pendencia: "jurisdicional_a_conferir", fazendas: 4, ha: 100, creditos: { p10: 4, p50: 10, p90: 14 }, somavel: false },
      { pendencia: "clpi", fazendas: 4, ha: 100, creditos: { p10: 4, p50: 10, p90: 14 }, somavel: false },
    ],
    o_que_falta: ["Conferir as certidões."],
    folha_proprietario: "PESSOA-PRIVADA", matriculas: ["MATRICULA-PRIVADA"],
  }
  return {
    uf: "PA", cenario: "central_r11", modelo_versao: "modelo-teste", publicado_em: "2026-11-12T18:00:00Z",
    municipios_calculados: 144, imoveis_calculados: 350000,
    resumos: { barata: resumo, segura: resumo, compacta: resumo },
    arquivos: { pacote: { url: "https://exemplo.invalid/FOLHAS-PRIVADAS.tar.gz" } },
  }
}

afterEach(() => vi.unstubAllGlobals())

describe("publicação dos três lotes", () => {
  it("mantém ausência desconhecida, sem quantis ou TIR inventados", () => {
    const p = projetarPublicacaoLote(null)
    expect(p.estado).toBe("ausente")
    expect(p.opcoes).toEqual([])
    expect(p.base.creditos).toEqual({ p10: null, p50: null, p90: null })
    expect(p.base.fazendas).toBeNull()
    expect(p.pedido_recalculado).toBe(false)
  })

  it("lê o contrato imutável da rodada e separa quantis de carteira, TIR de fluxo e base", () => {
    const p = projetarPublicacaoLote(manifesto())
    expect(p.estado).toBe("publicado")
    expect(p.atualizado_em).toBe("2026-11-12T18:00:00Z")
    expect(p.opcoes.map((o) => o.id)).toEqual(["barata", "segura", "compacta"])
    expect(p.opcoes[0]).toMatchObject({ creditos: { p10: 12, p50: 21, p90: 32 }, tir_p50: .132, fazendas: 5, pequenas: 4, hectares: 40, reservas: 2 })
    expect(p.base).toMatchObject({ fazendas: 10, hectares: null, creditos: { p10: null, p50: 70, p90: null } })
    expect(p.opcoes[0].destrava).toEqual([
      { tipo: "salvaguarda", texto: "Comprovar ausência de sobreposição ou exclusão do programa jurisdicional.", fazendas: 4, hectares: 100, creditos: null, creditos_faixa: { p10: 4, p50: 10, p90: 14 }, somavel: false },
      { tipo: "salvaguarda", texto: "Comprovar consentimento em consulta livre, prévia e informada, custeada pelo desenvolvedor.", fazendas: 4, hectares: 100, creditos: null, creditos_faixa: { p10: 4, p50: 10, p90: 14 }, somavel: false },
      { tipo: "regularizacao", texto: "Concluir o georreferenciamento certificado.", fazendas: 3, hectares: 70, creditos: 11, creditos_faixa: null, somavel: false },
      { tipo: "certidao", texto: "Pedir 2 certidões e conferir a cadeia da terra.", fazendas: 1, hectares: 12, creditos: null, creditos_faixa: null, somavel: false },
    ])
    expect(JSON.stringify(p)).not.toMatch(/PRIVAD|matriculas|folha_proprietario|\.tar\.gz/)
  })

  it("não troca TIR ausente pela média das fazendas nem null por zero", () => {
    const m = manifesto()
    m.resumos.barata.economia = { tir_alavancada_pct: null as unknown as number }
    const p = projetarPublicacaoLote(m)
    expect(p.opcoes[0].tir_p50).toBeNull()
    m.resumos.barata.economia = { tir_alavancada_pct: 0 }
    expect(projetarPublicacaoLote(m).opcoes[0].tir_p50).toBe(0)
  })

  it("rejeita um conjunto incompleto ou cenário diferente e ignora campos futuros", () => {
    const m = manifesto()
    delete (m.resumos as Partial<typeof m.resumos>).segura
    expect(projetarPublicacaoLote(m).estado).toBe("ausente")
    expect(projetarPublicacaoLote({ ...manifesto(), cenario: "outro" }).estado).toBe("ausente")
    const p = projetarPublicacaoLote(manifesto())
    expect(lerPublicacaoLote({ ...p, dono: "PRIVADO", arquivos: ["PRIVADO"] })).toEqual(p)
    expect(lerPublicacaoLote({ ...p, opcoes: [p.opcoes[0], p.opcoes[0], p.opcoes[2]] }).estado).toBe("ausente")
  })
})

describe("consulta estática aos lotes", () => {
  const campos = { ...CAMPOS_PADRAO, onde: { ...CAMPOS_PADRAO.onde, ufs: ["PA"] } }
  const fonte = () => ({ municipios: vi.fn(async () => [
    { uf: "PA", cod_ibge: "1505536", imoveis: 7, ha_carbono: 20, linha: { imoveis: "7", ha_carbono: "20", dados_suprimidos: "false" } },
    { uf: "TO", cod_ibge: "1721000", imoveis: 100, ha_carbono: 1000, linha: { imoveis: "100", ha_carbono: "1000", dados_suprimidos: "false" } },
  ] as FunilMunicipio[]) }) as unknown as FonteDeDados

  it("abre sem login fictício, lê o arquivo com subcaminho e só soma a cobertura territorial real", async () => {
    const buscar = vi.fn(async () => new Response(JSON.stringify(projetarPublicacaoLote(null)), { headers: { "content-type": "application/json" } }))
    vi.stubGlobal("fetch", buscar)
    const f = fontePedidosRelease("/Raiz/", fonte())
    expect(f.publica).toBe(true)
    expect(f.sessao()).toBeNull()
    const p = await f.criar(campos)
    expect(buscar).toHaveBeenCalledWith("/Raiz/amostra/lote_PA_central_r11.json")
    expect(p.publicacao?.cobertura).toEqual({ municipios: 1, estados: 1, fazendas: 7, hectares: 20 })
    expect(p.publicacao?.base.creditos.p50).toBeNull()
    expect(p.exemplo).toBe(false)
    expect(p.opcoes).toEqual([])
    expect((await f.pedido(p.id))?.campos).toEqual(campos)
    await expect(f.solicitarInteresse(p.id, "barata")).rejects.toThrow("fase final")
    await expect(f.reservar(p.id)).rejects.toThrow("fase final")
    await expect(f.entrar("pessoa@example.com")).rejects.toThrow("fase final")
  })

  it("seleciona o Release sem API e conserva o contrato autenticado quando configurado", () => {
    expect(escolherFontePedidos({ BASE_URL: "/" }, fonte()).publica).toBe(true)
    expect(escolherFontePedidos({ VITE_RAIZ_API: "https://api.exemplo/" }, fonte()).publica).not.toBe(true)
  })

  it.each([
    { linha: { imoveis: "", ha_carbono: "", dados_suprimidos: "true" }, esperado: { fazendas: null, hectares: null } },
    { linha: { imoveis: "", ha_carbono: "", dados_suprimidos: "false" }, esperado: { fazendas: null, hectares: null } },
    { linha: { imoveis: "8", dados_suprimidos: "false" }, esperado: { fazendas: 15, hectares: null } },
    { linha: { imoveis: "0", ha_carbono: "0", dados_suprimidos: "false" }, esperado: { fazendas: 7, hectares: 20 } },
  ])("não apresenta uma soma parcial como total nem ausência como zero: $linha", async ({ linha, esperado }) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(projetarPublicacaoLote(null)))))
    const original = fonte()
    const dados = await original.municipios()
    const f = fontePedidosRelease("/", { municipios: async () => [dados[0], { uf: "PA", cod_ibge: "1507300", imoveis: 0, ha_carbono: 0, linha } as FunilMunicipio] } as FonteDeDados)
    const p = await f.criar(campos)
    expect(p.publicacao?.cobertura).toMatchObject({ municipios: 2, estados: 1, ...esperado })
    if (esperado.fazendas === null || esperado.hectares === null) expect(p.publicacao?.cobertura.observacao).toContain("suprimidos")
  })
})
