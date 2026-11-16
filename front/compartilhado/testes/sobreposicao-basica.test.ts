import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { expect, it } from "vitest"
import { abrirPasta } from "../pasta-dados"

it("preserva apenas sinal booleano de sobreposição no contorno básico", () => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "raiz-contorno-basico-"))
  try {
    const dados = path.join(repo, "dados"), geo = path.join(repo, "geo"), uf = path.join(dados, "PA")
    fs.mkdirSync(uf, { recursive: true }); fs.mkdirSync(geo)
    const cod = "1505536", cars = ["A", "B", "C"].map(x => `PA-${cod}-${x.repeat(32)}`)
    fs.writeFileSync(path.join(dados, "estados.json"), JSON.stringify({ escopo: "publico_basico", versao_publicacao: 1, estados: { PA: { escopo: "publico_basico", versao_publicacao: 1 } } }))
    fs.writeFileSync(path.join(uf, "resumo_PA.csv"), `cod_ibge,municipio,imoveis\n${cod},Parauapebas,3\n`)
    fs.writeFileSync(path.join(uf, `imoveis_basicos_${cod}.csv`), "cod_imovel,cod_ibge,municipio,uf,situacao_basica\n" + cars.map(c => `${c},${cod},Parauapebas,PA,apto\n`).join(""))
    fs.writeFileSync(path.join(geo, `imoveis_${cod}.geojson`), JSON.stringify({ type: "FeatureCollection", features: cars.map((car, n) => ({
      type: "Feature", properties: { cod_imovel: car, sobreposto: [true, false, "sim"][n], carbono_ha: 999, proprietario: "PRIVADO" },
      geometry: { type: "Polygon", coordinates: [[[-50, -6], [-49, -6], [-49, -5], [-50, -6]]] },
    })) }))
    const dadosPublicos = abrirPasta({ repo, raizDados: dados, geo }).geoBasico(cod)
    expect(dadosPublicos?.features.map(f => f.properties)).toEqual([
      { cod_imovel: cars[0], sobreposto: true }, { cod_imovel: cars[1], sobreposto: false }, { cod_imovel: cars[2] },
    ])
    expect(JSON.stringify(dadosPublicos)).not.toMatch(/carbono_ha|proprietario|PRIVADO/)
  } finally { fs.rmSync(repo, { recursive: true, force: true }) }
})
