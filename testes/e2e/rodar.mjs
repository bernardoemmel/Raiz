import { spawnSync } from "node:child_process"
import { randomBytes } from "node:crypto"
import { mkdtempSync, rmSync } from "node:fs"
import { createRequire } from "node:module"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const globo = fileURLToPath(new URL("../../front/globo", import.meta.url))
const require = createRequire(path.join(globo, "package.json"))
const estado = mkdtempSync(path.join(os.tmpdir(), "raiz-e2e-api-"))
try {
  const resultado = spawnSync(process.execPath, [require.resolve("@playwright/test/cli"), "test", ...process.argv.slice(2)], {
    cwd: globo,
    stdio: "inherit",
    env: { ...process.env, RAIZ_E2E_ESTADO: estado, RAIZ_API_TOKEN: randomBytes(32).toString("hex") },
  })
  process.exitCode = resultado.status ?? 1
} finally {
  rmSync(estado, { recursive: true, force: true })
}
