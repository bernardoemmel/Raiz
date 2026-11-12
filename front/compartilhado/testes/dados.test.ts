import fs from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"
import { caixaDeFatos } from "../cenario"
import { camposDeFutebol, fraseIndice, frasePosicao } from "../comparacoes"
import { complementosDe, juntarComplementos } from "../dados/complementos"
import { escreverCsv, lerCsv } from "../dados/csv"
import { lerFicha, montarFicha } from "../dados/ficha"
import { funilDosImoveis, lerFunil, lerImovel } from "../dados/funil"
import { abreviarCar, fmtCompacto, fmtHa, fmtInt } from "../formato"
import { codificar, decodificar } from "../polyline"
import { colunaPessoal, mascarar } from "../privacidade"

const AMOSTRA = path.resolve(__dirname, "../../../dados/amostra")
const ler = (arq: string) => lerCsv(fs.readFileSync(path.join(AMOSTRA, arq), "utf8")).linhas

const carregar = (cod: string) => {
  const nomes = complementosDe(fs.readdirSync(AMOSTRA), cod)
  const { porImovel, avisos } = juntarComplementos(nomes.map((arquivo) => ({ arquivo, linhas: ler(arquivo) })))
  return { nomes, avisos, imoveis: ler(`imoveis_${cod}.csv`).map((l) => lerImovel(l, porImovel.get(l.cod_imovel))) }
}

describe("funil igual ao do motor", () => {
  const { imoveis } = carregar("1504950")
  const resumo = ler("resumo_PA.csv").find((l) => l.cod_ibge === "1504950")!

  for (const [cod, nome] of [
    ["1504950", "Nova Esperança do Piriá"],
    ["1507300", "São Félix do Xingu"],
  ])
    it(`a soma dos imóveis de ${nome} bate com o resumo_PA.csv`, () => {
      const lista = cod === "1504950" ? imoveis : carregar(cod).imoveis
      const meu = funilDosImoveis(lista, cod, nome, "PA")
      const motor = lerFunil(ler("resumo_PA.csv").find((l) => l.cod_ibge === cod)!, "PA")
      for (const k of [
        "imoveis",
        "sem_problema",
        "aptas_carbono",
        "ha_carbono",
        "tco2_ano_aptas",
        "aptas_com_matricula",
        "ha_carbono_matricula",
        "para_agrupar",
      ] as const)
        expect(meu[k], k).toBe(motor[k])
    })

  it("junta todo arquivo de uma linha por imóvel, inclusive extras_direto_, e deixa certidoes_ de fora", () => {
    const { nomes, avisos } = carregar("1504950")
    expect(nomes).toEqual(["direto_1504950.csv", "extras_1504950.csv", "extras_direto_1504950.csv", "filtros_1504950.csv", "mapbiomas_1504950.csv"])
    expect(avisos).toEqual([])
    expect(resumo).toBeDefined()
  })

  it("lê fogo, TMF, causa da perda e o ano mais recente do MapBiomas", () => {
    const com = imoveis.filter((i) => i.tmf_classe !== null && i.causa_perda !== null && i.fogo_anos_max !== null)
    expect(com.length).toBeGreaterThan(800)
    expect(imoveis.every((i) => i.mb_ano === null || i.mb_ano === 2025)).toBe(true)
    expect(imoveis.some((i) => (i.mb_fogo_ha ?? 0) > 0)).toBe(true)
    const novo = lerImovel({ ...imoveis[0].linha, mb_fogo_2026_ha: "12.5", mb_fogo_mes_principal_2026: "9.0" })
    expect([novo.mb_ano, novo.mb_fogo_ha, novo.mb_fogo_mes]).toEqual([2026, 12.5, 9])
  })

  it("lê pelo nome e tolera coluna nova, coluna faltando e ordem trocada", () => {
    const l = { ...ler("imoveis_1504950.csv")[5], coluna_que_o_motor_criou_amanha: "42" }
    delete (l as Record<string, string>).cacau_aptidao
    const csv = escreverCsv(Object.keys(l).reverse(), [l])
    const i = lerImovel(lerCsv(csv).linhas[0])
    expect(i.cod_imovel).toBe(l.cod_imovel)
    expect(i.ha).toBeCloseTo(Number(l.ha))
    expect(i.cacau_aptidao).toBeNull()
    expect(i.linha.coluna_que_o_motor_criou_amanha).toBe("42")
  })

  it("junta as colunas de filtros_<mun>.csv (uma fazenda com bloqueio territorial)", () => {
    expect(imoveis.filter((i) => i.filtro_territorial === "bloqueio")).toHaveLength(1)
  })
})

describe("privacidade", () => {
  it("mascara CPF e CNPJ, formatados ou não, e não estraga números comuns nem o código do CAR", () => {
    expect(mascarar("dono 123.456.789-09")).toBe("dono ***.456.789-**")
    expect(mascarar("CNPJ 11.222.333/0001-81")).toBe("CNPJ **.222.333/****-**")
    expect(mascarar("12345678909")).toBe("***.456.789-**")
    expect(mascarar("área 189.99087022873272")).toBe("área 189.99087022873272")
    const car = "PA-1504950-00162AB1E0B34E339E65946061393F10"
    expect(mascarar(car)).toBe(car)
  })
  it("tira colunas pessoais e deixa nomes de lugar", () => {
    expect(colunaPessoal("nome_proprietario")).toBe(true)
    expect(colunaPessoal("cpf_cnpj")).toBe(true)
    expect(colunaPessoal("municipio")).toBe(false)
    expect(colunaPessoal("nome_ti")).toBe(false)
    const i = lerImovel({ ...ler("imoveis_1504950.csv")[0], nome_proprietario: "Fulano", cpf: "123.456.789-09" })
    expect(i.linha.nome_proprietario).toBeUndefined()
    expect(i.linha.cpf).toBeUndefined()
  })
  it("nenhum arquivo da amostra tem CPF ou CNPJ", () => {
    for (const f of fs.readdirSync(AMOSTRA)) {
      const t = fs.readFileSync(path.join(AMOSTRA, f), "utf8")
      expect(mascarar(t) === t, f).toBe(true)
    }
  })
})

describe("formatos e comparações", () => {
  it("formata no jeito brasileiro", () => {
    expect(fmtInt(9703)).toBe("9.703")
    expect(fmtHa(4.31)).toBe("4,3 ha")
    expect(fmtCompacto(15_900)).toBe("15,9 mil")
    expect(fmtCompacto(4_226_631)).toBe("4,2 milhões")
    expect(abreviarCar("PA-1507300-F293C0B5E1E44B5E9AA0AAC1B5FE")).toBe("PA-1507300-F293…B5FE")
  })
  it("compara com campos de futebol e com o município", () => {
    expect(camposDeFutebol(28.6)).toBe("são 40 campos de futebol")
    expect(fraseIndice(200, 100, "média do município")).toBe("cerca do dobro da média do município")
    expect(fraseIndice(100, 100, "média do município")).toBe("quase igual à média do município")
    expect(fraseIndice(50, 100, "média do município")).toBe("cerca da metade da média do município")
    const todos = Array.from({ length: 100 }, (_, i) => i)
    expect(frasePosicao(95, todos, "X")).toBe("maior que 9 de cada 10 imóveis de X")
    expect(frasePosicao(50, todos, "X")).toBeNull()
  })
})

describe("ficha e caixa de fatos", () => {
  const imoveis = ler("imoveis_1504950.csv").map((l) => lerImovel(l))
  const alvo = imoveis.filter((i) => i.com_matricula).sort((a, b) => b.carbono_ha - a.carbono_ha)[0]

  it("caixa de fatos: base de 100 ha, 'não fazer nada' sem carbono e a área se conserva", () => {
    const c = caixaDeFatos(alvo)
    const flo = c.linhas.find((l) => l.id === "floresta")!
    const abe = c.linhas.find((l) => l.id === "aberta")!
    const car = c.linhas.find((l) => l.id === "carbono")!
    expect(car.nada).toBe(0)
    expect(car.restaurar).toBeGreaterThan(0)
    expect(flo.restaurar + abe.restaurar).toBeCloseTo(flo.nada + abe.nada)
    expect(flo.nada + abe.nada).toBeLessThanOrEqual(100.5)
  })

  it("polyline vai e volta com 6 casas", () => {
    const anel: [number, number][] = [
      [-46.893083, -2.343303],
      [-46.896241, -2.343393],
      [-46.902049, -2.345751],
      [-46.893083, -2.343303],
    ]
    expect(decodificar(codificar(anel))).toEqual(anel)
  })

  it("a ficha em JSON reconstrói o mesmo imóvel", () => {
    const f = lerFicha(JSON.parse(JSON.stringify(montarFicha(alvo, imoveis))))
    expect(f.imovel.carbono_ha).toBeCloseTo(alvo.carbono_ha)
    expect(f.imovel.categoria).toBe(alvo.categoria)
    expect(f.contexto.n_imoveis).toBe(880)
    expect(f.contexto.posicao_carbono).toBeGreaterThan(0.9)
  })
})

describe("título e motivos", async () => {
  const { situacaoTitulo } = await import("../titulo")
  const { motivos } = await import("../motivos")
  const filtros = new Map(ler("filtros_1504950.csv").map((l) => [l.cod_imovel, l]))
  const imoveis = ler("imoveis_1504950.csv").map((l) => lerImovel(l, [filtros.get(l.cod_imovel) ?? {}]))

  it("toda matrícula do SIGEF leva o selo 'matrícula a conferir' até alguém conferir", () => {
    const comMat = imoveis.filter((i) => i.f_matricula >= 0.5)
    expect(comMat.length).toBeGreaterThan(0)
    for (const i of comMat) expect(situacaoTitulo(i).selo).toBe("matricula_a_conferir")
    const conferida = lerImovel({ ...comMat[0].linha, matricula_conferida: "True" })
    expect(situacaoTitulo(conferida).selo).toBe("matricula_conferida")
    const semNada = imoveis.find((i) => i.f_matricula === 0 && !i.assentamento)!
    expect(situacaoTitulo(semNada).selo).toBe("sem_matricula")
  })

  it("toda fazenda fora do funil tem pelo menos um motivo que bloqueia, e toda apta nenhum", () => {
    for (const i of imoveis) {
      const bloqueios = motivos(i).filter((m) => m.bloqueia && !m.ok)
      if (i.apta) expect(bloqueios, i.cod_imovel).toHaveLength(0)
      else expect(bloqueios.length, i.cod_imovel).toBeGreaterThan(0)
    }
  })
})
