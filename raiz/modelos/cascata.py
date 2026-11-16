"""Cascata ABC: o modelo local responde; só a dúvida sobe.

    A = Qwen3-4B no llama.cpp (custo de API zero)      B = Claude Haiku 5.5 (triagem)
    C = Claude Sonnet 5.5 (juiz) ou, sem juiz, a fila de revisão do fundador

Rota (raiz/regras/padroes/cascata.yaml, E7 passo 10):
- O Qwen só faz classificação curta (poucos campos, todos de lista fechada ou sim/não, resposta curta, sem chamada
  de ferramenta). O resto vai para a nuvem: o Haiku responde sozinho (via "direto"); se falhar ou recusar, o
  Sonnet; sem resposta válida, a fila de revisão.

Classificação curta:
- Com corte de confiança calibrado para a tarefa (cascata_cortes.yaml, `raiz modelos calibrar`): se a confiança do
  Qwen (logprobs) chega ao corte, vale a resposta dele (via "confianca"). Só os 20 a 30% menos confiantes sobem.
- Sem corte, ou abaixo dele: A e B votam. Válidos e concordando, vale a resposta (via "acordo").
- Desacordo, ou um dos dois falhou/recusou: pergunta ao C. Se o C concordar com um voto válido, vale o C (via
  "juiz"). Se o C não concordar com ninguém, ou falhar, o caso vai para a fila de revisão (via "revisao").
- Uma tarefa pode deixar o C decidir sozinho (juiz_decide_sozinho=True) quando não há voto válido para conferir.

Toda decisão fica em operacao.decisao_cascata, com o custo somado, a rota, a confiança do Qwen e a versão da regra e
dos cortes. Respostas de pedido com dado pessoal não são guardadas; na fila de revisão fica só a referência.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from psycopg.types.json import Jsonb
from sqlalchemy import Connection, text

from raiz.modelos import chamar, rastro, rota
from raiz.modelos.base import Modelo, Pedido, Resposta
from raiz.privacidade import mascarar

Comparador = Callable[[dict, dict], bool]


def _norm(v):
    return v.strip().lower() if isinstance(v, str) else v


def comparador_por_campos(campos: list[str], tolerancia: float = 0.0) -> Comparador:
    """Concorda se os campos escolhidos batem (texto sem caixa nem espaço; número dentro da tolerância)."""

    def igual(a: dict, b: dict) -> bool:
        for c in campos:
            x, y = a.get(c), b.get(c)
            if isinstance(x, int | float) and isinstance(y, int | float) and not isinstance(x, bool):
                if abs(x - y) > tolerancia:
                    return False
            elif _norm(x) != _norm(y):
                return False
        return True

    return igual


@dataclass
class ResultadoCascata:
    via: str  # confianca | acordo | juiz | direto | revisao
    dados: dict | None  # decisão final; None quando foi para revisão
    respostas: dict[str, Resposta] = field(default_factory=dict)
    custo_usd: Decimal = Decimal(0)
    revisao_id: int | None = None
    decisao_id: int | None = None
    rota: str = "local"  # local (classificação curta) | nuvem
    confianca: float | None = None  # do Qwen, quando respondeu com logprobs
    corte: float | None = None  # corte calibrado da tarefa, se havia
    versao: str | None = None  # versão da regra de rota e dos cortes


class Cascata:
    def __init__(
        self,
        a: Modelo,
        b: Modelo,
        juiz: Modelo | None = None,
        comparar: Comparador | None = None,
        campos: list[str] | None = None,
        tolerancia: float = 0.0,
        juiz_decide_sozinho: bool = False,
        politica: dict | None = None,
        cortes: dict | None = None,
    ):
        self.a, self.b, self.juiz = a, b, juiz
        self._comparar = comparar or (comparador_por_campos(campos, tolerancia) if campos else None)
        self.juiz_decide_sozinho = juiz_decide_sozinho
        self._politica, self._cortes = politica, cortes

    def politica(self) -> dict:
        return self._politica if self._politica is not None else rota.politica()

    def cortes(self) -> dict:
        return self._cortes if self._cortes is not None else rota.cortes()

    def _concordam(self, pedido: Pedido, x: dict, y: dict) -> bool:
        cmp = self._comparar or comparador_por_campos(pedido.esquema.get("required", list(x)))
        return cmp(x, y)

    def decidir(self, pedido: Pedido, con: Connection | None = None) -> ResultadoCascata:
        pol, cs = self.politica(), self.cortes()
        # a rota só vale quando o A é o modelo local de verdade
        no_local, motivo = rota.cabe_no_local(pedido, pol) if self.a.provedor == "local" else (True, "")
        corte = rota.corte_da_tarefa(pedido.tarefa, cs, self.a.nome) if no_local else None
        with rastro.contexto(pedido, f"cascata:{pedido.tarefa}"):
            if not no_local:
                out = self._nuvem(pedido, pol, motivo, con)
            else:
                ra = chamar(self.a, pedido, "A", con)
                if corte is not None and ra.ok and ra.confianca is not None and ra.confianca >= corte:
                    out = ResultadoCascata("confianca", ra.dados, {"A": ra})
                else:
                    rb = chamar(self.b, pedido, "B", con)
                    res = {"A": ra, "B": rb}
                    if ra.ok and rb.ok and self._concordam(pedido, ra.dados, rb.dados):
                        out = ResultadoCascata("acordo", ra.dados, res)
                    else:
                        out = self._desempate(pedido, res, con)
                out.confianca = ra.confianca
        out.rota = "local" if no_local else "nuvem"
        out.corte = corte
        out.versao = f"{pol.get('versao')}|{cs.get('versao')}"
        out.custo_usd = sum((r.custo_usd or Decimal(0)) for r in out.respostas.values())
        if con is not None:
            self._gravar(con, pedido, out)
        return out

    def _nuvem(self, pedido: Pedido, pol: dict, motivo: str, con) -> ResultadoCascata:
        """Tarefa que não é classificação curta: um modelo da nuvem responde sozinho; o outro é a reserva."""
        papeis = {"triagem": ("B", self.b), "juiz": ("C", self.juiz)}
        regra = pol.get("nuvem") or {}
        res: dict[str, Resposta] = {}
        for nome in (regra.get("primeiro", "triagem"), regra.get("reserva", "juiz")):
            papel, m = papeis.get(nome, (None, None))
            if m is None or papel in res:
                continue
            r = chamar(m, pedido, papel, con)
            res[papel] = r
            if r.ok:
                return ResultadoCascata("direto", r.dados, res)
        texto = f"nuvem sem resposta válida (fora do modelo local: {motivo})"
        return ResultadoCascata("revisao", None, res, revisao_id=self._revisao(con, pedido, res, texto))

    def _desempate(self, pedido: Pedido, res: dict[str, Resposta], con) -> ResultadoCascata:
        validos = [r for r in res.values() if r.ok]
        motivo = "desacordo entre A e B" if len(validos) == 2 else "voto barato faltando (falha ou recusa)"
        if self.juiz is None:
            return ResultadoCascata("revisao", None, res, revisao_id=self._revisao(con, pedido, res, motivo))
        rc = chamar(self.juiz, pedido, "C", con)
        res["C"] = rc
        if rc.ok and any(self._concordam(pedido, rc.dados, r.dados) for r in validos):
            return ResultadoCascata("juiz", rc.dados, res)
        if rc.ok and not validos and self.juiz_decide_sozinho:
            return ResultadoCascata("juiz", rc.dados, res)
        motivo = f"{motivo}; juiz {'discordou dos dois' if rc.ok else 'falhou: ' + (rc.erro or '')}"
        return ResultadoCascata("revisao", None, res, revisao_id=self._revisao(con, pedido, res, motivo))

    @staticmethod
    def _respostas_json(pedido: Pedido, res: dict[str, Resposta]) -> dict | None:
        if pedido.pessoal:
            return None
        return {
            k: {"modelo": r.modelo, "dados": r.dados, "erro": r.erro, "recusou": r.recusou, "confianca": r.confianca}
            for k, r in res.items()
        }

    def _revisao(self, con, pedido: Pedido, res: dict[str, Resposta], motivo: str) -> int | None:
        if con is None:
            return None
        conteudo = {"tarefa": pedido.tarefa, "cod_imovel": pedido.cod_imovel}
        if pedido.pessoal:
            conteudo["aviso"] = "pedido com dado pessoal: ver a conversa original, nada copiado aqui"
        else:
            conteudo["mensagem"] = mascarar(pedido.mensagem)
            conteudo["respostas"] = self._respostas_json(pedido, res)
        return con.execute(
            text("""insert into operacao.fila_revisao (tarefa, chave, motivo, conteudo)
                    values (:t, :c, :m, :x) returning id"""),
            dict(t=pedido.tarefa, c=pedido.cod_imovel, m=mascarar(motivo), x=Jsonb(_mascarar_json(conteudo))),
        ).scalar_one()

    def _gravar(self, con: Connection, pedido: Pedido, out: ResultadoCascata) -> None:
        h = hashlib.sha256(
            json.dumps([pedido.sistema, pedido.mensagem, pedido.esquema], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        resp = self._respostas_json(pedido, out.respostas)
        out.decisao_id = con.execute(
            text("""insert into operacao.decisao_cascata
                    (tarefa, chave, entrada_hash, via, respostas, decisao, revisao_id, custo_usd, rota, confianca,
                     corte, regra_versao)
                    values (:t, :c, :h, :v, :r, :d, :rv, :cu, :ro, :cf, :co, :rg) returning id"""),
            dict(
                t=pedido.tarefa,
                c=pedido.cod_imovel,
                h=h,
                v=out.via,
                r=Jsonb(_mascarar_json(resp)) if resp is not None else None,
                d=Jsonb(_mascarar_json(out.dados)) if out.dados is not None and not pedido.pessoal else None,
                rv=out.revisao_id,
                cu=out.custo_usd,
                ro=out.rota,
                cf=out.confianca,
                co=out.corte,
                rg=out.versao,
            ),
        ).scalar_one()


def _mascarar_json(x):
    return json.loads(mascarar(json.dumps(x, ensure_ascii=False, default=str)))


def resolver_revisao(con: Connection, revisao_id: int, resposta: dict, quem: str) -> None:
    """O revisor (fundador) decide; fica gravado quem confirmou e quando (padrão HMDA)."""
    n = con.execute(
        text("""update operacao.fila_revisao set estado = 'resolvida', resposta = :r, resolvida_por = :q,
                resolvida_em = now() where id = :i and estado = 'aberta'"""),
        dict(r=Jsonb(_mascarar_json(resposta)), q=quem, i=revisao_id),
    ).rowcount
    if n != 1:
        raise ValueError(f"revisão {revisao_id} não está aberta")


def cascata_padrao(**kw) -> Cascata:
    """A = Qwen3-4B local, B = Claude Haiku 5.5, C = Claude Sonnet 5.5; rota e cortes lidos dos YAML a cada decisão."""
    from raiz.modelos import modelo_conversa, modelo_local, modelo_triagem

    return Cascata(modelo_local(), modelo_triagem(), modelo_conversa(), **kw)
