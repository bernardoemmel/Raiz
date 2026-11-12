#!/usr/bin/env node
/** Compatibilidade do site estático: lotes financeiros exigem a API autenticada. */
import path from "node:path"
import { pathToFileURL } from "node:url"

export async function baixarLotes(_opcoes = {}) {
  // Não baixar, ler nem sobrescrever snapshots locais: podem pertencer ao motor privado.
  // O build gera seu próprio marcador público constante, sem consultar esses arquivos.
  return "ausente"
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await baixarLotes()
  console.log("[lotes] Lotes financeiros estão disponíveis somente pela API autenticada; nenhum download ou alteração local foi feito.")
}
