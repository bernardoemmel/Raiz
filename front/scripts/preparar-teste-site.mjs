#!/usr/bin/env node
/** Dados pequenos e determinísticos para testar o build do Pages, sem acessar serviços públicos.
 * São fazendas fictícias: nunca usar esta pasta para publicar o produto.
 * O PMTiles contém MVT de verdade, lido pelo mesmo protocolo HTTP Range do site.
 */
import fs from "node:fs"
import { gzipSync } from "node:zlib"
import path from "node:path"
import { fileURLToPath } from "node:url"

export const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
export const FIXTURE = path.join(REPO, "front/.cache/teste-site")
export const MUNICIPIO = "1505536"
export const SEM_DESENHO = "1502772"
export const MUNICIPIOS_FRONTEIRA = ["2400109", "2413409"]
export const CAR_FRONTEIRA = `PB-2500106-${"D".repeat(32)}`
export const CAR = `PA-${MUNICIPIO}-${"A".repeat(32)}`
export const CAR_PENDENTE = `PA-${MUNICIPIO}-${"B".repeat(32)}`
export const CANARIO_PRIVADO = "certidao_PRIVADA_nao_publicar"
export const CARS = [CAR, CAR_PENDENTE, ...["D", "E", "F", "1"].map((letra) => `PA-${MUNICIPIO}-${letra.repeat(32)}`)]

const colecao = (features) => ({ type: "FeatureCollection", features })
const retangulo = ([x0, y0, x1, y1], properties = {}) => ({
  type: "Feature", properties,
  geometry: { type: "Polygon", coordinates: [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]] },
})

// Escritor mínimo dos formatos públicos MVT/PMTiles, só para a fixture:
// uma mesma feição de água por tile, z0..6. Não substitui a renderização por mock.
function varint(n) {
  const bytes = []
  while (n > 127) { bytes.push((n & 127) | 128); n = Math.floor(n / 128) }
  bytes.push(n)
  return Buffer.from(bytes)
}
const inteiro = (tag, n) => Buffer.concat([varint(tag * 8), varint(n)])
const campo = (tag, dado) => {
  const bytes = Buffer.isBuffer(dado) ? dado : Buffer.from(dado)
  return Buffer.concat([varint(tag * 8 + 2), varint(bytes.length), bytes])
}
function basePmtiles() {
  const geometria = Buffer.concat([9, 0, 0, 26, 8192, 0, 0, 8192, 8191, 0, 15].map(varint))
  const feicao = Buffer.concat([inteiro(1, 1), inteiro(3, 3), campo(4, geometria)])
  const camada = Buffer.concat([campo(1, "water"), campo(2, feicao), inteiro(5, 4096), inteiro(15, 2)])
  const tile = campo(3, camada)
  const nTiles = (4 ** 7 - 1) / 3
  const diretorio = Buffer.concat([1, 0, nTiles, tile.length, 1].map(varint))
  const meta = Buffer.from(JSON.stringify({ vector_layers: [{ id: "water", fields: {}, minzoom: 0, maxzoom: 6 }] }))
  const header = Buffer.alloc(127)
  header.write("PMTiles", 0)
  header[7] = 3
  const u64 = (offset, valor) => header.writeBigUInt64LE(BigInt(valor), offset)
  u64(8, 127); u64(16, diretorio.length)
  u64(24, 127 + diretorio.length); u64(32, meta.length)
  u64(40, 127 + diretorio.length + meta.length); u64(48, 0)
  u64(56, 127 + diretorio.length + meta.length); u64(64, tile.length)
  u64(72, nTiles); u64(80, 1); u64(88, 1)
  header[96] = 1; header[97] = 1; header[98] = 1; header[99] = 1
  header[100] = 0; header[101] = 6
  for (const [offset, n] of [[102, -180], [106, -85], [110, 180], [114, 85]]) header.writeInt32LE(n * 1e7, offset)
  header[118] = 6
  return Buffer.concat([header, diretorio, meta, tile])
}

export function preparar() {
  const geo = path.join(FIXTURE, "geo")
  const dados = path.join(FIXTURE, "dados/PA")
  const calendario = path.join(FIXTURE, "calendario")
  // Não deixar um arquivo de uma execução anterior mudar o resultado da fixture.
  fs.rmSync(geo, { recursive: true, force: true })
  fs.rmSync(path.join(FIXTURE, "dados"), { recursive: true, force: true })
  fs.rmSync(calendario, { recursive: true, force: true })
  fs.mkdirSync(geo, { recursive: true })
  fs.mkdirSync(dados, { recursive: true })
  fs.mkdirSync(calendario, { recursive: true })
  const evento = {
    id: "a".repeat(24), tipo: "leilao_imovel", titulo: "Leilão fictício para teste do Pages",
    data: "2099-11-15", prazo: null, uf: "PA", municipio: MUNICIPIO, codigos_car: [CAR],
    fonte_url: "https://example.test/leilao", fonte_nome: "Fonte fictícia de teste",
    coletado_em: "2026-11-12T12:00:00Z", confianca: 0.9, situacao: "previsto",
  }
  fs.writeFileSync(path.join(calendario, "eventos.json"), JSON.stringify({
    eventos: [evento], total: 1, coletado_em: evento.coletado_em, fontes: [],
  }))
  fs.writeFileSync(path.join(calendario, "eventos.ics"), [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Raiz//Teste//PT-BR", "BEGIN:VEVENT",
    `UID:${evento.id}@teste.raiz`, "DTSTAMP:20261112T120000Z", "DTSTART;VALUE=DATE:20991115",
    "DTEND;VALUE=DATE:20991116", `SUMMARY:${evento.titulo}`, "END:VEVENT", "END:VCALENDAR", "",
  ].join("\r\n"))
  const salvar = (nome, conteudo) => fs.writeFileSync(path.join(geo, nome), JSON.stringify(conteudo))
  const municipio = retangulo([-50.05, -6.3, -49.84, -5.95], { cod_ibge: MUNICIPIO, nome: "Parauapebas", uf: "PA" })
  const semDesenho = retangulo([-49.7, -6.2, -49.6, -6.1], { cod_ibge: SEM_DESENHO, nome: "Curionópolis", uf: "PA" })
  salvar("brasil_municipios.geojson", colecao([municipio, semDesenho]))
  salvar("brasil_estados.geojson", colecao([retangulo([-58, -10, -46, 2], { uf: "PA", nome: "Pará" })]))
  salvar(`municipio_${MUNICIPIO}.geojson`, colecao([municipio]))
  // A origem contém campos privados e um CAR fora do contrato; o build deve projetar só a camada básica.
  salvar(`imoveis_${MUNICIPIO}.geojson`, colecao(CARS.map((car, i) =>
    retangulo([-49.93 + i * 0.01 - (i === 1 ? 0.006 : 0), -6.108, -49.922 + i * 0.01, -6.096], { cod_imovel: car, sobreposto: i < 2, certidao_ia: CANARIO_PRIVADO, credito_p50: 987654.32 }),
  ).concat(retangulo([-49.95, -6.11, -49.94, -6.10], { cod_imovel: `PA-${MUNICIPIO}-${"9".repeat(32)}`, certidao_ia: CANARIO_PRIVADO }))))
  salvar("potencial_PA.geojson", {
    ...colecao([{ type: "Feature", properties: { h3: "85814e6bfffffff", potencial_ha: 1000, fazendas: 6 },
      geometry: { type: "Polygon", coordinates: [[[-49.8984495939181, -6.260471150530112], [-49.847870642465764, -6.178610266870429], [-49.89342649424477, -6.093467393596889], [-49.989516791316845, -6.090200910457667], [-50.04007122789514, -6.1720383434742745], [-49.994560011151954, -6.257165702980741], [-49.8984495939181, -6.260471150530112]]] } },
      { type: "Feature", properties: { h3: "85814ad3fffffff", potencial_ha: null, fazendas: 5 }, geometry: retangulo([-50, -6.1, -49.9, -6]).geometry }]),
    metadados: { contrato: "potencial_h3", versao: 1, resolucao: 5, minimo_contribuintes: 5, dominio_ha: [0,100,1000,10000,50000], atualizado_em: "2026-11-12T10:41:00Z", fonte: "Fixture fictícia de teste", metodo: "ponto_interior_estatistico", cobertura: "parcial" },
  })
  fs.writeFileSync(path.join(geo, "base_brasil.pmtiles"), basePmtiles())
  // Letras reais dos números do cluster; snapshot pequeno e licenciado, sem rede no CI.
  fs.cpSync(path.join(REPO, "front/scripts/fixtures/fontes"), path.join(geo, "fontes"), { recursive: true })
  fs.writeFileSync(path.join(geo, "potencial_PA.geojson.gz"), gzipSync(fs.readFileSync(path.join(geo, "potencial_PA.geojson"))))
  const item = (arquivo) => ({ arquivo, bytes: fs.statSync(path.join(geo, arquivo)).size })
  salvar("potencial_indice.json", { potencial: { PA: item("potencial_PA.geojson.gz") } })
  salvar("indice.json", {
    gerado_em: "2026-11-12T10:41:00Z", dados_publicados_em: "2026-11-11T18:00:00Z",
    brasil: {
      municipios: item("brasil_municipios.geojson"), estados: item("brasil_estados.geojson"), base: item("base_brasil.pmtiles"),
    },
    potencial: { PA: item("potencial_PA.geojson.gz") },
    municipios: { [MUNICIPIO]: { municipio: item(`municipio_${MUNICIPIO}.geojson`), imoveis: item(`imoveis_${MUNICIPIO}.geojson`) } },
    sem_contorno: { [SEM_DESENHO]: "Ainda não publicado" },
  })
  fs.writeFileSync(path.join(FIXTURE, "dados/estados.json"), JSON.stringify({
    versao_publicacao: 1, escopo: "publico_basico", gerado_em: "2026-11-12T00:00:00Z",
    estados: { PA: { versao_publicacao: 1, escopo: "publico_basico", municipios: 2, total_ibge: 144, completo: false },
      RN: { versao_publicacao: 1, escopo: "publico_basico", municipios: 2, total_ibge: 167, completo: false } },
  }))
  const basico = "cod_imovel,cod_ibge,municipio,uf,situacao_basica\n"
  // O mesmo CAR cadastrado na PB cruza dois recortes RN; a PB continua sem dados próprios.
  const rn = path.join(FIXTURE, "dados/RN")
  fs.mkdirSync(rn, { recursive: true })
  for (const cod of MUNICIPIOS_FRONTEIRA) fs.writeFileSync(path.join(rn, `imoveis_basicos_${cod}.csv`),
    basico + `${CAR_FRONTEIRA},${cod},Município de fronteira,RN,apto\n`)
  fs.writeFileSync(path.join(rn, "resumo_RN.csv"), "cod_ibge,municipio,imoveis\n" + MUNICIPIOS_FRONTEIRA.map(cod => `${cod},Município de fronteira,1\n`).join(""))
  fs.writeFileSync(path.join(dados, `imoveis_basicos_${MUNICIPIO}.csv`), basico + CARS.map((car, i) =>
    `${car},${MUNICIPIO},Parauapebas,PA,${["apto", "com_pendencia", "nao_apto"][i % 3]}\n`,
  ).join(""))
  fs.writeFileSync(path.join(dados, `imoveis_basicos_${SEM_DESENHO}.csv`), basico +
    `PA-${SEM_DESENHO}-${"C".repeat(32)},${SEM_DESENHO},Curionópolis,PA,apto\n`)
  fs.writeFileSync(path.join(dados, "resumo_PA.csv"),
    "cod_ibge,municipio,imoveis,sem_problema,aptas_carbono,ha_carbono,aptas_com_matricula,ha_carbono_matricula\n" +
    `${MUNICIPIO},Parauapebas,6,6,6,360,3,240\n${SEM_DESENHO},Curionópolis,1,1,1,40,0,0\n`)
  const cabecalho = "cod_imovel,uf,municipio,cod_municipio_ibge,ha,carbono_ha,f_matricula,problema,desm_pos2016_ha,certidao_ia\n"
  fs.writeFileSync(path.join(dados, `imoveis_${MUNICIPIO}.csv`), cabecalho + CARS.map((car, i) =>
    `${car},PA,Parauapebas,${MUNICIPIO},${i % 2 ? 90 : 120},${i % 2 ? 40 : 80},${i % 2 ? 0 : 0.8},False,0,${CANARIO_PRIVADO}\n`,
  ).join(""))
  fs.writeFileSync(path.join(dados, `imoveis_${SEM_DESENHO}.csv`), cabecalho +
    `PA-${SEM_DESENHO}-${"C".repeat(32)},PA,Curionópolis,${SEM_DESENHO},90,40,0,False,0,${CANARIO_PRIVADO}\n`)
  console.log(`Fixture do Pages pronta: ${path.relative(REPO, FIXTURE)} (dados fictícios, uso exclusivo nos testes).`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) preparar()
