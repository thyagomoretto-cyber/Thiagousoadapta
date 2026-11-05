# Cadastro Kenlo

Ensinamentos do cadastro de imóveis, para levar a outro computador sem treinar de novo.
Todo ensinamento novo do DodaiOS entra numa pasta como esta, junto com o que foi ensinado.

| Arquivo | O que guarda | Destino no computador |
| --- | --- | --- |
| `regras-cadastro.json` | Valores fixos e tipos já ensinados | Juntar em `~/.dodaios-data/data/imoveis/regras-cadastro.json` |
| `respostas-aprendidas.json` | O que o agente aprendeu ao perguntar | Juntar em `~/.dodaios-data/data/agente/respostas-aprendidas.json` |

## Regras do cadastro

- Taxa de administração 10%, seguro incêndio e seguro fiança 0,01.
- Publicar valor no site sempre como venda e locação. Exclusividade Não. Situação Desocupado. Aceita financiamento Sim.
- Tipo de locação Mensal em locação; em venda não mexer.
- Sala, loja e prédio usam área útil, total e privativa. Sala e prédio marcam Interfone.
- Dormitórios, suítes, vagas e banheiros: conferir ficha e fotos e perguntar se não houver.
- Casa e apartamento sempre têm dormitórios e suítes preenchidos; sem suíte, vale 0.
- Banheiros: ver nas fotos e nunca colocar menos que o número de suítes.
- Piso: marcar todos os que aparecem na ficha ou nas fotos.
- Itens identificados na ficha ou nas fotos são marcados; os outros ficam em branco.
- Finalidade e Tipo ficam travados enquanto carregam: esperar e conferir antes de seguir.
- Sem o modelo de imagens, perguntar antes e nunca salvar.
- IPTU sempre Mensal: com valor na ficha, usar o valor; sem valor, 0,01.
- Sem valor de condomínio na ficha: usar o valor mais comum dos imóveis lidos do mesmo condomínio, com os mesmos dormitórios.
- Consultar imóveis parecidos na base lida, marcando para conferir.
- Comparar o cadastro final com o que foi preenchido e perguntar antes de virar regra.
- Antes de perguntar ao dono, olhar a tela e tentar resolver uma vez.

## O que não fica aqui

Senhas, tokens, nomes e telefones de proprietários, corretor, registro de imóveis e dados dos cadastros lidos.
Enquanto este repositório for público, dados da empresa ficam só no computador. Ao juntar as regras, informe o corretor em `*Corretor:`.

## Quando faltar informação

1. Procure primeiro nos imóveis já lidos, aceitando erro de escrita em rua e condomínio.
2. Cadastre o endereço igual ao que já existe na base. Sem resultado pela rua, use o CEP.
3. Apartamento sempre leva o nome do condomínio ou edifício. Sem ele na ficha, procure pelo endereço na base.
4. Não achou na base: procure na internet só pelo endereço, nunca com dados do proprietário.
5. Não achou na internet: pergunte ao dono.

## Mobília

Quando as fotos mostrarem móveis, marque Mobiliado e cada ambiente com mobília. O seletor de fotos entrega ambientes, itens e pisos para quem preenche.

## Campos proibidos

Nunca preencher Link do YouTube.

## Final do cadastro

A mensagem "Imóvel cadastrado com a referência" confirma o cadastro. Não é preciso responder ao aviso: feche a guia e siga para o próximo imóvel do grupo. Sem mais imóveis, feche o Chrome.

## Proprietário já cadastrado

Ao digitar o telefone, responda Sim em "Utilizar dados deste cliente". A Mídia de origem vem do cadastro existente e fica travada: não mexa nela.
