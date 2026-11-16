/** Contrato privado: só terra, fontes e referências de documentos. */
export interface FontePasta { documento_id: string; localizador: string; data_referencia: string }
export interface MedidaPasta { valor: string | null; unidade: string; natureza: string; fontes: FontePasta[] }
export interface PrecoPasta { valor: string | null; moeda: string | null; unidade: string | null; natureza: string | null; periodo: { inicio: string; fim: string } | null; fontes: FontePasta[] }
export interface CreditoPasta { metodo: string; area: MedidaPasta | null; p10: MedidaPasta | null; p50: MedidaPasta | null; p90: MedidaPasta | null; periodo: { inicio: string; fim: string } | null; modelo_versao: string | null; fontes: FontePasta[]; previsao_id: string }
export interface ImovelPasta { codigo_car: string; area_elegivel: MedidaPasta | null; titulo: { nivel: string; situacao: string; fontes: FontePasta[] } | null; garantia: { situacao: string; fontes: FontePasta[] } | null; creditos: CreditoPasta[]; preco: PrecoPasta | null }
export interface PastaFiadorDados {
  pasta_id: string; versao_id: string; numero: number; anterior_id: string | null; tipo_alteracao: string; motivo: string; assinatura: string; registrada_em: string
  dados: { pedido_id: string; opcao: string; data_corte: string; imoveis: ImovelPasta[]; documentos: { id: string; referencia: string; tipo: string; estado: string; emitido_em: string | null; valido_ate: string | null; sem_vencimento: boolean; conferido_em: string | null; sha256: string | null }[] }
  validacao: { pronto: boolean; regra_versao: string; conferido_em: string; falhas: { codigo: string; campo: string; mensagem: string; documento_id: string | null }[]; campos: { campo: string; fontes: FontePasta[] }[]; documentos: { id: string; tipo: string; estado: string; valido_ate: string | null }[] }
  previsoes: { codigo_car: string; metodo: string; referencia: string; relacoes: { tipo: string; referencia: string }[] }[]
}
export interface HistoricoPasta { versoes: { id: string; numero: number; anterior_id: string | null; tipo: string; motivo: string; registrada_em: string }[] }
export function linhasPasta(pasta: PastaFiadorDados) {
  return pasta.dados.imoveis.flatMap((i, pos) => {
    const ids = new Set(pasta.validacao.campos.filter((c) => c.campo.startsWith(`imoveis/${pos}/`)).flatMap((c) => c.fontes.map((f) => f.documento_id)))
    const documentos = pasta.dados.documentos.filter((d) => ids.has(d.id))
    const pendente = pasta.validacao.falhas.some((f) => f.campo.startsWith(`imoveis/${pos}/`) || !!f.documento_id && ids.has(f.documento_id) || !f.campo.startsWith('imoveis/'))
    return (documentos.length ? documentos : [null]).map((d) => ({
      car: i.codigo_car, area: i.area_elegivel?.valor == null ? 'Não informada' : `${numeroPasta(i.area_elegivel.valor)} ha`,
      estagio: pendente ? 'Com pendência' : 'Conferido', titulo: rotuloPasta(i.titulo?.nivel ?? 'Não conferido'),
      documento: d ? `${rotuloPasta(d.tipo)}; ${d.referencia}` : 'Documento obrigatório ausente',
      validade: d?.valido_ate ?? (d?.sem_vencimento ? 'Sem vencimento declarado' : 'Não informada'),
      estado_documento: pasta.validacao.documentos.find((v) => v.id === d?.id)?.estado ?? 'Ausente',
    }))
  })
}

/** Preserva a precisão decimal recebida; não converte preços para ponto flutuante. */
export function numeroPasta(valor: string | null | undefined): string {
  if (valor == null) return 'Não informado'
  if (!/^-?[0-9]+(?:\.[0-9]+)?$/.test(valor)) return valor
  const [inteiro, fracao] = valor.split('.')
  return BigInt(inteiro).toLocaleString('pt-BR') + (fracao ? `,${fracao}` : '')
}

const ROTULOS: Record<string, string> = {
  conferencia_concluida: 'Conferência concluída', documento_apresentado: 'Documento apresentado',
  nao_verificado: 'Não verificado', titularidade: 'Titularidade', garantia: 'Garantia',
  area_elegivel: 'Área elegível', previsao: 'Previsão', preco: 'Preço',
  inclusao: 'Inclusão', correcao: 'Correção', substituicao: 'Substituição', retirada: 'Retirada', nova_previsao: 'Nova previsão',
  regeneracao_assistida: 'Regeneração assistida', semeadura_direta: 'Semeadura direta', plantio_total: 'Plantio total',
  agrofloresta: 'Agrofloresta', silvipastoril: 'Silvipastoril',
}
export const rotuloPasta = (valor: string) => ROTULOS[valor] ?? valor.replaceAll('_', ' ')

export interface PastasDaFichaDados {
  codigo_car: string
  pastas: { pedido_id: string; opcao: string; pasta_id: string; versao_id: string; numero: number; pronto: boolean; data_corte: string; imovel: ImovelPasta }[]
}
