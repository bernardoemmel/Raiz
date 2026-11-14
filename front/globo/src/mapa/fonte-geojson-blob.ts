/** URLs locais duram somente até o worker do mapa terminar de ler o GeoJSON. */
export class FonteGeojsonBlob {
  private urls = new Set<string>()

  async aplicar(fonte: { setData(url: string): Promise<void> }, dados: Blob): Promise<void> {
    const url = URL.createObjectURL(dados)
    this.urls.add(url)
    try { await fonte.setData(url) }
    finally {
      if (this.urls.delete(url)) URL.revokeObjectURL(url)
    }
  }

  encerrar() {
    for (const url of this.urls) URL.revokeObjectURL(url)
    this.urls.clear()
  }
}
