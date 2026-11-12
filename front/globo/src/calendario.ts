import { fonteCalendario } from "../../compartilhado/calendario"

export const calendario = fonteCalendario({
  api: import.meta.env.VITE_RAIZ_API,
  json: import.meta.env.VITE_RAIZ_EVENTOS_URL,
  ics: import.meta.env.VITE_RAIZ_EVENTOS_ICS_URL,
  base: import.meta.env.BASE_URL,
})
