#!/usr/bin/env node
/** Dados pequenos e determinísticos para testar o build do Pages, sem acessar serviços públicos.
 * São fazendas fictícias: nunca usar esta pasta para publicar o produto.
 * O PMTiles contém MVT de verdade, lido pelo mesmo protocolo HTTP Range do site.
 */
import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

export const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..")
export const FIXTURE = path.join(REPO, "front/.cache/teste-site")
export const MUNICIPIO = "1505536"
export const SEM_DESENHO = "1502772"
export const CAR = `PA-${MUNICIPIO}-${"A".repeat(32)}`
export const CAR_PENDENTE = `PA-${MUNICIPIO}-${"B".repeat(32)}`

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
  fs.mkdirSync(geo, { recursive: true })
  fs.mkdirSync(dados, { recursive: true })
  const salvar = (nome, conteudo) => fs.writeFileSync(path.join(geo, nome), JSON.stringify(conteudo))
  const municipio = retangulo([-49.95, -6.15, -49.85, -6.05], { cod_ibge: MUNICIPIO, nome: "Parauapebas", uf: "PA" })
  const semDesenho = retangulo([-49.7, -6.2, -49.6, -6.1], { cod_ibge: SEM_DESENHO, nome: "Curionópolis", uf: "PA" })
  salvar("brasil_municipios.geojson", colecao([municipio, semDesenho]))
  salvar("brasil_estados.geojson", colecao([retangulo([-58, -10, -46, 2], { uf: "PA", nome: "Pará" })]))
  salvar(`municipio_${MUNICIPIO}.geojson`, colecao([municipio]))
  salvar(`imoveis_${MUNICIPIO}.geojson`, colecao([
    retangulo([-49.908, -6.108, -49.900, -6.096], { cod_imovel: CAR }),
    retangulo([-49.898, -6.108, -49.890, -6.096], { cod_imovel: CAR_PENDENTE }),
  ]))
  fs.writeFileSync(path.join(geo, "base_brasil.pmtiles"), basePmtiles())
  const item = (arquivo) => ({ arquivo, bytes: fs.statSync(path.join(geo, arquivo)).size })
  salvar("indice.json", {
    brasil: {
      municipios: item("brasil_municipios.geojson"), estados: item("brasil_estados.geojson"), base: item("base_brasil.pmtiles"),
    },
    municipios: { [MUNICIPIO]: { municipio: item(`municipio_${MUNICIPIO}.geojson`), imoveis: item(`imoveis_${MUNICIPIO}.geojson`) } },
  })
  fs.writeFileSync(path.join(dados, "resumo_PA.csv"),
    "cod_ibge,municipio,imoveis,sem_problema,aptas_carbono,ha_carbono,aptas_com_matricula,ha_carbono_matricula\n" +
    `${MUNICIPIO},Parauapebas,2,2,2,120,1,80\n${SEM_DESENHO},Curionópolis,1,1,1,40,0,0\n`)
  const cabecalho = "cod_imovel,uf,municipio,cod_municipio_ibge,ha,carbono_ha,f_matricula,problema,desm_pos2016_ha\n"
  fs.writeFileSync(path.join(dados, `imoveis_${MUNICIPIO}.csv`), cabecalho +
    `${CAR},PA,Parauapebas,${MUNICIPIO},120,80,0.8,False,0\n` +
    `${CAR_PENDENTE},PA,Parauapebas,${MUNICIPIO},90,40,0,False,0\n`)
  fs.writeFileSync(path.join(dados, `imoveis_${SEM_DESENHO}.csv`), cabecalho +
    `PA-${SEM_DESENHO}-${"C".repeat(32)},PA,Curionópolis,${SEM_DESENHO},90,40,0,False,0\n`)
  console.log(`Fixture do Pages pronta: ${path.relative(REPO, FIXTURE)} (dados fictícios, uso exclusivo nos testes).`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) preparar()
