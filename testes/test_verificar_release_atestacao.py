"""Política OR entre workflows sem acesso à rede ou aos dados dos Releases."""

import argparse
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from scripts import verificar_release_dados as V


def resposta(*, nome="produto.json", digest="a" * 64, predicate="https://slsa.dev/provenance/v1", codigo=0):
    return SimpleNamespace(
        returncode=codigo,
        stdout=json.dumps(
            [
                {
                    "verificationResult": {
                        "statement": {
                            "predicateType": predicate,
                            "subject": [{"name": nome, "digest": {"sha256": digest}}],
                        }
                    }
                }
            ]
        ).encode(),
        stderr=b"conteudo-que-nao-deve-aparecer",
    )


def instalar_respostas(monkeypatch, respostas):
    chamadas = []

    def executar(cmd, **kwargs):
        chamadas.append((cmd, kwargs))
        resultado = respostas[len(chamadas) - 1]
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    monkeypatch.setattr(V.subprocess, "run", executar)
    return chamadas


def conferir_politica(chamadas, arquivo):
    for indice, (cmd, kwargs) in enumerate(chamadas):
        assert cmd == [
            "gh",
            "attestation",
            "verify",
            str(arquivo),
            "--repo",
            "bernardoemmel/Raiz",
            "--signer-workflow",
            V.WORKFLOWS_PERMITIDOS[indice],
            "--format",
            "json",
            "--deny-self-hosted-runners",
        ]
        assert kwargs == {"capture_output": True, "timeout": 240, "check": False}


@pytest.mark.parametrize("vencedor", [0, 1])
def test_aceita_cada_workflow_com_politica_completa_e_registra_vencedor(tmp_path, monkeypatch, vencedor):
    assert V.WORKFLOWS_PERMITIDOS == (
        "bernardoemmel/Raiz/.github/workflows/publicar-metadados.yml",
        "bernardoemmel/Raiz/.github/workflows/processar-estados.yml",
    )
    respostas = [resposta(codigo=1)] * vencedor + [resposta()]
    chamadas = instalar_respostas(monkeypatch, respostas)
    arquivo = tmp_path / "arquivo"
    resultado = V.atestacao(arquivo, "produto.json", "a" * 64, "gh")
    assert resultado == {
        "verificadas": 1,
        "workflow": V.WORKFLOWS_PERMITIDOS[vencedor],
        "self_hosted_recusado": True,
    }
    assert len(chamadas) == vencedor + 1
    conferir_politica(chamadas, arquivo)


@pytest.mark.parametrize(
    "respostas",
    [
        [resposta(codigo=1), resposta(codigo=1)],
        [resposta(digest="b" * 64), resposta(nome="outro.json")],
        [resposta(predicate="https://slsa.dev/provenance/v0.2"), resposta(predicate="invalido")],
        [SimpleNamespace(returncode=0, stdout=b"[nao-json", stderr=b"segredo"), resposta(codigo=1)],
        [SimpleNamespace(returncode=0, stdout=b"[]", stderr=b"segredo"), resposta(codigo=1)],
        [SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"segredo"), resposta(codigo=1)],
    ],
    ids=["gh-recusou-ambos", "nome-e-hash-separados", "predicate-incorreto", "json-malformado", "vazio", "objeto"],
)
def test_recusa_provas_insuficientes_sem_fallback_irrestrito(tmp_path, monkeypatch, capsys, respostas):
    chamadas = instalar_respostas(monkeypatch, respostas)
    arquivo = tmp_path / "arquivo"
    with pytest.raises(V.FalhaSegura) as erro:
        V.atestacao(arquivo, "produto.json", "a" * 64, "gh")
    assert len(chamadas) == 2
    conferir_politica(chamadas, arquivo)
    assert str(erro.value) in {
        "atestacao_ausente_ou_invalida",
        "atestacao_sem_subject_nome_e_hash",
        "atestacao_resposta_invalida",
    }
    assert capsys.readouterr() == ("", "")


def test_nao_combina_subjects_distintos_da_mesma_assinatura(tmp_path, monkeypatch):
    resultado = resposta(digest="b" * 64)
    payload = json.loads(resultado.stdout)
    payload[0]["verificationResult"]["statement"]["subject"].append(
        {"name": "outro.json", "digest": {"sha256": "a" * 64}}
    )
    resultado.stdout = json.dumps(payload).encode()
    instalar_respostas(monkeypatch, [resultado, resposta(codigo=1)])
    with pytest.raises(V.FalhaSegura, match="subject"):
        V.atestacao(tmp_path / "arquivo", "produto.json", "a" * 64, "gh")


@pytest.mark.parametrize(
    "primeira",
    [
        subprocess.TimeoutExpired("gh", 240, output=b"segredo"),
        SimpleNamespace(returncode=0, stdout=b"malformado", stderr=b"segredo"),
        resposta(nome="produto-anterior.json"),
    ],
    ids=["timeout", "json-invalido", "subject-antigo"],
)
def test_segundo_workflow_independe_de_falha_segura_do_primeiro(tmp_path, monkeypatch, primeira):
    chamadas = instalar_respostas(monkeypatch, [primeira, resposta()])
    arquivo = tmp_path / "arquivo"
    assert V.atestacao(arquivo, "produto.json", "a" * 64, "gh")["workflow"] == V.WORKFLOWS_PERMITIDOS[1]
    conferir_politica(chamadas, arquivo)


@pytest.mark.parametrize("vencedor", [0, 1])
def test_privado_exige_subject_do_conteudo_em_cada_workflow(tmp_path, monkeypatch, vencedor):
    respostas = [resposta(codigo=1)] * vencedor + [resposta(nome="privado-sha256-" + "a" * 64)]
    chamadas = instalar_respostas(monkeypatch, respostas)
    arquivo = tmp_path / "arquivo"
    resultado = V.atestacao(arquivo, "nome-ficticio.json", "a" * 64, "gh", privado=True)
    assert resultado["verificadas"] == 1
    assert resultado["workflow"] == V.WORKFLOWS_PERMITIDOS[vencedor]
    conferir_politica(chamadas, arquivo)
    assert all("nome-ficticio.json" not in cmd for cmd, _ in chamadas)


@pytest.mark.parametrize(
    "subject,digest",
    [
        ("nome-ficticio.json", "a" * 64),
        ("privado-sha256-" + hashlib.sha256(b"nome-ficticio.json").hexdigest(), "a" * 64),
        ("privado-sha256-" + "b" * 64, "a" * 64),
        ("privado-sha256-" + "a" * 64, "b" * 64),
    ],
    ids=["nome-original", "hash-do-nome", "subject-de-outro-conteudo", "digest-de-outro-conteudo"],
)
def test_privado_recusa_nome_legado_ou_digest_divergente(tmp_path, monkeypatch, subject, digest):
    chamadas = instalar_respostas(monkeypatch, [resposta(nome=subject, digest=digest)] * 2)
    arquivo = tmp_path / "arquivo"
    with pytest.raises(V.FalhaSegura, match="subject"):
        V.atestacao(arquivo, "nome-ficticio.json", "a" * 64, "gh", privado=True)
    assert len(chamadas) == 2
    conferir_politica(chamadas, arquivo)


def test_publico_nao_aceita_alias_privado_no_lugar_do_nome(tmp_path, monkeypatch):
    instalar_respostas(monkeypatch, [resposta(nome="privado-sha256-" + "a" * 64)] * 2)
    with pytest.raises(V.FalhaSegura, match="subject"):
        V.atestacao(tmp_path / "arquivo", "produto.json", "a" * 64, "gh", privado=False)


@pytest.mark.parametrize("digest", [None, "", "a" * 63, "A" * 64, "z" * 64, "a" * 64 + "\n"])
def test_privado_bloqueia_digest_invalido_antes_de_executar_gh(tmp_path, monkeypatch, digest):
    chamadas = instalar_respostas(monkeypatch, [])
    with pytest.raises(V.FalhaSegura, match="digest_privado_invalido"):
        V.atestacao(tmp_path / "arquivo", "nome-ficticio.json", digest, "gh", privado=True)
    assert chamadas == []


@pytest.mark.parametrize("escopo", ["publico", "privado"])
def test_escopo_propaga_politica_de_subject_ao_verificador(tmp_path, monkeypatch, escopo):
    import httpx

    from raiz.executor import publicacao_aberta

    # Dados sintéticos, API totalmente simulada e métodos HTTP limitados a GET.
    nome, dados = "estados.json", b"{}"
    digest = hashlib.sha256(dados).hexdigest()
    asset = {"id": 1, "name": nome, "size": len(dados), "digest": "sha256:" + digest}
    privado = escopo == "privado"
    assunto = f"privado-sha256-{digest}" if privado else nome
    chamadas = instalar_respostas(monkeypatch, [resposta(nome=assunto, digest=digest)])

    def responder(req):
        assert req.method == "GET"
        if req.url.path.endswith("/releases/assets/1"):
            return httpx.Response(200, content=dados)
        if req.url.path.endswith("/releases/2/assets"):
            return httpx.Response(200, json=[asset])
        if "/releases/tags/" in req.url.path:
            return httpx.Response(200, json={"id": 2, "draft": privado})
        if req.url.path == "/repos/bernardoemmel/Raiz":
            return httpx.Response(200, json={"private": False})
        raise AssertionError("rota inesperada")

    cliente = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: cliente(transport=httpx.MockTransport(responder), **kw))
    monkeypatch.setattr(publicacao_aberta, "validar_asset_publico", lambda *a, **kw: None)
    monkeypatch.setenv("GH_TOKEN", "credencial-ficticia")
    monkeypatch.delenv("RAIZ_DADOS_PRIVADOS_TOKEN", raising=False)
    # Garante o destino fictício controlado pelo teste, sem consumir configuração do host.
    from raiz.executor import armazem

    monkeypatch.setattr(armazem, "destino_privado", lambda: None)
    args = argparse.Namespace(
        repo_publico="bernardoemmel/Raiz",
        tag_publica="dados",
        sem_atestacao=False,
        gh="gh",
        relatorio=tmp_path / "relatorio.json",
    )
    relatorio = {"escopos": {}}
    V.executar_escopo(
        args,
        escopo,
        V.Cache(tmp_path / "cache"),
        relatorio,
        SimpleNamespace(arquivos_produto=lambda a: [asset]),
        SimpleNamespace(base_release=lambda *a, **kw: None),
    )
    resultado = relatorio["escopos"][escopo]
    assert resultado["arquivos"][nome]["atestacao"]["verificadas"] == 1
    assert resultado["erros"] == [{"etapa": "escopo", "codigo": "catalogo_indice_ou_cartao_ausente"}]
    conferir_politica(chamadas, tmp_path / "cache" / "objetos" / digest)
