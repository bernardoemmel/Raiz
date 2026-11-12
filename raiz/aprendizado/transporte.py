"""Publica e espelha retratos imutáveis, sem regravar os pacotes correntes do motor.

Local/S3 usam historico/UF/município/hash.json.gz. O GitHub recebe lotes de até
64 MiB em Releases diários privados (rascunhos, ou repositório privado).
O destino e cada Release são conferidos antes do acesso; não há leitura anônima.
Só grava recibos após conferir o objeto
remoto; nunca chama o método de substituição de assets do ArmazemRelease.
Recibos evitam reenvio no mesmo executor. Sem recibo, um pacote determinístico
pode ser repetido em outro dia ou agrupamento; os retratos continuam deduplicados
pelo hash, sem baixar todo o histórico durante a publicação.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import gzip
import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
from pathlib import Path

from raiz.aprendizado.retratos import MAX_COMPRIMIDO, descomprimir, validar_retrato
from raiz.executor.armazem import Armazem, ArmazemLocal, ArmazemRelease, ArmazemS3

MAX_PACOTE = 64 * 1024 * 1024
MAX_RETRATO = MAX_COMPRIMIDO
MAX_MEMBROS = 10000
CAMINHO = re.compile(r"([A-Z]{2})/(\d{7})/([a-f0-9]{64})\.json\.gz")
ASSET = re.compile(r"historico_([A-Z]{2})_([a-f0-9]{64})\.tar\.gz")
TAG = re.compile(r"historico-\d{4}-\d{2}-\d{2}")


def _sha(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _partes(nome: str) -> tuple[str, str, str]:
    m = CAMINHO.fullmatch(nome)
    if not m:
        raise ValueError("caminho de retrato inválido")
    return m.groups()


def _destino(raiz: Path, relativo: str) -> Path:
    _partes(relativo)
    raiz = raiz.resolve()
    p = raiz / relativo
    if p.is_symlink() or raiz not in p.resolve().parents:
        raise ValueError("caminho de retrato fora do destino")
    return p


def _validar(p: Path, relativo: str) -> dict:
    uf, cod, _ = _partes(relativo)
    if p.is_symlink() or p.stat().st_size > MAX_RETRATO:
        raise ValueError("retrato excede o limite ou usa vínculo simbólico")
    try:
        obj = validar_retrato(p)
    except Exception:  # noqa: BLE001 - não devolver conteúdo pessoal de um arquivo adulterado
        raise ValueError("retrato inválido ou adulterado") from None
    if obj["uf"] != uf or str(obj["municipio"]) != cod:
        raise ValueError("pasta não corresponde ao município do retrato")
    return obj


def _validar_bytes(dados: bytes, relativo: str) -> None:
    if len(dados) > MAX_RETRATO:
        raise ValueError("retrato excede o limite de transporte")
    with tempfile.TemporaryDirectory(prefix="raiz-confere-retrato-") as tmp:
        p = _destino(Path(tmp), relativo)
        p.parent.mkdir(parents=True)
        p.write_bytes(dados)
        _validar(p, relativo)


def _gravar_novo(raiz: Path, relativo: str, dados: bytes) -> bool:
    """Instala com link exclusivo: concorrência nunca substitui arquivo existente."""
    p = _destino(raiz, relativo)
    p.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=p.parent, suffix=".tmp", delete=False) as f:
        temporario = Path(f.name)
        f.write(dados)
        f.flush()
        os.fsync(f.fileno())
    try:
        try:
            os.link(temporario, p)
            return True
        except FileExistsError:
            _validar(p, relativo)
            return False
    finally:
        temporario.unlink(missing_ok=True)


def _identidade(a: Armazem) -> str:
    if isinstance(a, ArmazemRelease):
        valor = ["github-privado-v1", a.repo, a.tag]
    elif isinstance(a, ArmazemS3):
        valor = ["s3", a.balde, a.prefixo, a.cli.meta.endpoint_url]
    elif isinstance(a, ArmazemLocal):
        valor = ["local", str(a.raiz.resolve())]
    else:
        raise TypeError("tipo de armazém não suporta publicação imutável")
    return _sha(json.dumps(valor, sort_keys=True).encode())


@contextlib.contextmanager
def _recibos(pasta: Path, a: Armazem):
    raiz = pasta / ".recibos"
    raiz.mkdir(parents=True, exist_ok=True)
    nome = _identidade(a)
    caminho = raiz / f"{nome}.json"
    with (raiz / f"{nome}.lock").open("a") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        try:
            r = json.loads(caminho.read_text()) if caminho.exists() else {}
        except (ValueError, OSError):
            r = {}
        if (
            not isinstance(r, dict)
            or r.get("formato") != 1
            or not isinstance(r.get("assets"), dict)
            or not isinstance(r.get("retratos"), dict)
        ):
            r = {"formato": 1, "assets": {}, "retratos": {}}

        def salvar():
            with tempfile.NamedTemporaryFile("w", dir=raiz, suffix=".tmp", delete=False) as f:
                tmp = Path(f.name)
                json.dump(r, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.replace(tmp, caminho)
            finally:
                tmp.unlink(missing_ok=True)

        yield r, salvar


def _cabecalhos(a: ArmazemRelease, escrita: bool = False) -> dict:
    if not a.privado:
        raise PermissionError("histórico por CAR exige o armazém privado configurado em RAIZ_DADOS_PRIVADOS_URL")
    if not a.token:
        raise PermissionError("histórico por CAR exige RAIZ_DADOS_PRIVADOS_TOKEN, inclusive para leitura")
    return a._cabecalhos()


def _ok(resposta, operacao: str):
    if not 200 <= resposta.status_code < 300:
        raise RuntimeError(f"{operacao} falhou (HTTP {resposta.status_code})")
    return resposta


@contextlib.contextmanager
def _acesso_privado(armazem: Armazem):
    if isinstance(armazem, ArmazemRelease):
        with armazem._erros_privados("histórico"):
            _cabecalhos(armazem)
            armazem._exigir_privado()
            yield
    else:
        yield


def _conferir_release(a: ArmazemRelease, release_id: int) -> dict:
    """Confere visibilidade atual do alvo, também ao reaproveitar recibos locais."""
    h = _cabecalhos(a)
    repo = _ok(a.cli.get(f"{a.API}/repos/{a.repo}", headers=h), "verificação do arquivo histórico").json()
    rel = _ok(
        a.cli.get(f"{a.API}/repos/{a.repo}/releases/{int(release_id)}", headers=h),
        "verificação do Release histórico",
    ).json()
    if repo.get("private") is not True and rel.get("draft") is not True:
        raise PermissionError("Release histórico está aberto; dados por CAR exigem repositório privado ou rascunho")
    return rel


def _paginas(a: ArmazemRelease, sufixo: str):
    pagina = 1
    while True:
        r = _ok(
            a.cli.get(
                f"{a.API}/repos/{a.repo}/{sufixo}", headers=_cabecalhos(a), params={"per_page": 100, "page": pagina}
            ),
            "listagem do histórico",
        )
        objetos = r.json()
        if not isinstance(objetos, list):
            raise ValueError("resposta inválida ao listar histórico")
        yield from objetos
        if not objetos or (len(objetos) < 100 and "next" not in r.links):
            return
        pagina += 1


def _assets(a: ArmazemRelease, ufs: set[str] | None = None) -> list[dict]:
    out = []
    for rel in _paginas(a, "releases"):
        tag = rel.get("tag_name", "")
        if not isinstance(tag, str) or not TAG.fullmatch(tag):
            continue
        try:
            dt.date.fromisoformat(tag.removeprefix("historico-"))
            rid = int(rel["id"])
        except (ValueError, TypeError, KeyError):
            raise ValueError("metadados inválidos do Release histórico") from None
        _conferir_release(a, rid)
        for asset in _paginas(a, f"releases/{rid}/assets"):
            m = ASSET.fullmatch(asset.get("name", ""))
            if m and (not ufs or m[1] in ufs) and asset.get("state") == "uploaded":
                out.append({**asset, "tag": tag, "uf": m[1], "sha256": m[2], "release_id": rid})
    return out


def _baixar_asset(a: ArmazemRelease, asset: dict) -> bytes:
    if int(asset.get("size", 0)) > MAX_PACOTE:
        raise ValueError("pacote histórico excede o limite de transporte")
    _conferir_release(a, int(asset["release_id"]))
    aid = int(asset["id"])
    with a.cli.stream(
        "GET",
        f"{a.API}/repos/{a.repo}/releases/assets/{aid}",
        headers={**_cabecalhos(a), "Accept": "application/octet-stream"},
    ) as r:
        _ok(r, "download histórico")
        pedacos, tamanho = [], 0
        for bloco in r.iter_bytes():
            tamanho += len(bloco)
            if tamanho > MAX_PACOTE:
                raise ValueError("pacote histórico excede o limite de transporte")
            pedacos.append(bloco)
    dados = b"".join(pedacos)
    if _sha(dados) != asset["sha256"]:
        raise ValueError("hash do pacote histórico não corresponde ao asset")
    return dados


def _abrir_pacote(dados: bytes, uf: str) -> dict[str, bytes]:
    """Não usa extract/extractall; rejeita links, travessia, duplicatas e excesso."""
    out, total = {}, 0
    bruto = descomprimir(dados, MAX_PACOTE)
    try:
        with tarfile.open(fileobj=io.BytesIO(bruto), mode="r|") as tar:
            for membro in tar:
                u, _, _ = _partes(membro.name)
                if (
                    u != uf
                    or not membro.isfile()
                    or membro.type != tarfile.REGTYPE
                    or membro.pax_headers
                    or membro.uid != 0
                    or membro.gid != 0
                    or membro.uname
                    or membro.gname
                    or membro.mtime != 0
                    or membro.mode != 0o444
                    or membro.name in out
                    or membro.size < 0
                    or membro.size > MAX_RETRATO
                ):
                    raise ValueError("membro inválido no pacote histórico")
                total += membro.size + 1024
                if total > MAX_PACOTE or len(out) >= MAX_MEMBROS:
                    raise ValueError("pacote histórico excede o limite descomprimido")
                f = tar.extractfile(membro)
                corpo = f.read(MAX_RETRATO + 1)
                if len(corpo) != membro.size:
                    raise ValueError("membro histórico truncado")
                _validar_bytes(corpo, membro.name)
                out[membro.name] = corpo
    except (tarfile.TarError, EOFError, OSError):
        raise ValueError("pacote histórico inválido") from None
    if not out:
        raise ValueError("pacote histórico vazio")
    if bruto != _tar_bytes(out):
        raise ValueError("tar histórico contém metadados ou preenchimento fora do contrato")
    return out


def _indice(a: ArmazemRelease, r: dict, salvar, destino: Path, ufs: set[str] | None = None):
    """Recibo de um pacote validado só é reutilizado com digest igual no GitHub."""
    arquivos, assets = {}, _assets(a, ufs)
    for asset in assets:
        sha = asset["sha256"]
        recibo = r["assets"].get(sha)
        digest = asset.get("digest")
        if digest is not None and digest != f"sha256:{sha}":
            raise ValueError("digest remoto do histórico diverge do nome do asset")
        if (
            isinstance(recibo, dict)
            and digest == f"sha256:{sha}"
            and recibo.get("asset_id") == asset["id"]
            and recibo.get("tag") == asset["tag"]
        ):
            membros = recibo.get("membros")
            if not isinstance(membros, list) or not membros or any(_partes(m)[0] != asset["uf"] for m in membros):
                raise ValueError("recibo histórico inválido")
        else:
            corpos = _abrir_pacote(_baixar_asset(a, asset), asset["uf"])
            for nome, corpo in corpos.items():
                _gravar_novo(destino, nome, corpo)
            membros = sorted(corpos)
            r["assets"][sha] = {
                "asset_id": asset["id"],
                "release_id": asset["release_id"],
                "tag": asset["tag"],
                "membros": membros,
            }
            salvar()
        for relativo in membros:
            arquivos[relativo] = asset
    return arquivos, assets


def _publicados_recebidos(a: ArmazemRelease, r: dict, selecionados: dict) -> set[str]:
    """Confere só assets dos recibos necessários, sem percorrer Releases antigos."""
    publicados = set()
    hashes = {r["retratos"].get(nome) for nome in selecionados}
    for sha in sorted(x for x in hashes if isinstance(x, str)):
        recibo = r["assets"].get(sha)
        if not isinstance(recibo, dict) or not isinstance(recibo.get("membros"), list):
            continue
        aid = recibo.get("asset_id")
        if not isinstance(aid, int):
            continue
        rid = recibo.get("release_id")
        if not isinstance(rid, int):
            continue  # recibo antigo não comprova o destino privado; reconferir o pacote
        rel = _conferir_release(a, rid)
        if rel.get("tag_name") != recibo.get("tag"):
            raise ValueError("Release diverge do recibo histórico")
        res = a.cli.get(f"{a.API}/repos/{a.repo}/releases/assets/{aid}", headers=_cabecalhos(a))
        if res.status_code == 404:
            continue
        asset = _ok(res, "conferência do recibo histórico").json()
        m = ASSET.fullmatch(asset.get("name", ""))
        if not m or m[2] != sha or asset.get("id") != aid or asset.get("state") != "uploaded":
            raise ValueError("asset remoto diverge do recibo histórico")
        digest = asset.get("digest")
        if digest is None:
            continue  # Sem digest remoto, o recibo não comprova a integridade atual.
        if digest != f"sha256:{sha}":
            raise ValueError("digest remoto do histórico diverge do recibo")
        for nome in recibo["membros"]:
            if _partes(nome)[0] != m[1]:
                raise ValueError("recibo histórico inválido")
            if nome in selecionados:
                publicados.add(nome)
    return publicados


def _release_diario(a: ArmazemRelease) -> dict:
    tag = f"historico-{dt.datetime.now(dt.UTC).date().isoformat()}"
    url = f"{a.API}/repos/{a.repo}/releases"
    h = _cabecalhos(a, escrita=True)

    def existente():
        r = a.cli.get(f"{url}/tags/{tag}", headers=h)
        if r.status_code != 404:
            return _ok(r, "consulta do Release histórico").json()
        # GitHub pode responder 404 por tag para rascunhos; a listagem autenticada os inclui.
        return next((r for r in _paginas(a, "releases") if r.get("tag_name") == tag), None)

    rel = existente()
    if rel is None:
        r = a.cli.post(
            url,
            headers=h,
            json={
                "tag_name": tag,
                "name": tag,
                "draft": True,
                "prerelease": False,
                "make_latest": "false",
                "body": "Retratos históricos privados da Raíz, imutáveis e verificados por SHA-256. "
                "Não publicar este rascunho em repositório aberto.",
            },
        )
        if r.status_code == 422:  # outro executor criou o Release entre as duas chamadas
            rel = existente()
            if rel is None:
                raise RuntimeError("não foi possível localizar o Release histórico concorrente")
        else:
            rel = _ok(r, "criação do Release histórico privado").json()
    return _conferir_release(a, int(rel["id"]))


def _tar_bytes(arquivos: dict[str, bytes]) -> bytes:
    bruto = io.BytesIO()
    with tarfile.open(fileobj=bruto, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for nome, corpo in sorted(arquivos.items()):
            info = tarfile.TarInfo(nome)
            info.size, info.mtime, info.mode = len(corpo), 0, 0o444
            tar.addfile(info, io.BytesIO(corpo))
    return bruto.getvalue()


def _pacote(arquivos: dict[str, bytes]) -> bytes:
    comprimido = gzip.compress(_tar_bytes(arquivos), mtime=0)
    if len(comprimido) > MAX_PACOTE:
        raise ValueError("lote histórico excede o limite de transporte")
    return comprimido


def _lotes(arquivos: dict[str, Path]):
    atual, tamanho, uf_atual = {}, 0, None
    for nome, p in sorted(arquivos.items()):
        uf, _, _ = _partes(nome)
        corpo = p.read_bytes()
        _validar_bytes(corpo, nome)
        peso = len(corpo) + 1024
        if atual and (uf != uf_atual or tamanho + peso > MAX_PACOTE - 65536 or len(atual) >= MAX_MEMBROS):
            yield uf_atual, atual
            atual, tamanho = {}, 0
        atual[nome], tamanho, uf_atual = corpo, tamanho + peso, uf
    if atual:
        yield uf_atual, atual


def _subir_pacote(a: ArmazemRelease, rel: dict, uf: str, arquivos: dict[str, bytes]) -> dict:
    dados = _pacote(arquivos)
    sha = _sha(dados)
    nome = f"historico_{uf}_{sha}.tar.gz"
    _conferir_release(a, int(rel["id"]))
    h = {**_cabecalhos(a, escrita=True), "Content-Type": "application/gzip"}
    res = a.cli.post(
        f"{a.UPLOADS}/repos/{a.repo}/releases/{int(rel['id'])}/assets", params={"name": nome}, headers=h, content=dados
    )
    if res.status_code == 422:  # colisão por publicação concorrente; nunca excluir o asset
        existentes = [x for x in _paginas(a, f"releases/{int(rel['id'])}/assets") if x.get("name") == nome]
        if len(existentes) != 1:
            raise RuntimeError("não foi possível conferir o pacote histórico concorrente")
        asset = existentes[0]
    else:
        asset = _ok(res, "upload histórico").json()
    if asset.get("state") != "uploaded":
        raise RuntimeError("upload histórico ainda não concluído")
    asset = {**asset, "sha256": sha, "uf": uf, "tag": rel["tag_name"], "release_id": int(rel["id"])}
    # Confere bytes reais, inclusive no primeiro upload e na corrida com outro executor.
    _abrir_pacote(_baixar_asset(a, asset), uf)
    return asset


def _publicar_objeto(a: Armazem, relativo: str, p: Path) -> bool:
    chave, dados = f"historico/{relativo}", p.read_bytes()
    _validar_bytes(dados, relativo)
    if isinstance(a, ArmazemLocal):
        return _gravar_novo(a.raiz / "historico", relativo, dados)
    if not isinstance(a, ArmazemS3):
        raise TypeError("armazém inválido para objeto histórico")
    from botocore.exceptions import ClientError

    try:
        a.cli.put_object(
            Bucket=a.balde,
            Key=a._k(chave),
            Body=dados,
            IfNoneMatch="*",
            Metadata={"sha256": _sha(dados), "retrato-sha256": _partes(relativo)[2]},
        )
        novo = True
    except ClientError as ex:
        if str(ex.response.get("Error", {}).get("Code")) not in {"PreconditionFailed", "412"}:
            raise RuntimeError("upload imutável do histórico no S3 falhou") from None
        novo = False
    existente = _ler_objeto(a, relativo)
    if existente is None:
        raise RuntimeError("objeto histórico ausente após upload")
    _validar_bytes(existente, relativo)
    return novo


def _ler_objeto(a: ArmazemLocal | ArmazemS3, relativo: str) -> bytes | None:
    """Limita também leituras de objetos remotos adulterados, antes de alocar."""
    _partes(relativo)
    if isinstance(a, ArmazemLocal):
        p = _destino(a.raiz / "historico", relativo)
        if not p.exists():
            return None
        if p.stat().st_size > MAX_RETRATO:
            raise ValueError("objeto histórico excede o limite de transporte")
        with p.open("rb") as f:
            dados = f.read(MAX_RETRATO + 1)
    else:
        from botocore.exceptions import ClientError

        try:
            obj = a.cli.get_object(Bucket=a.balde, Key=a._k(f"historico/{relativo}"))
        except ClientError as ex:
            if a._nao_existe(ex):
                return None
            raise RuntimeError("leitura do histórico no S3 falhou") from None
        with contextlib.closing(obj["Body"]) as corpo:
            if obj.get("ContentLength", 0) > MAX_RETRATO:
                raise ValueError("objeto histórico excede o limite de transporte")
            dados = corpo.read(MAX_RETRATO + 1)
    if len(dados) > MAX_RETRATO:
        raise ValueError("objeto histórico excede o limite de transporte")
    return dados


def publicar(pasta: Path, armazem: Armazem, uf: str | None = None) -> dict:
    """Publica somente no destino privado; retomar não apaga nem substitui objetos."""
    with _acesso_privado(armazem):
        return _publicar(pasta, armazem, uf)


def _publicar(pasta: Path, armazem: Armazem, uf: str | None = None) -> dict:
    pasta = Path(pasta)
    selecionados = {}
    filtro = {uf.upper()} if uf else None
    for p in sorted(pasta.glob("*/*/*.json.gz")):
        relativo = p.relative_to(pasta).as_posix()
        u, _, _ = _partes(relativo)
        if filtro and u not in filtro:
            continue
        _destino(pasta, relativo)
        _validar(p, relativo)
        selecionados[relativo] = p
    resultado = {"publicados": 0, "existentes": 0, "pacotes": 0}
    if not selecionados:
        return resultado
    with _recibos(pasta, armazem) as (r, salvar):
        if isinstance(armazem, ArmazemRelease):
            existentes = _publicados_recebidos(armazem, r, selecionados)
            pendentes = {k: v for k, v in selecionados.items() if k not in existentes}
            resultado["existentes"] = len(selecionados) - len(pendentes)
            rel = _release_diario(armazem) if pendentes else None
            for u, arquivos in _lotes(pendentes):
                asset = _subir_pacote(armazem, rel, u, arquivos)
                sha = asset["sha256"]
                r["assets"][sha] = {
                    "asset_id": asset["id"],
                    "release_id": asset["release_id"],
                    "tag": asset["tag"],
                    "membros": sorted(arquivos),
                }
                r["retratos"].update({k: sha for k in arquivos})
                salvar()
                resultado["publicados"] += len(arquivos)
                resultado["pacotes"] += 1
        else:
            for nome, p in selecionados.items():
                novo = _publicar_objeto(armazem, nome, p)
                r["retratos"][nome] = "objeto-verificado"
                salvar()
                resultado["publicados" if novo else "existentes"] += 1
    return resultado


def sincronizar(armazem: Armazem, destino: Path, ufs: list[str] | None = None) -> list[Path]:
    """Baixa retratos autenticados e devolve caminhos válidos; legado aberto falha explicitamente."""
    with _acesso_privado(armazem):
        return _sincronizar(armazem, destino, ufs)


def _sincronizar(armazem: Armazem, destino: Path, ufs: list[str] | None = None) -> list[Path]:
    destino = Path(destino)
    filtro = {u.upper() for u in ufs} if ufs else None
    encontrados = set()
    if isinstance(armazem, ArmazemRelease):
        with _recibos(destino, armazem) as (r, salvar):
            arquivos, _ = _indice(armazem, r, salvar, destino, filtro)
            por_asset = {}
            for nome, asset in arquivos.items():
                p = _destino(destino, nome)
                if p.exists():
                    _validar(p, nome)
                    encontrados.add(p)
                else:
                    por_asset[asset["sha256"]] = asset
            for asset in por_asset.values():
                membros = _abrir_pacote(_baixar_asset(armazem, asset), asset["uf"])
                for nome, dados in membros.items():
                    _gravar_novo(destino, nome, dados)
                    encontrados.add(_destino(destino, nome))
    elif isinstance(armazem, ArmazemLocal | ArmazemS3):
        for chave in armazem.listar("historico/"):
            nome = chave.removeprefix("historico/")
            u, _, _ = _partes(nome)
            if filtro and u not in filtro:
                continue
            dados = _ler_objeto(armazem, nome)
            if dados is None:
                raise RuntimeError("objeto histórico desapareceu durante o espelhamento")
            _validar_bytes(dados, nome)
            _gravar_novo(destino, nome, dados)
            encontrados.add(_destino(destino, nome))
    else:
        raise TypeError("tipo de armazém não suporta histórico imutável")
    return sorted(encontrados)
