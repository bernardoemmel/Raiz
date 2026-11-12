import { X } from "lucide-react"
import { useState } from "react"
import { UFS } from "../../../../compartilhado/formato"
import { BIOMAS, escopoDoPedido, mudarEscopoPedido, type EscopoPedido } from "../../../../compartilhado/pedidos/territorio"
import type { CamposPedido } from "../../../../compartilhado/pedidos/tipos"
import { CoberturaPedido } from "./CoberturaPedido"

export function OndePedido({ onde, mudar, mudarAlcance }: { onde: CamposPedido["onde"]; mudar: (onde: CamposPedido["onde"]) => void; mudarAlcance: () => void }) {
  const [escopo, setEscopo] = useState<EscopoPedido>(() => escopoDoPedido(onde))
  const biomas = <fieldset className="campo-grupo">
    <legend>{escopo === "biomas" ? "Biomas do pedido" : "Refinar os estados por bioma"}</legend>
    <div className="opcoes-linha">{BIOMAS.map((bioma) => <label key={bioma} className="opcao">
      <input type="checkbox" checked={onde.biomas.includes(bioma)} onChange={() => mudar({ ...onde, biomas: onde.biomas.includes(bioma) ? onde.biomas.filter((b) => b !== bioma) : [...onde.biomas, bioma] })} />
      <span>{bioma}</span>
    </label>)}</div>
    {!onde.biomas.length && <p className="legenda-frase">Todos os biomas. Os filtros da API consideram cada fazenda uma única vez.</p>}
  </fieldset>
  return <>
    <fieldset className="campo-grupo">
      <legend>Alcance do pedido</legend>
      {([["estados", "Um ou mais estados"], ["biomas", "Um ou mais biomas"], ["brasil", "Brasil inteiro"]] as const).map(([valor, rotulo]) => <label key={valor} className="opcao">
        <input type="radio" name="alcance" checked={escopo === valor} onChange={() => { setEscopo(valor); mudar(mudarEscopoPedido(onde, valor)); mudarAlcance() }} />
        <span>{rotulo}</span>
      </label>)}
    </fieldset>
    {escopo === "estados" && <>
      <label className="campo">
        <span id="np-estado-rotulo">Adicionar estado</span>
        <select aria-labelledby="np-estado-rotulo" value="" onChange={(e) => e.target.value && mudar({ ...onde, ufs: [...new Set([...onde.ufs, e.target.value])] })}>
          <option value="">Escolher um estado</option>
          {Object.entries(UFS).sort((a, b) => a[1].localeCompare(b[1], "pt-BR")).map(([uf, nome]) => <option key={uf} value={uf} disabled={onde.ufs.includes(uf)}>{nome}</option>)}
        </select>
      </label>
      {onde.ufs.length ? <ul className="fichas-escolhidas" aria-label="Estados escolhidos">{onde.ufs.map((uf) => <li key={uf}>{UFS[uf]}<button type="button" aria-label={`Tirar ${UFS[uf]}`} onClick={() => mudar({ ...onde, ufs: onde.ufs.filter((u) => u !== uf) })}><X size={16} aria-hidden="true" /></button></li>)}</ul> : <p className="legenda-frase">Sem estado escolhido: a consulta inclui todos os estados já processados.</p>}
      <details open={onde.biomas.length > 0}><summary>Refinar por bioma (opcional)</summary>{biomas}</details>
    </>}
    {escopo === "biomas" && biomas}
    {escopo === "brasil" && <p>Busca nos estados já processados de todo o Brasil, sem restrição de bioma. As partes ainda não processadas ficam indicadas abaixo.</p>}
    <CoberturaPedido onde={onde} />
  </>
}
