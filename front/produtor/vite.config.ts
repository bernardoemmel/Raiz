import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import { dadosRaiz } from '../compartilhado/vite-dados'

// raiz do repositório: os dados ficam em dados/amostra/ e as geometrias em front/geo/
const repo = fileURLToPath(new URL('../..', import.meta.url))

// Preact sem plugin: o Oxc do Vite 8 já transforma o JSX com o runtime automático do Preact
export default defineConfig({
  base: './',
  oxc: { jsx: { runtime: 'automatic', importSource: 'preact' } },
  plugins: [dadosRaiz({ repo })],
  server: { port: 5174, fs: { allow: [repo] } },
  build: { target: 'es2020', reportCompressedSize: true },
})
