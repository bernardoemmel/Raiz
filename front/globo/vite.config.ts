import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import { transformWithOxc } from 'vite'
import { acertoRaiz } from '../compartilhado/vite-acerto'
import { dadosRaiz } from '../compartilhado/vite-dados'
import { maplibreCeuTransparente } from '../compartilhado/vite-maplibre-ceu'
import { maplibreProgramasNacionais } from '../compartilhado/vite-maplibre-programas'

// raiz do repositório: os dados ficam em dados/amostra/ e as geometrias em front/geo/
const repo = fileURLToPath(new URL('../..', import.meta.url))

// Somente testes importam os TS privados do fornecedor para conferir as variantes reais.
// Seu build remove campos de classe sem inicializador; preserve a mesma semântica no harness.
const fontesMapLibreNoTeste = process.env.VITEST ? [{
  name: 'raiz-fontes-maplibre-no-teste', enforce: 'pre' as const,
  transform(code: string, id: string) {
    if (!id.replaceAll('\\', '/').includes('/maplibre-gl/src/') || !id.endsWith('.ts')) return null
    return transformWithOxc(code, id, { lang: 'ts', typescript: { removeClassFieldsWithoutInitializer: true }, assumptions: { setPublicClassFields: true } })
  },
}] : []

// https://vite.dev/config/
// RAIZ_BASE: o caminho do site (no GitHub Pages, /Raiz/); sem ela, a raiz
export default defineConfig({
  base: process.env.RAIZ_BASE || '/',
  plugins: [...fontesMapLibreNoTeste, maplibreCeuTransparente(), maplibreProgramasNacionais(), react(), dadosRaiz({ repo }), acertoRaiz({ repo })],
  worker: { plugins: () => [maplibreProgramasNacionais()] },
  server: { fs: { allow: [repo] } },
  test: { include: ['../compartilhado/**/*.test.ts', 'src/**/*.test.ts'], root: '.', server: { deps: { inline: [/maplibre-gl\/src/] } } },
})
