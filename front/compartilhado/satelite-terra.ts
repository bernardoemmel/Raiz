/** A mediana reúne cenas de um período; não deve receber a data de uma única foto. */
export function legendaCenaSatelite(meta: { data_cena: string; metodo: string; satelite: string }): string {
  const data = (iso: string) => {
    const partes = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
    return partes ? `${partes[3]}/${partes[2]}/${partes[1]}` : iso
  }
  const intervalo = /^(\d{4}-\d{2}-\d{2}) a (\d{4}-\d{2}-\d{2})$/.exec(meta.data_cena)
  const periodo = intervalo ? `de ${data(intervalo[1])} a ${data(intervalo[2])}` : `em ${data(meta.data_cena)}`
  const composicao = meta.metodo === "mediana" ? "Composição mediana de cenas " : ""
  return `${composicao}${meta.satelite} ${periodo}`
}
