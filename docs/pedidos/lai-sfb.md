# Pedido de acesso à informação ao Serviço Florestal Brasileiro (SICAR)

**Órgão:** Serviço Florestal Brasileiro (SFB)
**Assunto:** Data de atualização e lista de exclusões do Cadastro Ambiental Rural nos serviços WFS do SICAR

---

Com base na Lei 12.527/2011 (arts. 10 e 11) e na Política de Dados Abertos do Poder Executivo federal
(Decreto 8.777/2016), solicito:

1. **Data de atualização em todas as UFs.** A camada pública `sicar:sicar_imoveis_<uf>` do GeoServer do CAR
   (geoserver.car.gov.br) traz o campo `data_atualizacao` em 15 UFs e não traz em 12. Peço que o campo seja publicado
   em todas as UFs ou, se isso não for possível agora, que me seja enviada a data da última alteração de cada imóvel
   (código do imóvel e data) das 12 UFs sem o campo, em formato aberto (CSV ou Parquet). A lista das 12 UFs segue
   abaixo.

   [lista das UFs sem o campo, gerada pela checagem da coleta]

2. **Lista de exclusões.** Peço a lista de imóveis cancelados ou excluídos do CAR, com o código do imóvel, a situação
   e a data do cancelamento ou exclusão, desde 2020, em formato aberto. Quem replica a base pela camada pública hoje
   não tem como saber que um imóvel saiu sem baixar a UF inteira de novo.

3. **Dicionário de dados** das camadas `sicar_imoveis_<uf>`: significado, unidade e regra de preenchimento de cada
   campo, inclusive `status_imovel`, `condicao`, `m_fiscal` e `data_atualizacao`.

**Por que isso importa.** O art. 8º, § 3º, III, da Lei 12.527/2011 pede que as informações permitam o acesso
automatizado por sistemas externos em formatos abertos, estruturados e legíveis por máquina. Uma data de atualização
confiável e uma lista de exclusões permitem que quem usa os dados baixe só o que mudou, o que reduz a carga sobre o
servidor do SICAR. É a prática de outras bases públicas: o Land Information New Zealand publica "changesets" de cada
camada (só o que mudou entre duas datas), o padrão SDMX de estatísticas oficiais aceita o parâmetro `updatedAfter`, e a
SEC dos Estados Unidos publica um índice diário dos documentos novos.

Não peço dado pessoal: nenhum nome, CPF ou CNPJ de proprietário ou possuidor, só o código do imóvel, a situação e as
datas.

Fico à disposição para esclarecer o pedido.

[nome do solicitante, pelo cadastro do Fala.BR]
