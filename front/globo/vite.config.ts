import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import { transformWithOxc } from 'vite'
import { acertoRaiz } from '../compartilhado/vite-acerto'
import { dadosRaiz } from '../compartilhado/vite-dados'
import { maplibreCeuTransparente } from '../compartilhado/vite-maplibre-ceu'

// raiz do repositório: os dados ficam em dados/amostra/ e as geometrias em front/geo/
const repo = fileURLToPath(new URL('../..', import.meta.url))

// Só o teste do adaptador importa os TS internos. O build upstream remove declarações
// de campos sem inicializador; preserve essa semântica sem alterar o código da aplicação.
const fontesMapLibreNoTeste = process.env.VITEST ? [{
  name: 'raiz-fontes-maplibre-no-teste',
  enforce: 'pre' as const,
  transform(code: string, id: string) {
    if (!id.replaceAll('\\', '/').includes('/maplibre-gl/src/') || !id.endsWith('.ts')) return null
    return transformWithOxc(code, id, { lang: 'ts', typescript: { removeClassFieldsWithoutInitializer: true }, assumptions: { setPublicClassFields: true } })
  },
}] : []

// https://vite.dev/config/
// RAIZ_BASE: o caminho do site (no GitHub Pages, /Raiz/); sem ela, a raiz
export default defineConfig({
  base: process.env.RAIZ_BASE || '/',
  plugins: [...fontesMapLibreNoTeste, maplibreCeuTransparente(), react(), dadosRaiz({ repo }), acertoRaiz({ repo })],
  server: { fs: { allow: [repo] } },
  test: { include: ['../compartilhado/**/*.test.ts', 'src/**/*.test.ts'], root: '.', server: { deps: { inline: [/maplibre-gl\/src/] } } },
})
