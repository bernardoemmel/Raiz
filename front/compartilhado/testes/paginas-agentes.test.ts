import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { afterEach, describe, expect, it } from "vitest"
import { lerFunil } from "../dados/funil"
import type { Estados } from "../dados/tipos"
import { paginasAgentes } from "../paginas-agentes"

const temporarios: string[] = []
const preparar = () => {
  const saida = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-paginas-"))
  temporarios.push(saida)
  fs.writeFileSync(path.join(saida, "index.html"), "<!doctype html><html><head></head><body></body></html>")
  return saida
}
afterEach(() => temporarios.splice(0).forEach((p) => fs.rmSync(p, { recursive: true, force: true })))

const estados: Estados = {
  pasta: "publicada", lista_ibge: "DTB 2025", gerado_em: "2026-11-12T10:00:00Z",
  estados: [
    { uf: "PA", cod: "15", nome: "Pará", municipios_ibge: 144, municipios: 1, com_lista: ["1505536"], situacao: "incompleto", completo: false, fora_da_lista: [], versao: "abc123", atualizado_em: "2026-11-11T10:00:00Z" },
    { uf: "AC", cod: "12", nome: "Acre", municipios_ibge: 22, municipios: 0, com_lista: [], situacao: "sem_dados", completo: false, fora_da_lista: [] },
  ],
}
const municipio = lerFunil({ cod_ibge: "1505536", municipio: "Parauapebas", imoveis: "11", sem_problema: "8", aptas_carbono: "5", ha_carbono: "123.4", tco2_ano_aptas: "234.5", aptas_com_matricula: "2", ha_carbono_matricula: "40", frente_assentamento_agrupado: "1", nome_proprietario: "Nunca publicar esta pessoa", _plus_code: "SEGREDO" }, "PA")
const catalogo = { estados, municipios: [municipio], arquivos: { PA: ["resumo_PA.csv", "imoveis_1505536.csv"] } }
const ler = (saida: string, arquivo: string) => fs.readFileSync(path.join(saida, arquivo), "utf8")
const schema = (saida: string) => JSON.parse(ler(saida, "index.html").match(/<script id="raiz-dados-estruturados" type="application\/ld\+json">([\s\S]*?)<\/script>/)![1])

describe("páginas para pessoas e agentes", () => {
  for (const base of ["/", "/Raiz/"]) {
    it(`publica agregados e links corretos em ${base}`, () => {
      const saida = preparar()
      paginasAgentes({ saida, base, catalogo })
      expect(ler(saida, "index.html")).toContain(`<link rel="canonical" href="https://bernardoemmel.github.io${base}"`)
      expect(ler(saida, "index.md")).toContain("11 imóveis, 5 aptos no funil e 123,4 ha")
      expect(ler(saida, "dados/estados/PA.md")).toContain("1 de 144")
      const texto = ler(saida, "dados/municipios/1505536.md")
      expect(texto).toContain("| Imóveis analisados | 11 |")
      expect(texto).toContain("| Potencial estimado de carbono nas aptas (tCO₂/ano) | 234,5 |")
      expect(texto).toContain(`(${base}#/municipio/1505536)`)
      expect(texto).not.toContain("Nunca publicar")
      expect(texto).not.toContain("SEGREDO")
      expect(fs.existsSync(path.join(saida, "dados/estados/AC.md"))).toBe(false)
      const dados = schema(saida)["@graph"].filter((g: Record<string, unknown>) => g["@type"] === "Dataset")
      expect(dados).toHaveLength(1)
      expect(dados[0].distribution[0].contentUrl).toBe(`https://bernardoemmel.github.io${base}amostra/resumo_PA.csv.gz`)
      expect(dados[0].dateModified).toBe("2026-11-11T10:00:00.000Z")
      expect(dados[0].version).toBe("abc123")
      expect(ler(saida, "dados/estados/PA.md")).not.toContain("imoveis_1505536.csv")
      for (const arquivo of ["index.md", "dados/index.md", "dados/estados/PA.md", "dados/municipios/1505536.md", "servico.md", "privacidade.md", "fontes.md"]) {
        const links = [...ler(saida, arquivo).matchAll(/\]\(([^)]+)\)/g)].map((m) => m[1])
        for (const href of links.filter((l) => l.startsWith(base) && l.endsWith(".md") && !l.includes("produtor/"))) {
          expect(fs.existsSync(path.join(saida, href.slice(base.length))), `${arquivo}: ${href}`).toBe(true)
        }
      }
    })
  }

  it("mantém a supressão de grupos pequenos no município, estado e total do Brasil", () => {
    const saida = preparar()
    const pequena = lerFunil({ ...municipio.linha, cod_ibge: "1504208", municipio: "Marabá", imoveis: "3", ha_carbono: "987.65" }, "PA")
    paginasAgentes({ saida, base: "/Raiz/", catalogo: { ...catalogo, municipios: [municipio, pequena] } })
    const local = ler(saida, "dados/municipios/1504208.md")
    expect(local).toContain("| Imóveis analisados | Suprimido |")
    expect(local).not.toContain("987,65")
    expect(local).not.toContain("| Imóveis analisados | 3 |")
    for (const arq of ["index.md", "dados/index.md", "dados/estados/PA.md"]) {
      expect(ler(saida, arq)).toContain("totais deste recorte foram suprimidos")
      expect(ler(saida, arq)).not.toContain("14 imóveis")
    }
    const dados = schema(saida)["@graph"].filter((g: Record<string, unknown>) => g["@type"] === "Dataset")
    expect(dados[0].distribution).toHaveLength(1)
    expect(dados[0].distribution[0].name).toBe("resumo_PA.csv")
  })

  it("não anuncia estados que tenham somente listas privadas de fazendas", () => {
    const saida = preparar()
    paginasAgentes({ saida, base: "/Raiz/", catalogo: { ...catalogo, arquivos: { PA: ["imoveis_1505536.csv"] } } })
    expect(schema(saida)["@graph"].some((g: Record<string, unknown>) => g["@type"] === "Dataset")).toBe(false)
    expect(fs.existsSync(path.join(saida, "dados/estados/PA.md"))).toBe(false)
    expect(ler(saida, "index.md")).not.toContain("11 imóveis")
  })

  it("preserva a marca de supressão mesmo quando o leitor normalizou vazios para zero", () => {
    const saida = preparar()
    const suprimido = lerFunil({ ...municipio.linha, dados_suprimidos: "true", imoveis: "", ha_carbono: "" }, "PA")
    paginasAgentes({ saida, base: "/Raiz/", catalogo: { ...catalogo, municipios: [suprimido] } })
    expect(ler(saida, "dados/municipios/1505536.md")).toContain("| Imóveis analisados | Suprimido |")
    expect(ler(saida, "dados/municipios/1505536.md")).not.toContain("| Imóveis analisados | 0 |")
  })

  it("distingue medida ausente de zero e não publica soma parcial como total", () => {
    const saida = preparar()
    const ausente = lerFunil({ ...municipio.linha, cod_ibge: "1506401", municipio: "Santa Cruz do Arari", imoveis: "130", aptas_carbono: "0", ha_carbono: "" }, "PA")
    const zero = lerFunil({ ...municipio.linha, cod_ibge: "1507706", municipio: "São Sebastião da Boa Vista", imoveis: "40", aptas_carbono: "0", ha_carbono: "0" }, "PA")
    paginasAgentes({ saida, base: "/", catalogo: { ...catalogo, municipios: [ausente, zero] } })
    expect(ler(saida, "dados/municipios/1506401.md")).toContain("| Área de carbono nas fazendas aptas (ha) | Ainda não publicado |")
    expect(ler(saida, "dados/municipios/1506401.md")).toContain("| Imóveis aptos para carbono | 0 |")
    expect(ler(saida, "dados/municipios/1507706.md")).toContain("| Área de carbono nas fazendas aptas (ha) | 0 |")
    const estadual = ler(saida, "dados/estados/PA.md")
    expect(estadual).toContain("| 1506401 | 130 | 0 | Ainda não publicado |")
    expect(estadual).toContain("| 1507706 | 40 | 0 | 0 |")
    for (const arquivo of ["index.md", "dados/index.md", "dados/estados/PA.md"]) {
      const texto = ler(saida, arquivo)
      expect(texto).toContain("Há medidas ainda não publicadas neste recorte.")
      expect(texto).toContain("Imóveis: 170. Aptos no funil: 0. Área de carbono nas fazendas aptas (ha): Ainda não publicado.")
      expect(texto).not.toContain("0 ha de área de carbono")
      expect(texto).not.toContain("totais deste recorte foram suprimidos")
    }
    // O JSON-LD descreve a cobertura e o download; não deve introduzir uma soma parcial de área.
    expect(ler(saida, "index.html")).not.toContain("0 ha de área de carbono")
  })

  it("não chama contagem ausente de supressão nem abre medidas sem grupo mínimo conhecido", () => {
    const saida = preparar()
    const semContagem = lerFunil({ ...municipio.linha, imoveis: "", ha_carbono: "987.65" }, "PA")
    paginasAgentes({ saida, base: "/", catalogo: { ...catalogo, municipios: [semContagem] } })
    const local = ler(saida, "dados/municipios/1505536.md")
    expect(local).toContain("| Imóveis analisados | Ainda não publicado |")
    expect(local).not.toContain("Suprimido")
    expect(local).not.toContain("987,65")
    expect(ler(saida, "index.md")).toContain("Área de carbono nas fazendas aptas (ha): Ainda não publicado.")
    expect(ler(saida, "index.md")).not.toContain("987,65")
  })

  it.each([undefined, "", "NaN", "NA"])("não transforma indicador opcional ausente (%s) em zero", (vazio) => {
    const saida = preparar()
    const linha = { ...municipio.linha }
    for (const coluna of ["tco2_ano_aptas", "frente_assentamento_agrupado"]) {
      if (vazio === undefined) delete linha[coluna]
      else linha[coluna] = vazio
    }
    const semIndicadores = lerFunil(linha, "PA")
    expect(semIndicadores.tco2_ano_aptas).toBe(0) // padrão de cálculo não é evidência de disponibilidade
    expect(semIndicadores.para_agrupar).toBe(0)
    paginasAgentes({ saida, base: "/Raiz/", catalogo: { ...catalogo, municipios: [semIndicadores] } })
    const texto = ler(saida, "dados/municipios/1505536.md")
    expect(texto).not.toContain("| Potencial estimado de carbono")
    expect(texto).not.toContain("| Imóveis na frente de assentamentos")
    expect(texto).toContain("| Imóveis analisados | 11 |")
    expect(texto).toContain("Ausência de informação não significa zero")
  })

  it("preserva o zero declarado pela fonte nos indicadores opcionais", () => {
    const saida = preparar()
    const zeroConhecido = lerFunil({ ...municipio.linha, tco2_ano_aptas: "0", frente_assentamento_agrupado: "0" }, "PA")
    paginasAgentes({ saida, base: "/Raiz/", catalogo: { ...catalogo, municipios: [zeroConhecido] } })
    const texto = ler(saida, "dados/municipios/1505536.md")
    expect(texto).toContain("| Potencial estimado de carbono nas aptas (tCO₂/ano) | 0 |")
    expect(texto).toContain("| Imóveis na frente de assentamentos para agrupar | 0 |")
  })

  it("omite opcionais de soma de imóveis sem evidência na tabela de origem", () => {
    const saida = preparar()
    const calculado = { ...municipio, origem: "imoveis" as const, linha: {}, tco2_ano_aptas: 0, para_agrupar: 0 }
    paginasAgentes({ saida, base: "/Raiz/", catalogo: { ...catalogo, municipios: [calculado] } })
    const texto = ler(saida, "dados/municipios/1505536.md")
    expect(texto).not.toContain("| Potencial estimado de carbono")
    expect(texto).not.toContain("| Imóveis na frente de assentamentos")
  })

  it("não apresenta preços de demonstração como ofertas comerciais", () => {
    const saida = preparar()
    paginasAgentes({ saida, base: "/Raiz/", catalogo })
    const servico = schema(saida)["@graph"].find((g: Record<string, unknown>) => g["@type"] === "Service")
    expect(servico.offers).toHaveLength(2)
    expect(servico.offers.every((o: Record<string, unknown>) => o["@type"] === "Offer" && !("price" in o))).toBe(true)
    expect(ler(saida, "servico.md")).toContain("Não efetiva contato, reserva ou cobrança real")
    expect(ler(saida, "servico.md")).toContain("não uma tabela comercial confirmada")
  })

  it("build sem dados não anuncia datasets nem totais de amostra", () => {
    const saida = preparar()
    paginasAgentes({ saida, base: "/Raiz/" })
    expect(ler(saida, "index.md")).toContain("não inclui tabelas do motor")
    expect(schema(saida)["@graph"].some((g: Record<string, unknown>) => g["@type"] === "Dataset")).toBe(false)
    expect(fs.existsSync(path.join(saida, "dados/index.md"))).toBe(true)
  })

  it("ficha estática do produtor funciona sob qualquer base e não expõe dados individuais", () => {
    const saida = preparar()
    paginasAgentes({ saida, base: "/outro/", produtor: true, catalogo })
    expect(ler(saida, "index.md")).toContain("(../index.md)")
    expect(ler(saida, "index.md")).not.toContain("Nunca publicar")
    expect(ler(saida, "index.md")).toContain("não contém uma ficha individual")
    expect(fs.existsSync(path.join(saida, "dados"))).toBe(false)
  })

  it("metadados não escapam da tag JSON-LD nem duplicam o script", () => {
    const saida = preparar()
    const dados = structuredClone(catalogo)
    dados.estados.estados[0].nome = "Pará </script><script>alert(1)</script>"
    paginasAgentes({ saida, base: "/Raiz/", catalogo: dados, siteUrl: "https://raiz.example/" })
    paginasAgentes({ saida, base: "/Raiz/", catalogo: dados, siteUrl: "https://raiz.example/" })
    expect(ler(saida, "index.html").match(/<script/g)).toHaveLength(1)
    expect(ler(saida, "index.html").match(/rel="canonical"/g)).toHaveLength(1)
    expect(schema(saida)["@graph"][0].url).toBe("https://raiz.example/")
    expect(ler(saida, "dados/estados/PA.md")).not.toContain("</script>")
  })

  it("domínio próprio anuncia a raiz e a ficha em produtor sem caminho do repositório", () => {
    for (const produtor of [false, true]) {
      const saida = preparar()
      paginasAgentes({ saida, base: "/", produtor, catalogo, siteUrl: "https://mapa.example/" })
      expect(ler(saida, "index.html")).toContain(`<link rel="canonical" href="https://mapa.example/${produtor ? "produtor/" : ""}"`)
      expect(ler(saida, "index.md")).not.toContain("/Raiz/")
    }
  })

  it("llms.txt fica abaixo de 8 KB e lista bots atuais sem bloqueio", () => {
    const publico = path.resolve(__dirname, "../../globo/public")
    expect(fs.statSync(path.join(publico, "llms.txt")).size).toBeLessThanOrEqual(8192)
    const llms = ler(publico, "llms.txt")
    expect(llms.startsWith("# Raíz\n")).toBe(true)
    expect(llms).toContain("[Brasil e cobertura dos dados](index.md)")
    const robots = ler(publico, "robots.txt")
    for (const bot of ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User", "Claude-SearchBot", "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot"]) expect(robots).toContain(`User-agent: ${bot}\n`)
    expect(robots).not.toContain("Disallow:")
  })
})
