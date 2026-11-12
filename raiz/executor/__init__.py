"""Agente Dados: o motor rodando DENTRO do produto, por estado e por município.

- armazem.py: onde os arquivos ficam (S3: Cloudflare R2 ou SeaweedFS; ou pasta local), cada um com a versão e a data;
- tarefas.py: as tarefas (as do motor e as do produto), do que cada uma depende e o que a muda (versão);
- executor.py: roda um estado retomando de onde parou (marca por município com a versão de cada tarefa) e refaz só
  o que mudou (versão da tarefa, fonte do município ou saída de uma tarefa anterior);
- agenda.py: rodada completa quando muda a coleção do MapBiomas, parcial no resto;
- sincronizar.py: o back-end espelha o armazenamento e carrega no banco (também sob demanda, por município).
"""
