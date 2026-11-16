"""Histórico imutável local/S3/Release: repetição, falhas e arquivos hostis."""

import gzip
import hashlib
import io
import json
import shutil
import tarfile

import boto3
import httpx
import pytest
from moto import mock_aws

from raiz.aprendizado import transporte as T
from raiz.aprendizado.captura import Captura
from raiz.aprendizado.retratos import guardar, validar_retrato
from raiz.executor.armazem import ArmazemLocal, ArmazemRelease, ArmazemS3


def _retrato(pasta, uf="PA", municipio=1504950, ha=0.3):
    cap = Captura(uf, municipio)
    cap.entrada("flag", {"cod_imovel": f"{uf}-TESTE-HISTORICO", "ha": ha, "mb_pasto_2023_ha": ha})
    r = guardar(cap, "flag", pasta)
    return pasta / uf / str(municipio) / f"{r['retrato_hash']}.json.gz"


def _sha(dados):
    return hashlib.sha256(dados).hexdigest()


class GitHubHistoricoFalso:
    """Simula APIs de metadados/bytes separadas e paginação curta de propósito."""

    def __init__(self):
        self.releases = {1: {"id": 1, "tag_name": "dados-privados", "draft": True}}
        self.privado = False
        self.tag_oculta = False
        self.assets = {}
        self.bytes = {}
        self.chamadas = []
        self.downloads = 0
        self.uploads = 0
        self.falhar_upload = False

    def release(self, tag, draft=True):
        rid = max(self.releases) + 1
        self.releases[rid] = {"id": rid, "tag_name": tag, "draft": draft}
        return rid

    def asset(self, rid, nome, dados):
        aid = max(self.assets, default=0) + 1
        self.assets[aid] = {
            "id": aid,
            "name": nome,
            "size": len(dados),
            "state": "uploaded",
            "digest": f"sha256:{_sha(dados)}",
            "release_id": rid,
        }
        self.bytes[aid] = dados
        return self.assets[aid]

    def pacote(self, rid, uf, membros):
        dados = T._pacote(membros)
        return self.asset(rid, f"historico_{uf}_{_sha(dados)}.tar.gz", dados)

    def _pagina(self, req, itens):
        pagina = int(req.url.params.get("page", 1))
        ini = (pagina - 1) * 2
        cabecalhos = {"Link": '<https://api.github.com/pagina-seguinte>; rel="next"'} if ini + 2 < len(itens) else {}
        return httpx.Response(200, json=itens[ini : ini + 2], headers=cabecalhos)

    def __call__(self, req):
        assert req.headers.get("authorization") == "Bearer teste"
        path = req.url.path.removeprefix("/repos/org/repo").lstrip("/")
        self.chamadas.append((req.method, path, dict(req.url.params)))
        assert req.method != "DELETE", "histórico não pode apagar assets"
        if req.method == "GET" and path == "":
            return httpx.Response(200, json={"private": self.privado})
        if req.method == "GET" and path.removeprefix("releases/").isdigit():
            rid = int(path.removeprefix("releases/"))
            return httpx.Response(200, json=self.releases[rid])
        if req.method == "GET" and path == "releases":
            return self._pagina(req, list(self.releases.values()))
        if req.method == "GET" and path.startswith("releases/tags/"):
            tag = path.removeprefix("releases/tags/")
            rel = next((x for x in self.releases.values() if x["tag_name"] == tag), None)
            return httpx.Response(200, json=rel) if rel and not self.tag_oculta else httpx.Response(404)
        if req.method == "POST" and path == "releases":
            payload = json.loads(req.content)
            assert payload["make_latest"] == "false"
            assert payload["draft"] is True
            rid = self.release(payload["tag_name"], draft=payload["draft"])
            return httpx.Response(201, json=self.releases[rid])
        if path.startswith("releases/assets/"):
            aid = int(path.rsplit("/", 1)[1])
            if aid not in self.assets:
                return httpx.Response(404)
            if req.headers.get("accept") == "application/octet-stream":
                self.downloads += 1
                return httpx.Response(200, content=self.bytes[aid])
            return httpx.Response(200, json=self.assets[aid])
        if path.endswith("/assets"):
            rid = int(path.split("/")[1])
            itens = [x for x in self.assets.values() if x["release_id"] == rid]
            if req.method == "GET":
                return self._pagina(req, itens)
            self.uploads += 1
            if self.falhar_upload:
                return httpx.Response(500, text="conteúdo remoto não deve aparecer no erro")
            nome = req.url.params["name"]
            if any(x["name"] == nome for x in itens):
                return httpx.Response(422)
            return httpx.Response(201, json=self.asset(rid, nome, req.content))
        pytest.fail(f"rota de teste desconhecida: {req.method} {path}")


def _github(tmp_path, falso, token="teste"):
    return ArmazemRelease(
        "org/repo",
        tag="dados-privados",
        privado=True,
        espelho=tmp_path / "espelho",
        token=token,
        cliente=httpx.Client(transport=httpx.MockTransport(falso)),
    )


def test_local_publica_espelha_deduplica_e_filtra_uf(tmp_path):
    spool = tmp_path / "spool"
    pa = _retrato(spool)
    _retrato(spool, "AC", 1200013)
    a = ArmazemLocal(tmp_path / "remoto")
    assert T.publicar(spool, a, "pa") == {"publicados": 1, "existentes": 0, "pacotes": 0}
    remoto = a.raiz / "historico" / pa.relative_to(spool)
    inode = remoto.stat().st_ino
    assert T.publicar(spool, a, "PA")["existentes"] == 1
    assert remoto.stat().st_ino == inode
    T.publicar(spool, a)
    destino = tmp_path / "destino"
    caminhos = T.sincronizar(a, destino, ["pa"])
    assert caminhos == [destino / pa.relative_to(spool)]
    assert validar_retrato(caminhos[0]) == validar_retrato(pa)
    assert T.sincronizar(a, destino, ["PA"]) == caminhos


def test_local_recusa_adulteracao_e_escape_sem_substituir(tmp_path):
    spool = tmp_path / "spool"
    p = _retrato(spool)
    a = ArmazemLocal(tmp_path / "remoto")
    T.publicar(spool, a)
    remoto = a.raiz / "historico" / p.relative_to(spool)
    remoto.write_bytes(gzip.compress(b"{}", mtime=0))
    corrompido = remoto.read_bytes()
    with pytest.raises(ValueError, match="adulterado"):
        T.publicar(spool, a)
    assert remoto.read_bytes() == corrompido
    with pytest.raises(ValueError, match="adulterado"):
        T.sincronizar(a, tmp_path / "destino")
    remoto.write_bytes(p.read_bytes())
    fora = tmp_path / "fora"
    fora.mkdir()
    destino = tmp_path / "escape"
    destino.mkdir()
    (destino / "PA").symlink_to(fora, target_is_directory=True)
    with pytest.raises(ValueError, match="fora do destino"):
        T.sincronizar(a, destino)
    assert not list(fora.rglob("*.json.gz"))


@mock_aws
def test_s3_gravacao_condicional_e_integridade_do_existente(tmp_path):
    cli = boto3.client("s3", region_name="us-east-1")
    cli.create_bucket(Bucket="historico-teste")
    a = ArmazemS3("historico-teste", "prefixo", cliente=cli)
    spool = tmp_path / "spool"
    p = _retrato(spool)
    assert T.publicar(spool, a)["publicados"] == 1
    assert T.publicar(spool, a)["existentes"] == 1
    caminhos = T.sincronizar(a, tmp_path / "destino")
    assert len(caminhos) == 1 and caminhos[0].read_bytes() == p.read_bytes()
    chave = "prefixo/historico/" + p.relative_to(spool).as_posix()
    cli.put_object(Bucket=a.balde, Key=chave, Body=b"adulterado")
    with pytest.raises(ValueError, match="adulterado"):
        T.publicar(spool, a)
    assert cli.get_object(Bucket=a.balde, Key=chave)["Body"].read() == b"adulterado"


def test_release_separado_recibos_sem_varrer_historico_e_repeticao_sem_recibo(tmp_path):
    spool = tmp_path / "spool"
    p = _retrato(spool)
    falso = GitHubHistoricoFalso()
    falso.release("historico-2020-01-01")
    a = _github(tmp_path, falso)
    assert T.publicar(spool, a) == {"publicados": 1, "existentes": 0, "pacotes": 1}
    assert all(x["release_id"] != 1 for x in falso.assets.values())
    assert falso.downloads == 1
    assert T.publicar(spool, a) == {"publicados": 0, "existentes": 1, "pacotes": 0}
    assert falso.downloads == 1 and falso.uploads == 1
    # Criar o primeiro draft pode listar metadados, nunca baixa os pacotes antigos.
    assert not any(p.endswith("/assets") and m == "GET" for m, p, _ in falso.chamadas)
    # Executor novo não baixa histórico inteiro: pacote igual colide e é conferido.
    novo = tmp_path / "novo"
    copia = novo / p.relative_to(spool)
    copia.parent.mkdir(parents=True)
    shutil.copyfile(p, copia)
    T.publicar(novo, a)
    assert len(falso.assets) == 1 and falso.downloads == 2 and falso.uploads == 2
    asset = next(iter(falso.assets.values()))
    asset["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="digest"):
        T.publicar(spool, a)
    assert falso.uploads == 2


def test_release_sincroniza_paginas_deduplica_e_baixa_cada_pacote_uma_vez(tmp_path):
    spool = tmp_path / "spool"
    p = _retrato(spool)
    q = _retrato(spool, ha=0.4)
    nome = p.relative_to(spool).as_posix()
    falso = GitHubHistoricoFalso()
    rids = [falso.release(f"historico-2020-01-0{dia}") for dia in (1, 2, 3)]
    falso.asset(1, "raiz_PA.tar.gz", b"produto atual separado")
    falso.pacote(rids[0], "PA", {nome: p.read_bytes()})
    falso.asset(rids[2], "ignorado-a", b"a")
    falso.asset(rids[2], "ignorado-b", b"b")
    falso.pacote(rids[2], "PA", {nome: p.read_bytes(), q.relative_to(spool).as_posix(): q.read_bytes()})
    a = _github(tmp_path, falso)
    destino = tmp_path / "destino"
    caminhos = T.sincronizar(a, destino)
    assert len(caminhos) == 2 and falso.downloads == 2
    assert T.sincronizar(a, destino) == caminhos and falso.downloads == 2
    caminhos[0].unlink()
    assert T.sincronizar(a, destino) == caminhos and falso.downloads == 3
    assert any(p == "releases" and params.get("page") == "2" for _, p, params in falso.chamadas)
    assert any(p == f"releases/{rids[2]}/assets" and params.get("page") == "2" for _, p, params in falso.chamadas)


def test_falha_no_upload_preserva_spool_e_nao_grava_recibo(tmp_path):
    spool = tmp_path / "spool"
    p = _retrato(spool)
    falso = GitHubHistoricoFalso()
    falso.falhar_upload = True
    a = _github(tmp_path, falso)
    with pytest.raises(RuntimeError, match="HTTP 500") as ex:
        T.publicar(spool, a)
    assert "conteúdo remoto" not in str(ex.value)
    assert p.exists() and not list((spool / ".recibos").glob("*.json"))
    falso.falhar_upload = False
    assert T.publicar(spool, a)["publicados"] == 1
    assert len(list((spool / ".recibos").glob("*.json"))) == 1


def _hostil(nome, corpo, tipo=tarfile.REGTYPE, pax=None, duplicado=False):
    bruto = io.BytesIO()
    with tarfile.open(fileobj=bruto, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for _ in range(2 if duplicado else 1):
            membro = tarfile.TarInfo(nome)
            membro.size, membro.type, membro.mode = len(corpo), tipo, 0o444
            membro.pax_headers = pax or {}
            if tipo == tarfile.SYMTYPE:
                membro.linkname = "../fora"
            tar.addfile(membro, io.BytesIO(corpo))
    return gzip.compress(bruto.getvalue(), mtime=0)


@pytest.mark.parametrize("problema", ["travessia", "link", "duplicata", "metadados", "outra-uf", "hash"])
def test_rejeita_pacotes_hostis_antes_de_instalar_qualquer_arquivo(tmp_path, problema):
    spool = tmp_path / "spool"
    p = _retrato(spool)
    nome, corpo = p.relative_to(spool).as_posix(), p.read_bytes()
    opcoes = {}
    if problema == "travessia":
        nome = "../fora.json.gz"
    elif problema == "link":
        opcoes["tipo"] = tarfile.SYMTYPE
    elif problema == "duplicata":
        opcoes["duplicado"] = True
    elif problema == "metadados":
        opcoes["pax"] = {"comentario": "conteúdo arbitrário proibido"}
    elif problema == "outra-uf":
        nome = nome.replace("PA/", "AC/")
    else:
        corpo = gzip.compress(b"{}", mtime=0)
    dados = _hostil(nome, corpo, **opcoes)
    falso = GitHubHistoricoFalso()
    rid = falso.release("historico-2020-01-01")
    falso.asset(rid, f"historico_PA_{_sha(dados)}.tar.gz", dados)
    destino = tmp_path / "destino"
    with pytest.raises(ValueError):
        T.sincronizar(_github(tmp_path, falso), destino)
    assert not list(destino.rglob("*.json.gz"))
    assert not list((destino / ".recibos").glob("*.json"))


def test_limite_de_tamanho_antes_de_leitura_e_lotes_deterministicos(tmp_path, monkeypatch):
    spool = tmp_path / "spool"
    a = _retrato(spool)
    b = _retrato(spool, ha=0.4)
    membros = {p.relative_to(spool).as_posix(): p.read_bytes() for p in (a, b)}
    assert T._pacote(membros) == T._pacote(dict(reversed(list(membros.items()))))
    monkeypatch.setattr(T, "MAX_MEMBROS", 1)
    lotes = list(T._lotes({p.relative_to(spool).as_posix(): p for p in (a, b)}))
    assert len(lotes) == 2 and all(len(m) == 1 for _, m in lotes)
    remoto = ArmazemLocal(tmp_path / "remoto")
    T.publicar(spool, remoto)
    monkeypatch.setattr(T, "MAX_RETRATO", 10)
    with pytest.raises(ValueError, match="limite"):
        T.sincronizar(remoto, tmp_path / "destino")
    assert not list((tmp_path / "destino").rglob("*.json.gz"))


def test_caminho_municipal_incorreto_e_retrato_modificado_sao_recusados(tmp_path):
    spool = tmp_path / "spool"
    p = _retrato(spool)
    novo = p.parent.parent / "1500001" / p.name
    novo.parent.mkdir()
    p.rename(novo)
    with pytest.raises(ValueError, match="município"):
        T.publicar(spool, ArmazemLocal(tmp_path / "remoto"))
    assert not list((tmp_path / "remoto").rglob("*.json.gz"))
    novo.rename(p)
    p.write_bytes("texto que não pode aparecer no erro".encode())
    with pytest.raises(ValueError, match="adulterado") as ex:
        T.publicar(spool, ArmazemLocal(tmp_path / "remoto"))
    assert "texto que" not in str(ex.value)


def test_hash_externo_e_cabecalho_tar_excessivo_sao_recusados(tmp_path, monkeypatch):
    spool = tmp_path / "spool"
    p = _retrato(spool)
    nome = p.relative_to(spool).as_posix()
    falso = GitHubHistoricoFalso()
    rid = falso.release("historico-2020-01-01")
    asset = falso.pacote(rid, "PA", {nome: p.read_bytes()})
    falso.bytes[asset["id"]] = b"bytes remotos alterados"
    with pytest.raises(ValueError, match="hash do pacote"):
        T.sincronizar(_github(tmp_path, falso), tmp_path / "destino")
    assert not list((tmp_path / "destino").rglob("*.json.gz"))
    # Um cabeçalho PAX gigante é contido antes de tarfile carregar seus metadados.
    dados = _hostil(nome, p.read_bytes(), pax={"comentario": "x" * 20000})
    monkeypatch.setattr(T, "MAX_PACOTE", 4096)
    with pytest.raises(ValueError, match="limite descomprimido"):
        T._abrir_pacote(dados, "PA")


@pytest.mark.parametrize("alteracao", ["gzip", "linkname", "sobras_tar"])
def test_envelope_externo_nao_pode_carregar_dados_pessoais(tmp_path, alteracao):
    spool = tmp_path / "spool"
    p = _retrato(spool)
    arquivos = {p.relative_to(spool).as_posix(): p.read_bytes()}
    bruto = T._tar_bytes(arquivos)
    if alteracao == "gzip":
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, filename="PessoaQueNaoPodePublicar", mode="wb", mtime=0) as f:
            f.write(bruto)
        pacote = buf.getvalue()
    elif alteracao == "linkname":
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            info = tarfile.TarInfo(next(iter(arquivos)))
            info.size, info.mode, info.linkname = len(p.read_bytes()), 0o444, "PessoaQueNaoPodePublicar"
            tar.addfile(info, io.BytesIO(p.read_bytes()))
        pacote = gzip.compress(buf.getvalue(), mtime=0)
    else:
        pacote = gzip.compress(bruto + b"PessoaQueNaoPodePublicar", mtime=0)
    with pytest.raises(ValueError):
        T._abrir_pacote(pacote, "PA")


@pytest.mark.parametrize("operacao", ["publicar", "sincronizar"])
def test_historico_exige_token_e_destino_privado_antes_de_acessar(tmp_path, operacao):
    spool = tmp_path / "spool"
    _retrato(spool)
    falso = GitHubHistoricoFalso()
    a = _github(tmp_path, falso, token="")

    def rodar():
        return T.publicar(spool, a) if operacao == "publicar" else T.sincronizar(a, tmp_path / "destino")

    with pytest.raises(PermissionError, match="TOKEN"):
        rodar()
    assert not falso.chamadas
    a.token, a.privado = "teste", False
    with pytest.raises(PermissionError, match="privado"):
        rodar()
    assert not falso.chamadas


def test_draft_por_listagem_e_visibilidade_reconferida_no_recibo(tmp_path):
    spool = tmp_path / "spool"
    _retrato(spool)
    falso = GitHubHistoricoFalso()
    a = _github(tmp_path, falso)
    T.publicar(spool, a)
    falso.tag_oculta = True
    assert T.publicar(spool, a)["existentes"] == 1
    diario = next(x for x in falso.releases.values() if x["tag_name"].startswith("historico-"))
    diario["draft"] = False
    for rodar in (lambda: T.publicar(spool, a), lambda: T.sincronizar(a, tmp_path / "destino")):
        with pytest.raises(PermissionError, match="aberto"):
            rodar()
    assert falso.uploads == 1 and falso.downloads == 1
    falso.privado = True
    assert T.publicar(spool, a)["existentes"] == 1


def test_erro_de_rede_do_historico_nao_expoe_url_assinada(tmp_path):
    def falhar(req):
        raise httpx.ReadError("https://exemplo.invalid?assinatura=conteudo-restrito", request=req)

    a = _github(tmp_path, falhar)
    with pytest.raises(RuntimeError, match="comunicação") as erro:
        T.sincronizar(a, tmp_path / "destino")
    assert "assinatura" not in str(erro.value)
