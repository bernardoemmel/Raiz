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
    expect(nomes).toEqual(expect.arrayContaining(["desenvolvedor_1504950.csv", "direto_1504950.csv", "extras_1504950.csv", "extras_direto_1504950.csv", "filtros_1504950.csv", "mapbiomas_1504950.csv", "rebanho_1504950.csv", "regularizacao_1504950.csv", "terra_1504950.csv"]))
    expect(nomes.some((nome) => nome.startsWith("certidoes_"))).toBe(false)
    const novos = complementosDe([...nomes, "indicador_novo_1504950.csv", "certidoes_1504950.csv"], "1504950")
    expect(novos).toEqual(expect.arrayContaining([...nomes, "indicador_novo_1504950.csv"]))
    expect(novos.some((nome) => nome.startsWith("certidoes_"))).toBe(false)
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

// CPF e CNPJ de exemplo montados na hora: nenhum número aparece inteiro no repositório (a varredura de
// raiz/privacidade.py barra CPF/CNPJ escrito em qualquer arquivo do git)
const CPF_EX = ["123", "456", "789"].join("") + "09"
const CPF_EX_FMT = `${CPF_EX.slice(0, 3)}.${CPF_EX.slice(3, 6)}.${CPF_EX.slice(6, 9)}-${CPF_EX.slice(9)}`
const CNPJ_EX_FMT = ["11", "222", "333"].join(".") + "/" + ["0001", "81"].join("-")

describe("privacidade", () => {
  it("mascara CPF e CNPJ, formatados ou não, e não estraga números comuns nem o código do CAR", () => {
    expect(mascarar(`dono ${CPF_EX_FMT}`)).toBe("dono ***.456.789-**")
    expect(mascarar(`CNPJ ${CNPJ_EX_FMT}`)).toBe("CNPJ **.222.333/****-**")
    expect(mascarar(CPF_EX)).toBe("***.456.789-**")
    expect(mascarar("área 189.99087022873272")).toBe("área 189.99087022873272")
    const car = "PA-1504950-00162AB1E0B34E339E65946061393F10"
    expect(mascarar(car)).toBe(car)
  })
  it("tira colunas pessoais e deixa nomes de lugar", () => {
    expect(colunaPessoal("nome_proprietario")).toBe(true)
    expect(colunaPessoal("cpf_cnpj")).toBe(true)
    expect(colunaPessoal("municipio")).toBe(false)
    expect(colunaPessoal("nome_ti")).toBe(false)
    const i = lerImovel({ ...ler("imoveis_1504950.csv")[0], nome_proprietario: "Fulano", cpf: CPF_EX_FMT })
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
    expect(f.capa).toBeNull() // a amostra não tem foto de satélite
  })

  it("a capa (satélite com ThumbHash) só passa quando vem completa do back-end", () => {
    const base = JSON.parse(JSON.stringify(montarFicha(alvo, imoveis)))
    const capa = {
      caminho: "imoveis/PA15049500016/imagem/hoje-produtor.webp",
      thumbhash: "1QsOTaRxd3iAiHiIiIiHh3FwGPd4",
      largura: 720,
      altura: 540,
      data_cena: "2026-10-28",
      credito: "Contains modified Copernicus Sentinel data 2026",
    }
    expect(lerFicha({ ...base, capa }).capa).toEqual(capa)
    expect(lerFicha({ ...base, capa: { ...capa, thumbhash: "" } }).capa).toBeNull()
    expect(lerFicha({ ...base, capa: null }).capa).toBeNull()
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

describe("busca por código do CAR ou município (GET /busca?q=)", async () => {
  const { buscar, normalizarCar } = await import("../dados/busca")
  const imoveis = [...carregar("1504950").imoveis, ...carregar("1507300").imoveis]
  const municipios = ler("resumo_PA.csv").map((l) => lerFunil(l, "PA"))
  const base = { municipios, imoveis, comImoveis: new Set(["1504950", "1507300"]) }
  const SFX = "PA-1507300-F293CD17B5FE4D4682CB436FF5B136D0"

  it("acha o imóvel pelo código inteiro, em municípios diferentes", () => {
    for (const [cod, mun] of [
      ["PA-1504950-508C67099D164E0581650983A8CC2059", "Nova Esperança do Piriá"],
      [SFX, "São Félix do Xingu"],
      // código com o município de outro lugar, mas o imóvel está nestes municípios
      ["PA-1503077-1105FEC8081A45F48E16739A0035CC5E", "Nova Esperança do Piriá"],
      ["PA-1502764-9686458E866C455FBDF5E41D96D7A614", "São Félix do Xingu"],
      ["PA-1504208-B000CE16276348319BBA474ACFB35A67", "São Félix do Xingu"],
    ]) {
      const r = buscar(cod, base)
      expect(r.situacao, cod).toBe("ok")
      expect(r.imoveis.map((i) => i.cod_imovel)).toEqual([cod])
      expect(r.imoveis[0].municipio).toBe(mun)
    }
  })

  it("aceita o código como o recibo do CAR mostra (com pontos), em minúsculas e sem hífen", () => {
    expect(normalizarCar("pa-1507300-f293.cd17.b5fe.4d46.82cb.436f.f5b1.36d0")).toBe(SFX)
    expect(buscar("PA-1507300-F293.CD17.B5FE.4D46.82CB.436F.F5B1.36D0", base).imoveis[0]?.cod_imovel).toBe(SFX)
    expect(buscar("pa1507300f293cd17b5fe4d4682cb436ff5b136d0", base).imoveis[0]?.cod_imovel).toBe(SFX)
  })

  it("acha pelo começo do código, as maiores áreas aptas primeiro", () => {
    const r = buscar("PA-1507300-F29", base)
    expect(r.situacao).toBe("ok")
    expect(r.imoveis.map((i) => i.cod_imovel)).toContain(SFX)
    expect(buscar("PA-1507300", base).imoveis.length).toBe(8)
  })

  it("diz quando o município tem funil mas os imóveis ainda não foram processados (Altamira)", () => {
    const r = buscar("PA-1500602-70896562BFAF45BCA609AD3EBBE266F1", base)
    expect(r.situacao).toBe("municipio_sem_imoveis")
    expect(r.mensagem).toContain("Altamira")
    expect(r.municipios.map((m) => [m.cod_ibge, m.tem_imoveis])).toEqual([["1500602", false]])
  })

  it("diz quando o estado ainda não foi processado (Sinop, MT)", () => {
    const r = buscar("MT-5107909-530857C676404FCEB548A881C0ED8B8A", base)
    expect(r.situacao).toBe("estado_nao_processado")
    expect(r.mensagem).toContain("Mato Grosso")
    expect(r.mensagem).toContain("Pará")
  })

  it("diz quando o código não existe e quando o formato está errado", () => {
    const errado = SFX.slice(0, -1) + "1"
    const r = buscar(errado, base)
    expect(r.situacao).toBe("nao_encontrado")
    expect(r.mensagem).toContain("São Félix do Xingu")
    expect(buscar("PA-9999999-ABC", base).situacao).toBe("nao_encontrado")
    expect(buscar("XX-1507300", base).situacao).toBe("formato_invalido")
    expect(buscar("PA-1507300-ZZZ", base).situacao).toBe("formato_invalido")
    expect(buscar("PA-15", base).situacao).toBe("curta")
  })

  it("acha município pelo nome, sem acento, e diz quais têm lista por fazenda", () => {
    const sf = buscar("sao felix", base)
    expect(sf.municipios[0]).toMatchObject({ cod_ibge: "1507300", tem_imoveis: true })
    expect(buscar("xingu", base).municipios.map((m) => m.municipio)).toEqual(
      expect.arrayContaining(["São Félix do Xingu", "Vitória do Xingu"]),
    )
    expect(buscar("Altamira", base).municipios[0]).toMatchObject({ cod_ibge: "1500602", tem_imoveis: false })
    expect(buscar("1504950", base).municipios[0].municipio).toBe("Nova Esperança do Piriá")
    expect(buscar("al", base).situacao).toBe("curta")
    const nada = buscar("Curitiba", base)
    expect(nada.situacao).toBe("nao_encontrado")
    expect(nada.mensagem).toContain("Pará")
  })
})
