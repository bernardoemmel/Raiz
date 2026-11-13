"""Importação interna da pasta conferida; não oferece entrada de modelos Jinja."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pydantic import ValidationError

from .esquema import Retificacao
from .servico import registrar
from .validacao import validar


def _salvar(caminho, resultado):
    fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        os.fchmod(f.fileno(), 0o600)
        json.dump(resultado, f, ensure_ascii=False, indent=2)


def _entrada(bruto):
    def unico(pares):
        d = {}
        for chave, valor in pares:
            if chave in d:
                raise ValueError("Campo duplicado")
            d[chave] = valor
        return d

    return Retificacao.model_validate(json.loads(bruto, object_pairs_hook=unico))


def main(argv=None):
    p = argparse.ArgumentParser(description="Valida ou registra dados conferidos da pasta do lote.")
    p.add_argument("arquivo", type=Path)
    p.add_argument("--registrar", action="store_true", help="Anexa uma versão no banco privado configurado.")
    p.add_argument("--relatorio", required=True, type=Path, help="JSON privado com falhas e referências.")
    args = p.parse_args(argv)
    try:
        if args.arquivo.resolve() == args.relatorio.resolve() or args.arquivo.stat().st_size > 20_000_000:
            raise ValueError("Entrada inválida")
        retificacao = _entrada(args.arquivo.read_bytes())
        if args.registrar:
            from raiz.banco import engine

            resultado = registrar(engine(), retificacao)
            pronto = resultado["validacao"]["pronto"]
        else:
            resultado = validar(retificacao.dados).model_dump(mode="json")
            pronto = resultado["pronto"]
        # Modo privado desde a criação; relatório nunca vai para o stdout/log do operador.
        _salvar(args.relatorio, resultado)
        print("Pasta conferida." if pronto else "Pasta com pendências; confira o relatório privado.")
        return 0 if pronto else 1
    except (ValueError, OSError) as erro:
        # Não reutilizar relatório aprovado quando a entrada seguinte falhou.
        # Chaves extras também podem conter dados pessoais: nunca copiá-las para o relatório.
        campos = []
        if isinstance(erro, ValidationError):
            from . import esquema

            conhecidos = {
                nome
                for cls in vars(esquema).values()
                if isinstance(cls, type) and issubclass(cls, esquema.Fechado)
                for nome in cls.model_fields
            }
            for falha in erro.errors(include_input=False, include_url=False, include_context=False):
                caminho = "/".join(
                    str(v) if isinstance(v, int) or v in conhecidos else "campo_nao_permitido" for v in falha["loc"]
                )
                campos.append(
                    {
                        "campo": caminho,
                        "codigo": "formato_invalido",
                        "mensagem": "Campo obrigatório ausente ou fora do contrato.",
                    }
                )
        if args.arquivo.resolve() != args.relatorio.resolve():
            try:
                _salvar(
                    args.relatorio,
                    {
                        "pronto": False,
                        "falhas": campos
                        or [{"campo": "entrada", "codigo": "entrada_invalida", "mensagem": "Entrada não validada."}],
                    },
                )
            except OSError:
                pass
        print(
            "Entrada inválida ou operação não permitida. Confira o contrato da pasta; "
            "valores não foram registrados no log."
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
