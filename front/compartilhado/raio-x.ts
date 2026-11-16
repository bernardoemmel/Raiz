/**
 * Raio-X do fazendeiro (ficha do produtor): hectares, faixa de valor e o pedido de contato.
 *
 * Regras:
 * - nunca pede CPF, nome, telefone ou e-mail do dono; o único dado que sai é o código do CAR, que a própria ficha mostra;
 * - a faixa de valor só aparece quando o back-end manda a conta do dono (P50 por hectare e por ano). Sem a faixa mínima
 *   e máxima, a tela diz isso em vez de inventar um intervalo.
 */

export interface PagamentoDoDono {
  /** reais por hectare e por ano, mediana (P50); null quando o município ainda não tem a conta */
  rs_ha_ano_medio: number | null
}

export interface ParaQuemRestaura {
  disponivel: boolean
  /** hectares da área de restauração usada na conta */
  area_ha?: number
  pagamento_dono?: PagamentoDoDono | null
}

export interface RaioX {
  hectares: number
  /** texto pronto: "R$ 12.000 por ano, em média" ou o aviso de que a faixa ainda não existe */
  valor: string
  /** true quando o número veio da conta do back-end */
  temValor: boolean
}

const reais = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 })

/** Hectares que podem voltar a ser mata, inteiros (1 hectare, 12 hectares). */
export function hectaresDoRaioX(carbonoHa: number): number {
  return Math.max(0, Math.round(carbonoHa))
}

export function raioX(carbonoHa: number, paraQuem: ParaQuemRestaura | null | undefined): RaioX {
  const hectares = hectaresDoRaioX(carbonoHa)
  const rs = paraQuem?.disponivel ? paraQuem.pagamento_dono?.rs_ha_ano_medio : null
  const area = paraQuem?.area_ha ?? hectares
  if (rs == null || !Number.isFinite(rs) || !(area > 0)) {
    return {
      hectares,
      valor: "A faixa de valor para a sua área ainda não foi calculada. A Raíz confere com você antes de qualquer número.",
      temValor: false,
    }
  }
  const ano = Math.round(rs * area)
  return {
    hectares,
    valor: `Cerca de ${reais.format(ano)} por ano, em média. A faixa mínima e máxima ainda não foi calculada; não é promessa.`,
    temValor: true,
  }
}

/** E-mail para a Raíz, já com o código do CAR preenchido. O endereço vem de VITE_RAIZ_EMAIL; sem ele, o e-mail abre
 *  sem destinatário e a pessoa escolhe para quem enviar. */
export function mailtoContato(cod: string, municipio: string, uf: string, email?: string): string {
  const assunto = `Quero ser contatado: CAR ${cod}`
  const corpo = [
    "Olá, a Raíz.",
    "",
    `Vi a ficha da minha fazenda no Cadastro Ambiental Rural (CAR) ${cod}, em ${municipio} (${uf}).`,
    "Quero ser contatado para conversar.",
    "",
    "Obrigado.",
  ].join("\n")
  return `mailto:${(email ?? "").trim()}?subject=${encodeURIComponent(assunto)}&body=${encodeURIComponent(corpo)}`
}
