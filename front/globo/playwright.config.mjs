import { defineConfig } from "@playwright/test"
import { fileURLToPath } from "node:url"

const repo = fileURLToPath(new URL("../..", import.meta.url))
if (!process.env.RAIZ_E2E_ESTADO || !process.env.RAIZ_API_TOKEN) throw new Error("Use npm run test:e2e:api")

export default defineConfig({
  testDir: "../../testes/e2e",
  testMatch: "**/*.spec.mjs",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  outputDir: "test-results",
  use: {
    baseURL: "http://127.0.0.1:4173",
    browserName: "chromium",
    viewport: { width: 1440, height: 900 },
    // Traces guardariam o token de sessão e o link de entrada.
    trace: "off",
    screenshot: "only-on-failure",
    launchOptions: {
      ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
      args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
    },
  },
  webServer: [
    {
      command: "uv run --frozen python -m testes.e2e.servidor",
      cwd: repo,
      url: "http://127.0.0.1:8765/saude",
      timeout: 180_000,
      reuseExistingServer: false,
      stdout: "ignore",
    },
    {
      command: "node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173 --strictPort",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: false,
      env: {
        VITE_RAIZ_API: "http://127.0.0.1:8765",
        // Token descartável, apenas no servidor local deste teste; nunca no build público.
        VITE_RAIZ_API_TOKEN: process.env.RAIZ_API_TOKEN,
        RAIZ_SEM_DOWNLOAD: "1",
        RAIZ_DADOS: "dados/amostra",
      },
    },
  ],
})
