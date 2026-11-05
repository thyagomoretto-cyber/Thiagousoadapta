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
- Itens identificados na ficha ou nas fotos são marcados; os outros ficam em branco.
- Finalidade e Tipo ficam travados enquanto carregam: esperar e conferir antes de seguir.
- Sem o modelo de imagens, perguntar antes e nunca salvar.

## O que não fica aqui

Senhas, tokens, nomes e telefones de proprietários, corretor, registro de imóveis e dados dos cadastros lidos.
Enquanto este repositório for público, dados da empresa ficam só no computador. Ao juntar as regras, informe o corretor em `*Corretor:`.
