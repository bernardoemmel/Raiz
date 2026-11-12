import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import { dadosRaiz } from '../compartilhado/vite-dados'

// raiz do repositório: os dados ficam em dados/amostra/ e as geometrias em front/geo/
const repo = fileURLToPath(new URL('../..', import.meta.url))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), dadosRaiz({ repo })],
  server: { fs: { allow: [repo] } },
  test: { include: ['../compartilhado/**/*.test.ts', 'src/**/*.test.ts'], root: '.' },
})
