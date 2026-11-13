import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import { acertoRaiz } from '../compartilhado/vite-acerto'
import { dadosRaiz } from '../compartilhado/vite-dados'
import { maplibreCeuTransparente } from '../compartilhado/vite-maplibre-ceu'

// raiz do repositório: os dados ficam em dados/amostra/ e as geometrias em front/geo/
const repo = fileURLToPath(new URL('../..', import.meta.url))

// https://vite.dev/config/
// RAIZ_BASE: o caminho do site (no GitHub Pages, /Raiz/); sem ela, a raiz
export default defineConfig({
  base: process.env.RAIZ_BASE || '/',
  plugins: [maplibreCeuTransparente(), react(), dadosRaiz({ repo }), acertoRaiz({ repo })],
  server: { fs: { allow: [repo] } },
  test: { include: ['../compartilhado/**/*.test.ts', 'src/**/*.test.ts'], root: '.' },
})
