"""Perfil Locust real com relógio virtual, isolado para não aplicar gevent ao pytest."""

import json
import os
import subprocess
import sys

from raiz import RAIZ_REPO


def test_normal_cobre_ferramentas_sem_exceder_fichas_e_nao_aprova_interrupcoes(tmp_path):
    codigo = r"""
import heapq, itertools, json
from collections import Counter
from types import SimpleNamespace
from locust.user import wait_time
from testes.carga import locust_mcp as carga
from testes.mcp.cliente import ErroMCP

agora = [0.0]
nomes = ['consultar_ficha', 'consultar_disponibilidade', 'pedir_lote', 'comparar_lotes',
         'acompanhar_contato', 'preparar_reserva', 'cancelar']
chamadas = []
eventos = []
class Interrupcao(BaseException): pass
class Cliente:
    def __init__(self, *a): pass
    def chamar(self, nome, argumentos):
        chamadas.append((agora[0], nome))
        agora[0] += 0.001
    def fechar(self): pass
carga.ClienteMCP = Cliente
carga.CASOS = {nome:{'argumentos':{}} for nome in nomes}
carga.BASE = SimpleNamespace(cabecalhos={}, identificadores=itertools.count(), fechar=lambda: None)
wait_time.perf_counter = lambda: agora[0]
carga.time.monotonic = lambda: agora[0]
def evento(**d):
    eventos.append(d)
    carga.medir(**d)
ambiente = SimpleNamespace(events=SimpleNamespace(request=SimpleNamespace(fire=evento)))
usuarios = [carga.MCPUsuario(ambiente) for _ in range(6)]
for usuario in usuarios:
    usuario.on_start()
    usuario._cp_last_run = 0.0
    usuario._cp_last_wait_time = 0.0
fila = [(0.0, i) for i in range(6)]
heapq.heapify(fila)
while fila:
    instante, i = heapq.heappop(fila)
    if instante >= 120: break
    agora[0] = instante
    usuarios[i].ferramenta()
    heapq.heappush(fila, (agora[0] + usuarios[i].wait_time(), i))
primeiras = Counter(nome for t,nome in chamadas if t < 10)
assert set(primeiras) == set(nomes) and sum(primeiras.values()) >= 20
fichas = [t for t,nome in chamadas if nome == 'consultar_ficha']
assert max(sum(inicio <= t < inicio + 60 for t in fichas) for inicio in fichas) <= 30
assert carga.CONTAGEM['requisicoes'] == sum(carga.SUCESSOS.values())
assert carga.CONTAGEM['falhas'] == 0

def interromper(*_): raise Interrupcao
usuarios[0].cliente.chamar = interromper
antes = len(eventos)
try: usuarios[0].ferramenta()
except Interrupcao: pass
else: raise AssertionError('interrupção suprimida')
assert len(eventos) == antes and carga.CONTAGEM['interrompidas'] == 1
def falhar(*_): raise ValueError('marcador-privado-exemplo')
usuarios[0].cliente.chamar = falhar
usuarios[0].ferramenta()
assert len(eventos) == antes + 1 and carga.CONTAGEM['falhas'] == 1
assert eventos[-1]['exception'].diagnostico()['codigo'] == 'erro_inesperado'
assert 'marcador-privado-exemplo' not in str(eventos[-1]['exception'])
assert carga.CONTAGEM['requisicoes'] == sum(carga.SUCESSOS.values()) + carga.CONTAGEM['falhas']
carga.finalizar(SimpleNamespace(process_exit_code=0))
print(json.dumps({'primeiras':dict(primeiras), 'interrompidas':carga.CONTAGEM['interrompidas']}))
"""
    relatorio = tmp_path / "relatorio.json"
    env = {
        **os.environ,
        "LOCUST_SKIP_MONKEY_PATCH": "1",
        "RAIZ_CARGA_FASE": "normal",
        "RAIZ_CARGA_RELATORIO": str(relatorio),
        "RAIZ_MCP_TESTE_URL": "http://localhost:8765/mcp",
        "RAIZ_MCP_TESTE_TOKEN": "token-local-descartavel",
    }
    executado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ_REPO, env=env, capture_output=True, timeout=30, check=False
    )
    assert executado.returncode == 0, executado.stderr.decode()
    dado = json.loads(relatorio.read_text())
    assert dado["falhas"] == 1 and dado["interrompidas"] == 1
    assert dado["falhas_por_tipo"][0]["codigo"] == "erro_inesperado"
    assert "marcador-privado-exemplo" not in relatorio.read_text()
