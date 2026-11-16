// Verificação externa: não modifica o coletor nem o analisador congelados.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const pasta = process.argv[2] || 'serie';
const resultado = JSON.parse(fs.readFileSync(process.argv[3] || 'resultado.json'));
const ordem = ['ml', 'ol', 'ol', 'ml', 'ml', 'ol', 'ol', 'ml'];
const esperados = ['com', 'sem'].flatMap(c => ordem.map((e, i) => `${c}-360-${String(i).padStart(2, '0')}-${e}.json`));
assert.deepEqual(fs.readdirSync(pasta).filter(f => f.endsWith('.json')).sort(), [...esperados].sort());
assert.equal(resultado.samples.length, 16);
assert.deepEqual(resultado.samples.map(s => s.file).sort(), [...esperados].sort());
for (const s of resultado.samples) {
  const x = JSON.parse(fs.readFileSync(path.join(pasta, s.file)));
  assert.equal(x.engine, ordem[x.ordinal]);
  assert.equal(x.caseName, s.case);
  assert.equal(x.width, 360);
  assert.deepEqual([...x.bad, ...x.errors, ...x.finalErrors.page, ...x.finalErrors.source], []);
  assert(x.state.tests.every(t => t.expected === t.actual));
  for (const k of ['startup', 'import', 'common_data', 'renderer', 'frame_p50', 'frame_p95',
    'frames_over_33_3_percent', 'selection_p95', 'selection_p50'])
    assert(typeof s[k] === 'number' && Number.isFinite(s[k]), `${s.file}: métrica inválida ${k}`);
  assert.equal(s.commands, 354);
  assert.equal(s.commands_unconfirmed, 0);
}
console.log('16 observações íntegras, métricas finitas e comandos confirmados; sem erro HTTP, JS ou de fonte.');
