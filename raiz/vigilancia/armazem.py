"""Estado da vigilância em arquivos (sem banco: roda igual no GitHub Actions, no servidor e no computador).

    publico/                       vai aberto para o Release (dado público cruzado; nada pessoal, nada de cliente)
        alertas/alertas_AAAA-MM.parquet   alertas de imóvel, um arquivo por mês em que a Raíz os viu
        ibama_espelho.parquet             SEQ_TAD, hash, ativo, cancelado, desembargado (sem nome nem CPF/CNPJ)
        fontes.json                       última leitura, cursor e erro de cada fonte
        rodadas.jsonl                     uma linha por rodada diária (contagens)
    privado/                       vai cifrado para o Release (chave em RAIZ_VIGILANCIA_CHAVE)
        alertas/alertas_AAAA-MM.parquet   alertas de projeto
        marcacoes.parquet                 verdadeiro ou falso de cada alerta (só acréscimo)
        eventos.parquet                   aviso à Verra, relatório enviado, aviso ao cliente aprovado... (só acréscimo)
        perdas_registro.parquet           número fixo de cada evento de perda (URTX_LE1, URTX_LE2...)
    entrada/                       marcações e eventos que chegaram pela API e ainda não entraram no estado

Alertas nunca mudam depois de gravados (são previsões congeladas); o que muda vem nas marcações e nos eventos.
Arquivo por mês: a rodada diária só regrava o mês corrente.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import secrets
from pathlib import Path

import pandas as pd

from raiz.vigilancia.aprendizado import COLUNAS_MARCACAO
from raiz.vigilancia.cruzamento import COLUNAS_ALERTA
from raiz.vigilancia.fontes import data as _data

COLUNAS_EVENTO = ["evento_id", "alvo", "alvo_id", "tipo", "data", "quem", "nota", "registrado_em"]
TIPOS_EVENTO = {
    "perda": (
        "verra_avisada",  # aviso por e-mail à Verra (30 dias)
        "relatorio_enviado",  # relatório de perda entregue (2 anos)
        "descoberta_informada",  # data de descoberta diferente da que a Raíz calculou (com justificativa)
        "perda_descartada",  # não é evento de perda (ex.: colheita prevista no plano)
        "perda_reaberta",
        "nota",
    ),
    "aviso": ("aviso_aprovado", "aviso_enviado", "aviso_descartado", "nota"),
}
DATAS = ("data_evento", "publicado_em", "visto_em")


def _escrever_parquet(df: pd.DataFrame, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(f"{caminho.name}.{os.getpid()}.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, caminho)


def _escrever_texto(texto: str, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(f"{caminho.name}.{os.getpid()}.tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, caminho)


def _datas(df: pd.DataFrame) -> pd.DataFrame:
    for c in DATAS:
        if c in df:
            df[c] = df[c].map(_data)
    return df


class Armazem:
    def __init__(self, pasta: Path | str):
        self.pasta = Path(pasta)
        self.publico = self.pasta / "publico"
        self.privado = self.pasta / "privado"
        self.entrada_dir = self.pasta / "entrada"
        for p in (self.publico / "alertas", self.privado / "alertas", self.entrada_dir):
            p.mkdir(parents=True, exist_ok=True)
        self._cache: tuple[tuple, pd.DataFrame] | None = None

    # ------------------------------------------------------------------ alertas

    def _arquivos_alertas(self) -> list[Path]:
        return sorted((self.publico / "alertas").glob("alertas_*.parquet")) + sorted(
            (self.privado / "alertas").glob("alertas_*.parquet")
        )

    def alertas(self, alvo_tipo: str | None = None, alvo_id: str | None = None) -> pd.DataFrame:
        arqs = self._arquivos_alertas()
        assinatura = tuple((str(a), a.stat().st_mtime_ns) for a in arqs)
        if self._cache is None or self._cache[0] != assinatura:
            partes = [pd.read_parquet(a) for a in arqs]
            partes = [p for p in partes if len(p)]
            df = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=COLUNAS_ALERTA)
            self._cache = (assinatura, _datas(df))
        df = self._cache[1]
        if alvo_tipo is not None:
            df = df[df["alvo_tipo"] == alvo_tipo]
        if alvo_id is not None:
            df = df[df["alvo_id"] == alvo_id]
        return df

    def gravar_alertas(self, novos: pd.DataFrame) -> pd.DataFrame:
        """Acrescenta os alertas que ainda não existem (pelo alerta_id). Devolve só os que entraram."""
        if novos is None or not len(novos):
            return pd.DataFrame(columns=COLUNAS_ALERTA)
        existentes = set(self.alertas()["alerta_id"])
        entram = novos[~novos["alerta_id"].isin(existentes)].drop_duplicates("alerta_id")
        if not len(entram):
            return entram
        for (lado, mes), g in entram.groupby(
            [
                entram["alvo_tipo"].map(lambda t: "privado" if t == "projeto" else "publico"),
                entram["visto_em"].map(lambda d: _data(d).strftime("%Y-%m")),
            ]
        ):
            arq = self.pasta / lado / "alertas" / f"alertas_{mes}.parquet"
            antigo = pd.read_parquet(arq) if arq.exists() else pd.DataFrame(columns=COLUNAS_ALERTA)
            junto = pd.concat([antigo, g[COLUNAS_ALERTA]], ignore_index=True) if len(antigo) else g[COLUNAS_ALERTA]
            _escrever_parquet(junto.reset_index(drop=True), arq)
        self._cache = None
        return entram

    # ------------------------------------------------------------------ marcações e eventos (só acréscimo)

    def _tabela(self, nome: str, colunas: list[str]) -> pd.DataFrame:
        arq = self.privado / f"{nome}.parquet"
        return pd.read_parquet(arq) if arq.exists() else pd.DataFrame(columns=colunas)

    def _acrescentar(self, nome: str, colunas: list[str], linhas: list[dict], chave: str) -> int:
        if not linhas:
            return 0
        antigo = self._tabela(nome, colunas)
        novo = pd.DataFrame(linhas, columns=colunas)
        novo = novo[~novo[chave].isin(set(antigo[chave]))].drop_duplicates(chave)
        if not len(novo):
            return 0
        junto = pd.concat([antigo, novo], ignore_index=True) if len(antigo) else novo
        _escrever_parquet(junto, self.privado / f"{nome}.parquet")
        return len(novo)

    def marcacoes(self) -> pd.DataFrame:
        return self._tabela("marcacoes", COLUNAS_MARCACAO)

    def gravar_marcacoes(self, linhas: list[dict]) -> int:
        return self._acrescentar("marcacoes", COLUNAS_MARCACAO, linhas, "marcacao_id")

    def eventos(self) -> pd.DataFrame:
        return self._tabela("eventos", COLUNAS_EVENTO)

    def gravar_eventos(self, linhas: list[dict]) -> int:
        return self._acrescentar("eventos", COLUNAS_EVENTO, linhas, "evento_id")

    def registro_perdas(self) -> pd.DataFrame:
        return self._tabela("perdas_registro", ["projeto_id", "numero", "alerta_raiz", "criado_em"])

    def gravar_registro_perdas(self, df: pd.DataFrame) -> None:
        _escrever_parquet(df.reset_index(drop=True), self.privado / "perdas_registro.parquet")

    # ------------------------------------------------------------------ entradas da API (pendentes)

    def nova_entrada(self, tipo: str, registro: dict) -> Path:
        """Guarda uma marcação ou um evento que chegou pela API. Entra no estado na próxima rodada (ou já, com
        incorporar_entradas). As telas já enxergam as entradas pendentes."""
        if tipo not in ("marcacao", "evento"):
            raise ValueError("tipo de entrada desconhecido")
        nome = f"entrada_{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%S}_{secrets.token_hex(4)}.json"
        caminho = self.entrada_dir / nome
        _escrever_texto(json.dumps({"tipo": tipo, "registro": registro}, ensure_ascii=False), caminho)
        return caminho

    def entradas(self) -> list[tuple[Path, dict]]:
        out = []
        for p in sorted(self.entrada_dir.glob("entrada_*.json")):
            try:
                out.append((p, json.loads(p.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                continue
        return out

    def pendentes(self, tipo: str) -> list[dict]:
        return [e["registro"] for _, e in self.entradas() if e.get("tipo") == tipo]

    def limpar_entradas_incorporadas(self) -> int:
        """Apaga as entradas locais que a rodada já juntou ao estado (servidor depois de baixar o estado novo)."""
        marc = set(self.marcacoes()["marcacao_id"])
        ev = set(self.eventos()["evento_id"])
        n = 0
        for p, e in self.entradas():
            reg = e.get("registro") or {}
            if reg.get("marcacao_id") in marc or reg.get("evento_id") in ev:
                p.unlink(missing_ok=True)
                n += 1
        return n

    def incorporar_entradas(self) -> dict:
        marc = [e["registro"] for _, e in self.entradas() if e.get("tipo") == "marcacao"]
        ev = [e["registro"] for _, e in self.entradas() if e.get("tipo") == "evento"]
        n = {"marcacoes": self.gravar_marcacoes(marc), "eventos": self.gravar_eventos(ev)}
        for p, _ in self.entradas():
            p.unlink(missing_ok=True)
        return n

    # ------------------------------------------------------------------ fontes, espelho do Ibama e rodadas

    def fontes(self) -> dict:
        arq = self.publico / "fontes.json"
        return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}

    def gravar_fontes(self, d: dict) -> None:
        _escrever_texto(json.dumps(d, ensure_ascii=False, indent=1, default=str), self.publico / "fontes.json")

    def espelho_ibama(self) -> pd.DataFrame | None:
        arq = self.publico / "ibama_espelho.parquet"
        return pd.read_parquet(arq) if arq.exists() else None

    def gravar_espelho_ibama(self, df: pd.DataFrame) -> None:
        _escrever_parquet(df, self.publico / "ibama_espelho.parquet")

    def registrar_rodada(self, d: dict) -> None:
        arq = self.publico / "rodadas.jsonl"
        with open(arq, "a", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")

    def rodadas(self, ultimas: int = 30) -> list[dict]:
        arq = self.publico / "rodadas.jsonl"
        if not arq.exists():
            return []
        linhas = arq.read_text(encoding="utf-8").splitlines()[-ultimas:]
        return [json.loads(x) for x in linhas if x.strip()]

    def gravar_privado_json(self, nome: str, dado) -> None:
        _escrever_texto(json.dumps(dado, ensure_ascii=False, indent=1, default=str), self.privado / nome)

    def ler_privado_json(self, nome: str, padrao=None):
        arq = self.privado / nome
        return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else padrao
