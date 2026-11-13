"""Regressão diária: Claude gravado, MCP real e notas semânticas da referência auditada.

Não é outra medição de pass^4. O VCR exige os mesmos pedidos completos ao agente,
incluindo os resultados atuais do MCP. O juiz não é executado novamente: suas notas
são a referência, e as barreiras determinísticas são recalculadas no banco atual.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import yaml

from raiz.publica.agente_real import HTTP_TRANSITORIOS, RETENTATIVAS_HTTP, Julgamento, hash_json
from raiz.publica.avaliacao import avaliar, carregar_gabarito, ler_execucoes
from scripts.cenarios_agentes import Provedor as ProvedorCenarios
from scripts.julgar_agentes import barreiras
from scripts.verificar_evidencias_agentes import verificar


def _chamadas_http(interacoes: list[dict]) -> list[list[dict]]:
    """Retentativas preservam o pedido e terminam em resposta 200, sem escolher notas."""
    chamadas, atual = [], []
    for interacao in interacoes:
        if atual and interacao["request"] != atual[0]["request"]:
            raise ValueError("retentativa mudou o pedido ao modelo")
        atual.append(interacao)
        status = interacao["response"]["status"]["code"]
        if status == 200:
            chamadas.append(atual)
            atual = []
        elif status not in HTTP_TRANSITORIOS or len(atual) > RETENTATIVAS_HTTP:
            raise ValueError("erro HTTP não reproduzível como retentativa")
    if atual:
        raise ValueError("referência termina sem resposta do modelo")
    return chamadas


class Referencia:
    def __init__(self, pasta: Path):
        verificar(pasta, pasta / "cassetes")
        self.pasta = pasta
        gabarito, sha = carregar_gabarito()
        registros = ler_execucoes(pasta / "execucoes.jsonl")
        apurado = avaliar(registros, gabarito, sha)
        if not apurado["aprovado"]:
            raise ValueError("a referência exige campanha real completa e aprovada")
        relatorio = json.loads((pasta / "relatorio.json").read_text())
        if any(relatorio.get(k) != v for k, v in apurado.items()):
            raise ValueError("relatório diverge das execuções da referência")
        config = json.loads((pasta / "configuracao.json").read_text())
        if hash_json(config) != apurado["configuracao_sha256"]:
            raise ValueError("configuração da referência foi alterada")
        self.modelo = config["modelo"]
        self.modelo_juiz = config["modelo_juiz"]
        self.max_passos = config["max_passos"]
        self.max_tokens = config["max_tokens"]
        self.registros = {(r.tarefa_id, r.tentativa): r for r in registros}
        metricas = relatorio["metricas"]
        self.metricas = {(m["tarefa_id"], m["tentativa"]): m for m in metricas}
        if len(metricas) != len(self.registros) or self.metricas.keys() != self.registros.keys():
            raise ValueError("métricas incompletas ou duplicadas na referência")
        for chave, metrica in self.metricas.items():
            nome = f"{chave[0]}-{chave[1]}"
            for arquivo, esperado in (
                (pasta / "cassetes" / f"{nome}.yaml", metrica["cassete_sha256"]),
                (pasta / f"trace-{nome}.json", metrica["trace_sha256"]),
            ):
                if hashlib.sha256(arquivo.read_bytes()).hexdigest() != esperado:
                    raise ValueError("cassete ou trace da referência foi alterado")
        self.sha256 = hash_json({"relatorio": relatorio, "configuracao": config})

    def cassetes_do_agente(self, destino: Path) -> None:
        """Separa explicitamente inferência do agente e julgamento; não ignora sobras no VCR."""
        if destino.exists():
            raise ValueError("use uma pasta nova para as cassetes de replay")
        destino.mkdir(parents=True, mode=0o700)
        for chave, metrica in self.metricas.items():
            nome = f"{chave[0]}-{chave[1]}.yaml"
            dados = yaml.safe_load((self.pasta / "cassetes" / nome).read_text())
            passos = metrica["passos_modelo"]
            interacoes = dados["interactions"]
            chamadas_http = _chamadas_http(interacoes)
            chamadas_juiz = metrica.get("chamadas_juiz", 1)
            if (
                type(passos) is not int
                or not 1 <= passos <= self.max_passos
                or type(chamadas_juiz) is not int
                or not 0 <= chamadas_juiz <= 3
                or (chamadas_juiz == 0 and any(self.registros[chave].criterios.values()))
                or len(chamadas_http) != passos + chamadas_juiz
            ):
                raise ValueError("quantidade de inferências ou chamadas do juiz diverge da referência")
            for papel, chamadas in (("agente", chamadas_http[:passos]), ("juiz", chamadas_http[passos:])):
                if sum(len(c) - 1 for c in chamadas) != metrica.get(f"retentativas_http_{papel}", 0):
                    raise ValueError("quantidade de retentativas HTTP diverge da referência")
            # Após as inferências vêm o juiz e suas eventuais correções de citação.
            # O original permanece integral na referência para auditoria.
            dados["interactions"] = [i for chamada in chamadas_http[:passos] for i in chamada]
            arquivo = destino / nome
            arquivo.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False))
            arquivo.chmod(0o600)


class ProvedorReplay(ProvedorCenarios):
    """Mesmos cenários, efeitos e OAuth reais; nenhum mock de ferramenta."""

    referencia: Referencia | None = None
    avaliador = "referencia-semantica-e-barreiras-v1"

    @property
    def versao(self):
        return "replay-contrato-v1-" + self._referencia().sha256

    def _referencia(self) -> Referencia:
        if self.referencia is None:
            self.referencia = Referencia(Path(os.environ["RAIZ_REFERENCIA_AGENTES"]))
        return self.referencia

    async def preparar(self, tarefa, tentativa, campanha_id):
        cenario = await super().preparar(tarefa, tentativa, campanha_id)
        cenario.dados["referencia_tentativa"] = tentativa
        return cenario

    async def julgar(self, tarefa, cenario, trace):
        referencia = self._referencia()
        esperado = referencia.registros[tarefa.id, cenario.dados["referencia_tentativa"]]
        if [c["ferramenta"] for c in trace["chamadas"]] != [c.ferramenta for c in esperado.chamadas]:
            raise ValueError("sequência de chamadas diverge da referência")
        cenario.dados["depois"] = await self.snapshot(cenario)
        limites = barreiras(tarefa, cenario.dados, trace, token=cenario.access_token)
        trace["julgamento"] = {
            "versao": self.avaliador,
            "referencia_sha256": referencia.sha256,
            "chamadas_modelo": 0,
            "uso": {"input_tokens": 0, "output_tokens": 0},
            "barreiras": sorted(limites.reprovados),
            "motivos": limites.motivos,
        }
        return Julgamento(
            criterios={
                k: v and k not in limites.reprovados and not limites.violacoes for k, v in esperado.criterios.items()
            },
            violacoes=sorted(limites.violacoes),
            chamadas_nao_autorizadas=sorted(limites.chamadas_nao_autorizadas),
        )


provedor = ProvedorReplay()


def main(argv=None) -> int:
    from raiz.publica.agente_real import main as executar

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--referencia", type=Path, required=True)
    parser.add_argument("--saida", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        referencia = Referencia(args.referencia)
        cassetes = args.saida / "cassetes"
        referencia.cassetes_do_agente(cassetes)
    except Exception:
        print(json.dumps({"aprovado": False, "erro": "Referência real ausente, incompleta ou alterada."}))
        return 2
    anterior = os.environ.get("RAIZ_REFERENCIA_AGENTES")
    os.environ["RAIZ_REFERENCIA_AGENTES"] = str(args.referencia.resolve())
    try:
        return executar(
            [
                "--provider",
                "scripts.reproduzir_agentes:provedor",
                "--modo",
                "replay",
                "--modelo",
                referencia.modelo,
                "--modelo-juiz",
                referencia.modelo_juiz,
                "--max-passos",
                str(referencia.max_passos),
                "--max-tokens",
                str(referencia.max_tokens),
                "--campanha",
                "replay-" + referencia.sha256[:20],
                "--saida",
                str(args.saida),
                "--cassetes",
                str(cassetes),
            ]
        )
    finally:
        if anterior is None:
            os.environ.pop("RAIZ_REFERENCIA_AGENTES", None)
        else:
            os.environ["RAIZ_REFERENCIA_AGENTES"] = anterior


if __name__ == "__main__":
    raise SystemExit(main())
