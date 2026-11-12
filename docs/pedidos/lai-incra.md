# Pedido de acesso à informação ao INCRA (SIGEF e acervo fundiário)

**Órgão:** Instituto Nacional de Colonização e Reforma Agrária (INCRA)
**Assunto:** Endereço dos arquivos do acervo fundiário e lista de parcelas canceladas do SIGEF

---

Com base na Lei 12.527/2011 (arts. 10 e 11) e na Política de Dados Abertos do Poder Executivo federal
(Decreto 8.777/2016), solicito:

1. **Novo endereço dos arquivos do acervo fundiário.** Os arquivos ZIP por UF (SIGEF, SNCI e assentamentos) eram
   baixados em certificacao.incra.gov.br, que está fora do ar. Peço o endereço oficial atual desses arquivos e, para
   cada arquivo, a data de geração e o hash (SHA-256), para que quem usa possa conferir a integridade e saber quando
   houve atualização.

2. **Lista de parcelas canceladas.** Peço a lista das parcelas do SIGEF canceladas, desativadas ou substituídas, com o
   código da parcela (`parcela_codigo`), a situação, a data do cancelamento e, quando houver, o código da parcela que a
   substituiu, desde 2013, em formato aberto (CSV ou Parquet).

3. **Data de atualização no serviço WFS.** A camada `geonode:sigef_geo` do Geoportal (geoportal.incra.gov.br) traz
   `data_aprovacao`, mas não a data da última alteração nem do cancelamento. Peço que essas datas sejam publicadas na
   camada ou informado se há previsão para isso.

**Por que isso importa.** O art. 8º, § 3º, III, da Lei 12.527/2011 pede que as informações permitam o acesso
automatizado por sistemas externos em formatos abertos, estruturados e legíveis por máquina. Sem a lista de
canceladas, quem replica o SIGEF pela camada pública mantém parcelas que já não valem, e sem o hash dos arquivos não há
como conferir uma cópia. É a prática de outras bases públicas: o Land Information New Zealand publica "changesets" do
cadastro (só o que mudou entre duas datas), o padrão SDMX aceita o parâmetro `updatedAfter`, e a SEC dos Estados Unidos
publica um índice diário dos documentos novos.

Não peço dado pessoal: nenhum nome, CPF ou CNPJ de detentor, só códigos de parcela, situação e datas.

Fico à disposição para esclarecer o pedido.

[nome do solicitante, pelo cadastro do Fala.BR]
