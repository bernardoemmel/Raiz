#!/usr/bin/env node
import { readFileSync, writeFileSync } from "node:fs"
import { arquivoShaderSimbolo } from "../compartilhado/gerar-shader-simbolo.ts"
const pacote = new URL("../globo/node_modules/maplibre-gl/", import.meta.url)
const codigo = readFileSync(new URL("dist/maplibre-gl.mjs", pacote), "utf8")
const { version } = JSON.parse(readFileSync(new URL("package.json", pacote), "utf8"))
writeFileSync(new URL("../globo/src/mapa/shader-simbolo.generated.ts", import.meta.url), arquivoShaderSimbolo(codigo, version))
