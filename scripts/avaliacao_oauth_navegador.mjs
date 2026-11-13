// Login somente na pilha local de avaliação. Entrada/saída são pipes privados do runner.
import { createRequire } from 'node:module';
const require = createRequire(new URL('../front/globo/package.json', import.meta.url));
const { chromium } = require('playwright');
let entrada = '';
for await (const parte of process.stdin) entrada += parte;
const config = JSON.parse(entrada);
const origem = new URL(config.autorizacao);
if (origem.origin !== 'http://127.0.0.1:18180' || !origem.pathname.startsWith('/realms/')) {
  throw new Error('OAuth fora da pilha de avaliação');
}
const navegador = await chromium.launch({ headless: true });
try {
  const pagina = await navegador.newPage({ serviceWorkers: 'block' });
  let callback = null;
  await pagina.route('**/*', async rota => {
    const url = rota.request().url();
    if (url.split('?')[0] === config.redirect) {
      callback = url;
      return rota.fulfill({ status: 200, contentType: 'text/plain', body: 'Autenticação da avaliação concluída.' });
    }
    if (new URL(url).origin !== origem.origin) return rota.abort();
    if (rota.request().isNavigationRequest()) {
      const resposta = await rota.fetch({ maxRedirects: 0 });
      const destino = resposta.headers()['location'];
      if (destino && destino.split('?')[0] === config.redirect) {
        callback = destino;
        return rota.fulfill({ status: 200, contentType: 'text/plain', body: 'Autenticação concluída.' });
      }
      return rota.fulfill({ response: resposta });
    }
    return rota.continue();
  });
  await pagina.goto(config.autorizacao, { waitUntil: 'domcontentloaded' });
  if (!callback) {
  await pagina.locator('input[name="username"]').fill(config.usuario);
  await pagina.locator('input[name="password"]').fill(config.senha);
  await pagina.locator('#kc-login').click();
  }
  for (let passo = 0; passo < 100 && !callback; passo++) {
    const aceite = pagina.locator('input[name="accept"], button[name="accept"]');
    if (await aceite.isVisible()) await aceite.click();
    await pagina.waitForTimeout(100);
  }
  if (!callback) throw new Error('OAuth não concluiu o callback');
  process.stdout.write(JSON.stringify({ callback }));
} finally {
  await navegador.close();
}
