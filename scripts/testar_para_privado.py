"""Prepara e testa o snapshot estadual privado, sem publicar dados nem diagnósticos.

O CI prepara a pasta em um passo autenticado separado. O pytest recebe apenas
RAIZ_TESTE_PA_PASTA e executa o mesmo caso estadual em um processo sem credenciais.
Os quatro arquivos estão ancorados nos comprovantes imutáveis da rodada concluída.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

RAIZ = Path(__file__).resolve().parents[1]
REPO = "bernardoemmel/Raiz"
RELEASE = 443383695
URL_PRIVADA = f"release-github://{REPO}/dados-privados"
MODELO = "restauracao-2026d+a84f9789"
ORIGEM = "31990520b842fd665152b2c7931b3556a66ca180"
NO_TESTE = "testes/test_lote.py::test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta"
CASO = ("testes.test_lote", "test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta")
PACOTES = ("raiz_PA.tar.gz", "raiz_geo_PA.tar.gz")
LIMITE_METADADOS = 2 * 1024 * 1024
LIMITE_TAR = 3 * 1024**3
HOSTS_DOWNLOAD = frozenset({"api.github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"})


class FalhaPrivada(Exception):
    """Somente mensagens fixas podem atravessar a fronteira do processo privado."""


@dataclass(frozen=True)
class Referencia:
    asset: int
    tamanho: int
    sha256: str


MANIFESTO = Referencia(741030570, 181198, "b29eb3fe8887a676bbf5ad1ea7a040c68a0cc90d0863b27c5d3bd6e9ff34854c")
PLANO = Referencia(740960941, 16600, "c4ebf38619d68fa3823d521eb8cfe793ffa405bc40005c7dc994ce1c78e4d5fa")


def _exigir(condicao: bool) -> None:
    if not condicao:
        raise FalhaPrivada("FALHA: contrato ou integridade do snapshot privado inválidos.")


def _sha(arquivo: Path) -> str:
    with arquivo.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _conferir(arquivo: Path, ref: Referencia) -> None:
    _exigir(arquivo.is_file() and not arquivo.is_symlink() and arquivo.stat().st_size == ref.tamanho)
    _exigir(_sha(arquivo) == ref.sha256)


def _json(arquivo: Path):
    _exigir(arquivo.is_file() and not arquivo.is_symlink() and arquivo.stat().st_size <= LIMITE_METADADOS)
    return json.loads(arquivo.read_bytes())


def _referencia(valor: dict) -> Referencia:
    asset, tamanho, digest = valor.get("asset_id"), valor.get("bytes"), valor.get("sha256")
    _exigir(type(asset) is int and asset > 0 and type(tamanho) is int and 0 < tamanho <= 1024**3)
    _exigir(isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest) is not None)
    return Referencia(asset, tamanho, digest)


def conferir_evento(ambiente: dict[str, str]) -> None:
    """Recusa forks antes de ler token ou fazer qualquer requisição."""
    evento = ambiente.get("GITHUB_EVENT_NAME")
    if ambiente.get("GITHUB_ACTIONS") != "true":
        return
    _exigir(evento in {"push", "pull_request"} and ambiente.get("GITHUB_REPOSITORY") == REPO)
    if evento == "pull_request":
        try:
            dados = _json(Path(ambiente["GITHUB_EVENT_PATH"]))
            origem = dados["pull_request"]["head"]["repo"]["full_name"]
            destino = dados["pull_request"]["base"]["repo"]["full_name"]
        except Exception:
            raise FalhaPrivada("FALHA: não foi possível verificar a origem do PR para o teste privado.") from None
        if origem != REPO or destino != REPO:
            raise FalhaPrivada(
                "BLOQUEADO: PR de fork não recebe dados nem credenciais; "
                "a validação estadual privada não foi executada."
            )


class _SemRedirecionar(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ClientePrivado:
    def __init__(self, ambiente: dict[str, str] | None = None):
        ambiente = dict(os.environ) if ambiente is None else ambiente
        conferir_evento(ambiente)
        if ambiente.get("RAIZ_DADOS_PRIVADOS_URL", URL_PRIVADA) != URL_PRIVADA:
            raise FalhaPrivada("FALHA: destino do snapshot privado não autorizado.")
        self.token = ambiente.get("RAIZ_DADOS_PRIVADOS_TOKEN") or ambiente.get("GH_TOKEN")
        if not self.token:
            raise FalhaPrivada("FALHA: credencial de leitura do snapshot privado ausente.")
        self.opener = urllib.request.build_opener(_SemRedirecionar())

    def _abrir(self, endpoint: str, *, binario: bool = False):
        url = f"https://api.github.com/repos/{REPO}/{endpoint}"
        for tentativa in range(4):
            destino = urllib.parse.urlsplit(url)
            _exigir(
                destino.scheme == "https"
                and destino.hostname in HOSTS_DOWNLOAD
                and destino.port in (None, 443)
                and destino.username is None
                and destino.password is None
            )
            headers = {"Accept": "application/octet-stream" if binario else "application/vnd.github+json"}
            # URL assinada é transitória. Nunca encaminhar Authorization após um redirect.
            if tentativa == 0:
                headers["Authorization"] = f"Bearer {self.token}"
            try:
                return self.opener.open(urllib.request.Request(url, headers=headers), timeout=60)
            except urllib.error.HTTPError as erro:
                with erro:
                    if binario and erro.code in (301, 302, 303, 307, 308) and erro.headers.get("Location"):
                        url = urllib.parse.urljoin(url, erro.headers["Location"])
                        continue
                raise FalhaPrivada("FALHA: acesso autenticado ao snapshot privado recusado.") from None
        raise FalhaPrivada("FALHA: redirecionamento do download privado recusado.")

    def _api(self, endpoint: str) -> dict:
        with self._abrir(endpoint) as resposta:
            dados = resposta.read(LIMITE_METADADOS + 1)
        _exigir(len(dados) <= LIMITE_METADADOS)
        return json.loads(dados)

    def verificar(self) -> None:
        release = self._api(f"releases/{RELEASE}")
        _exigir(
            release.get("id") == RELEASE
            and release.get("draft") is True
            and release.get("tag_name") == "dados-privados"
        )

    def baixar(self, ref: Referencia, destino: Path) -> None:
        self.verificar()
        ativo = self._api(f"releases/assets/{ref.asset}")
        _exigir(ativo.get("id") == ref.asset and ativo.get("size") == ref.tamanho)
        _exigir(ativo.get("digest") == f"sha256:{ref.sha256}")
        self.verificar()
        with self._abrir(f"releases/assets/{ref.asset}", binario=True) as resposta, destino.open("xb") as f:
            total = 0
            while bloco := resposta.read(1024 * 1024):
                total += len(bloco)
                _exigir(total <= ref.tamanho)
                f.write(bloco)
        _conferir(destino, ref)


def _contrato(pasta: Path) -> tuple[dict, dict, dict[str, Referencia]]:
    _conferir(pasta / "manifesto.json", MANIFESTO)
    _conferir(pasta / "plano.json", PLANO)
    manifesto, plano = _json(pasta / "manifesto.json"), _json(pasta / "plano.json")
    _exigir(
        manifesto.get("uf") == "PA"
        and manifesto.get("municipios") == manifesto.get("municipios_calculados") == 144
        and manifesto.get("imoveis_calculados") == 345870
        and manifesto.get("modelo_versao") == plano.get("modelo_versao") == MODELO
        and manifesto.get("cenario") == "central_r11"
        and manifesto.get("commit") == plano.get("sha_origem") == ORIGEM
        and plano.get("release_id") == RELEASE
        and plano.get("draft") is True
        and plano.get("execucao_origem") == 43285608189
    )
    return (
        manifesto,
        plano,
        {
            "entradas.tar.gz": _referencia(plano["entradas"]),
            "previsoes.tar.gz": _referencia(manifesto["arquivos"]["previsoes"]),
        },
    )


def _percorrer_tar(arquivo: Path, selecionar, *, comparar: bool = False) -> set[Path]:
    """Valida todos os membros; extrai ou compara somente os necessários ao teste."""
    nomes, destinos = set(), set()
    tamanho = 0
    with tarfile.open(arquivo, "r:gz") as tar:
        for membro in tar:
            nome = PurePosixPath(membro.name)
            _exigir(
                not nome.is_absolute()
                and ".." not in nome.parts
                and "\\" not in membro.name
                and nome.parts
                and str(nome) not in nomes
                and (membro.isfile() or membro.isdir())
                and len(nomes) < 10000
            )
            nomes.add(str(nome))
            tamanho += membro.size
            _exigir(0 <= membro.size <= LIMITE_TAR and tamanho <= LIMITE_TAR)
            if membro.isdir():
                continue
            destino = selecionar(nome)
            if destino is None:
                continue
            _exigir(destino not in destinos)
            destinos.add(destino)
            with tar.extractfile(membro) as fonte:
                if comparar:
                    _exigir(destino.is_file() and not destino.is_symlink() and destino.stat().st_size == membro.size)
                    _exigir(hashlib.file_digest(fonte, "sha256").hexdigest() == _sha(destino))
                else:
                    destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with destino.open("xb") as saida:
                        shutil.copyfileobj(fonte, saida)
    return destinos


def _layout(pasta: Path, *, comparar: bool = False) -> tuple[dict, list[dict]]:
    manifesto, plano, refs = _contrato(pasta)
    for nome, ref in refs.items():
        _conferir(pasta / nome, ref)
    entradas = pasta / "entradas"
    permitidos = {*PACOTES, "estados.json", "snapshot.json"}

    def escolher_entrada(nome):
        _exigir(len(nome.parts) == 1 and nome.name in permitidos)
        return entradas / nome.name

    extraidos = _percorrer_tar(pasta / "entradas.tar.gz", escolher_entrada, comparar=comparar)
    _exigir({p.name for p in extraidos} == permitidos)
    _conferir(
        entradas / "snapshot.json", Referencia(1, (entradas / "snapshot.json").stat().st_size, plano["snapshot_sha256"])
    )
    snapshot = _json(entradas / "snapshot.json")
    _exigir(snapshot.get("fontes") == manifesto["fontes"] and snapshot.get("cenario") == "central_r11")
    for nome in (*PACOTES, "estados.json"):
        _conferir(entradas / nome, _referencia(snapshot["fontes"][nome]))
    saida = pasta / "saida" / "PA"

    def escolher_base(nome):
        _exigir(len(nome.parts) == 2 and nome.parts[0] == "PA")
        return saida / nome.name

    tabelas = set()
    for nome in PACOTES:
        novos = _percorrer_tar(entradas / nome, escolher_base, comparar=comparar)
        _exigir(not tabelas.intersection(novos))
        tabelas.update(novos)

    def escolher_previsao(nome):
        if str(nome) in {"fontes.json", "municipios.json"}:
            return pasta / "metadados" / nome.name
        if (
            len(nome.parts) == 2
            and nome.parts[0] == "previsoes"
            and re.fullmatch(r"(?:desenvolvedor|terra)_\d{7}\.csv", nome.name)
        ):
            _exigir(saida / nome.name not in tabelas)
            return saida / nome.name
        return None

    previsoes = _percorrer_tar(pasta / "previsoes.tar.gz", escolher_previsao, comparar=comparar)
    tabelas.update(p for p in previsoes if p.parent == saida)
    _exigir({p for p in saida.iterdir()} == tabelas)
    _exigir(_json(pasta / "metadados" / "fontes.json") == snapshot)
    marcas = _json(pasta / "metadados" / "municipios.json")
    return snapshot, marcas


def _identidades(arquivo: Path, *, modelo: str | None = None, entradas: str | None = None) -> set[str]:
    codigos = set()
    with arquivo.open(encoding="utf-8", newline="") as f:
        leitor = csv.DictReader(f)
        _exigir("cod_imovel" in (leitor.fieldnames or []))
        for linha in leitor:
            cod = linha["cod_imovel"]
            _exigir(bool(cod and cod.strip()) and cod not in codigos)
            codigos.add(cod)
            if modelo is not None:
                _exigir(linha.get("restauracao_versao") == modelo and linha.get("entradas_versao") == entradas)
    return codigos


def conferir_preparado(pasta: Path) -> Path:
    """Reconfere os bytes contra os TARs ancorados; a variável de ambiente não é uma prova."""
    _pasta_privada(pasta)
    snapshot, marcas = _layout(pasta, comparar=True)
    from raiz import restauracao as R

    _exigir(R.versao() == MODELO and R.cenario()["cenario"] == "central_r11")
    cods = set(snapshot["cobertura"]["com_imoveis"])
    _exigir(len(cods) == len(marcas) == 144 and {m["cod_municipio"] for m in marcas} == cods)
    saida = pasta / "saida" / "PA"
    for prefixo, extensao in (("imoveis", "csv"), ("desenvolvedor", "csv"), ("terra", "csv"), ("geo", "parquet")):
        _exigir({int(p.stem.rsplit("_", 1)[1]) for p in saida.glob(f"{prefixo}_*.{extensao}")} == cods)
    todos = set()
    for marca in marcas:
        cod = marca["cod_municipio"]
        esperado = hashlib.sha256(
            json.dumps(
                {"municipio": cod, "fontes": {n: snapshot["fontes"][n]["sha256"] for n in PACOTES}}, sort_keys=True
            ).encode()
        ).hexdigest()
        _exigir(
            marca["modelo_versao"] == MODELO
            and marca["cenario"] == "central_r11"
            and marca["entradas_versao"] == esperado
        )
        brutos = _identidades(saida / f"imoveis_{cod}.csv")
        calculados = _identidades(saida / f"desenvolvedor_{cod}.csv", modelo=MODELO, entradas=esperado)
        _exigir(brutos == calculados == _identidades(saida / f"terra_{cod}.csv"))
        _exigir(len(brutos) == marca["imoveis"] and not todos.intersection(brutos))
        todos.update(brutos)
        for prefixo in ("desenvolvedor", "terra"):
            nome = f"{prefixo}_{cod}.csv"
            _exigir(_sha(saida / nome) == marca["arquivos"][nome])
    _exigir(len(todos) == 345870)
    return saida


def _pasta_privada(pasta: Path) -> None:
    _exigir(pasta.is_dir() and not pasta.is_symlink() and pasta.resolve() == pasta.absolute())
    _exigir(stat.S_IMODE(pasta.stat().st_mode) == 0o700 and pasta.stat().st_uid == os.getuid())
    _exigir(not pasta.is_relative_to(RAIZ))
    # Nenhum componente preparado pode apontar para um arquivo externo.
    _exigir(not any(p.is_symlink() for p in pasta.rglob("*")))


def preparar(pasta: Path, cliente: ClientePrivado | None = None) -> None:
    cliente = cliente or ClientePrivado()
    if not pasta.exists():
        pasta.mkdir(mode=0o700)
    _pasta_privada(pasta)
    _exigir(not any(pasta.iterdir()))
    try:
        cliente.baixar(MANIFESTO, pasta / "manifesto.json")
        cliente.baixar(PLANO, pasta / "plano.json")
        _, _, refs = _contrato(pasta)
        for nome, ref in refs.items():
            cliente.baixar(ref, pasta / nome)
        _layout(pasta)
    except FalhaPrivada:
        shutil.rmtree(pasta)
        raise
    except Exception:
        shutil.rmtree(pasta)
        raise FalhaPrivada("FALHA: preparação autenticada do snapshot privado não concluída.") from None


def conferir_resultado(arquivo: Path, codigo: int) -> None:
    _exigir(codigo == 0)
    casos = ET.parse(arquivo).getroot().findall(".//testcase")
    _exigir(len(casos) == 1 and (casos[0].get("classname"), casos[0].get("name")) == CASO)
    _exigir(not any(casos[0].find(tipo) is not None for tipo in ("skipped", "failure", "error")))


def _interromper(signum, frame) -> None:
    raise KeyboardInterrupt


def executar_preparado(pasta: Path, *, timeout: int = 1800) -> dict:
    """Só retorna contagens e recursos; nenhum diagnóstico do filho sai desta pasta."""
    conferir_evento(dict(os.environ))
    _pasta_privada(pasta)
    inicio = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="raiz-pa-teste-") as td:
        privado = Path(td)
        ambiente = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": td,
            "TMPDIR": td,
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "RAIZ_TESTE_PA_FILHO": "1",
            "RAIZ_TESTE_PA_PASTA": str(pasta),
        }
        if os.environ.get("RUNNER_TRACKING_ID"):
            ambiente["RUNNER_TRACKING_ID"] = os.environ["RUNNER_TRACKING_ID"]
        resultado = privado / "resultado.xml"
        comando = [
            sys.executable,
            "-m",
            "pytest",
            NO_TESTE,
            "-q",
            "--tb=no",
            "-p",
            "no:cacheprovider",
            f"--junitxml={resultado}",
        ]
        try:
            with (privado / "diagnostico.log").open("wb") as log:
                processo = subprocess.Popen(
                    comando, cwd=RAIZ, env=ambiente, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
                )
                principal = threading.current_thread() is threading.main_thread()
                anterior = signal.signal(signal.SIGTERM, _interromper) if principal else None
                try:
                    codigo = processo.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    raise FalhaPrivada("FALHA: teste estadual privado excedeu o tempo limite.") from None
                finally:
                    try:
                        if processo.poll() is None:
                            try:
                                os.killpg(processo.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            processo.wait()
                    finally:
                        if principal:
                            signal.signal(signal.SIGTERM, anterior)
            conferir_resultado(resultado, codigo)
        except Exception:
            raise FalhaPrivada(
                "FALHA: teste estadual privado não aprovado; diagnósticos privados não são publicados."
            ) from None
    return {
        "municipios": 144,
        "imoveis": 345870,
        "segundos": round(time.monotonic() - inicio, 1),
        "pico_rss_mib": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparar", type=Path, help="Pasta efêmera 0700 fora do checkout; não publicar nem cachear.")
    args = parser.parse_args()
    try:
        if args.preparar:
            preparar(args.preparar.absolute())
            print("SUCESSO: snapshot privado preparado; a execução do teste estadual ainda é obrigatória.")
        else:
            with tempfile.TemporaryDirectory(prefix="raiz-pa-") as td:
                preparar(Path(td))
                resultado = executar_preparado(Path(td))
                print("SUCESSO: teste estadual privado aprovado.")
                print(json.dumps(resultado))
    except FalhaPrivada as erro:
        print(str(erro), file=sys.stderr)
        return 1
    except Exception:
        print(
            "FALHA: preparação ou validação estadual privada não concluída; nenhum diagnóstico privado foi publicado.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
