import { describe, expect, it, vi } from "vitest"
import { codigosEmLeilao, filtrarEventos, fonteCalendario, hojeNoBrasil, lerAgenda, linkPublico, normalizarCar, type Evento } from "../calendario"
import { lerRota } from "../../globo/src/rota"

const CAR = `PA-1504950-${"A".repeat(32)}`
const evento: Evento = {
  id: "a".repeat(24), tipo: "leilao_imovel", titulo: "Leilão de imóvel rural", data: "2026-11-15", prazo: null,
  uf: "PA", municipio: "1504950", codigos_car: [CAR], fonte_url: "https://www.in.gov.br/edital", fonte_nome: "DOU",
  coletado_em: "2026-11-12T10:00:00Z", confianca: 0.9, situacao: "previsto",
}
const envelope = (eventos = [evento]) => ({ eventos, total: eventos.length, coletado_em: evento.coletado_em, fontes: [] })
const resposta = (valor: unknown) => new Response(JSON.stringify(valor), { headers: { "content-type": "application/json" } })

describe("calendário público", () => {
  it("abre a aba e usa a data de São Paulo mesmo depois da meia-noite UTC", () => {
    expect(lerRota("#/calendario")).toEqual({ tela: "calendario" })
    expect(lerRota(`#/calendario/${CAR}`)).toEqual({ tela: "calendario", car: CAR })
    expect(hojeNoBrasil(new Date("2026-11-13T01:00:00Z"))).toBe("2026-11-12")
  })
  it("filtra pelo prazo, estado, tipo e CAR, em ordem cronológica", () => {
    const a = { ...evento, id: "prazo", data: "2026-12-01", prazo: "2026-11-14" }
    expect(filtrarEventos([evento, a], { estado: "PA", inicio: "2026-11-14", fim: "2026-11-14", cod_imovel: CAR })).toEqual([a])
    expect(filtrarEventos([evento], { tipo: "verra" })).toEqual([])
    expect(filtrarEventos([evento], { estado: "MT" })).toEqual([])
    expect(filtrarEventos([{ ...evento, uf: null }], { estado: "MT" })).toHaveLength(1)
    expect(filtrarEventos([evento], { cod_imovel: CAR.toLowerCase().replace(/(.{4})$/, ".$1") })).toHaveLength(1)
  })
  it("só marca leilões previstos que ainda não passaram; cancelamento, adiamento e penhora não viram leilão", () => {
    const todos = [evento, { ...evento, id: "cancelado", situacao: "cancelado" as const, codigos_car: ["cancelado"] }, { ...evento, id: "adiado", situacao: "adiado" as const, codigos_car: ["adiado"] }, { ...evento, id: "penhora", tipo: "penhora" as const, codigos_car: ["penhora"] }]
    expect([...codigosEmLeilao(todos, "2026-11-15")]).toEqual([normalizarCar(CAR)])
    expect([...codigosEmLeilao(todos, "2026-11-16")]).toEqual([])
  })
  it("mantém o leilão marcado até o prazo futuro de propostas ou inscrições", () => {
    const emAndamento = { ...evento, data: "2026-11-10", prazo: "2026-11-15" }
    expect([...codigosEmLeilao([emAndamento], "2026-11-12")]).toEqual([normalizarCar(CAR)])
    expect([...codigosEmLeilao([emAndamento], "2026-11-16")]).toEqual([])
  })
  it("reconstrói rótulos oficiais e não usa texto livre ou contato do snapshot", () => {
    const pessoal = "Pessoa Particular; pessoa@example.invalid; (11) 91234-5678"
    const a = lerAgenda({
      ...envelope(), coletado_em: pessoal,
      eventos: [{ ...evento, titulo: pessoal, fonte_id: "dou", fonte_nome: pessoal, referencia: pessoal, marco: "constructor", coletado_em: pessoal, fonte_url: "https://www.in.gov.br/?contato=pessoa%40example.invalid" }],
      fontes: [{ id: "dou", nome: pessoal, erro: pessoal, situacao: pessoal, coletado_em: pessoal }],
    })
    expect(JSON.stringify(a)).not.toMatch(/Particular|pessoa@|91234/)
    expect(a.eventos[0].titulo).toBe("Leilão de imóvel rural: data do evento")
    expect(a.eventos[0].fonte_nome).toBe("Diário Oficial da União")
    expect(a.eventos[0].fonte_url).toBeNull()
    expect(a.fontes[0].situacao).toBe("desconhecida")
    expect(lerAgenda(envelope([{ ...evento, id: pessoal }])).eventos).toEqual([])
    expect(linkPublico("https://example.invalid/edital")).toBeNull()
    expect(linkPublico("https://www.in.gov.br/edital#pessoa-particular")).toBe("https://www.in.gov.br/edital")
  })
  it("descarta campos pessoais, mascara identificadores e rejeita links executáveis", () => {
    const cpf = ["123", "456", "789", "00"].join(".").replace(/\.(\d{2})$/, "-$1")
    const a = lerAgenda(envelope([{ ...evento, titulo: `Edital ${cpf}`, fonte_url: "javascript:alert(1)", titular: "Não publicar", codigos_car: [CAR, cpf] } as Evento]))
    expect(a.eventos[0].titulo).not.toContain(cpf)
    expect(a.eventos[0]).not.toHaveProperty("titular")
    expect(a.eventos[0].fonte_url).toBeNull()
    expect(a.eventos[0].codigos_car).toEqual([CAR])
    expect(linkPublico(`https://www.in.gov.br/?cpf=${encodeURIComponent(cpf)}`)).toBeNull()
    expect(linkPublico("https://usuario:senha@www.in.gov.br/edital")).toBeNull()
  })
  it("ausência de snapshot e HTML de fallback não são agenda vazia confirmada", async () => {
    for (const r of [new Response("", { status: 404 }), new Response("<html>Raíz</html>", { headers: { "content-type": "text/html" } })]) {
      const fonte = fonteCalendario({ base: "/Raiz/" }, vi.fn().mockResolvedValue(r))
      expect((await fonte.listar()).disponivel).toBe(false)
    }
  })
  it("filtra e pagina o snapshot, com feed completo, sem consultar a rede a cada filtro", async () => {
    const buscar = vi.fn().mockResolvedValue(resposta(envelope([evento, { ...evento, id: "b".repeat(24), uf: "MT" }])))
    const fonte = fonteCalendario({ base: "/Raiz/" }, buscar)
    expect((await fonte.listar({ estado: "PA" })).total).toBe(1)
    expect((await fonte.listar({}, 1, 1)).eventos[0].id).toBe("b".repeat(24))
    expect(buscar).toHaveBeenCalledTimes(1)
    expect(fonte.feed()).toBe("/Raiz/calendario/eventos.ics")
  })
  it("consulta todas as páginas de leilões e mantém o token no cabeçalho, nunca no feed", async () => {
    const buscar = vi.fn().mockResolvedValueOnce(resposta({ ...envelope(), total: 2 })).mockResolvedValueOnce(resposta({ ...envelope([{ ...evento, id: "b".repeat(24) }]), total: 2 }))
    const fonte = fonteCalendario({ api: "https://api.example.test/", token: "teste" }, buscar)
    expect((await fonte.leiloes({ estado: "PA" })).eventos).toHaveLength(2)
    expect(buscar.mock.calls[1][0]).toContain("deslocamento=1")
    expect(buscar.mock.calls[0][1].headers).toEqual({ Authorization: "Bearer teste" })
    expect(fonte.feed({ tipo: "verra" })).toBe("https://api.example.test/eventos.ics?tipo=verra")
  })
})
