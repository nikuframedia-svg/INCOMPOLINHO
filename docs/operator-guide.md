# Guia do Operador INCOMPOLINHO

Este guia resume os ecrãs que o planeador usa no dia a dia. O ISOP continua a
ser a origem dos dados de produção; a configuração guarda apenas exceções,
calendários e regras persistentes.

## Configuração

### Ver dados ISOP

Usa **Administração / Avançado -> Ver dados ISOP** para consultar a tabela
read-only de referências, máquinas, ferramentas, lotes económicos, stock, OEE e
procura. A tabela tem pesquisa e ordenação; não altera o plano.

Linhas com origem **Configuração** são referências preservadas entre ISOPs,
mesmo quando não aparecem no ficheiro carregado. Isto mantém regras como
`CF589MMA1A02.20` disponíveis para subcontratação ou histórico.

### Correções de planeamento

Usa **Correções de planeamento** para editar exceções por SKU: lote económico
efetivo, buffers internos, mínimos de campanha e janelas de agrupamento. O valor
ISOP fica visível; o valor efetivo é o que entra no cálculo após guardar.

### Subcontratações

Cada SKU pode ser marcado para a empresa `SUBCONTRATO`. O prazo do fornecedor é
mostrado como **7 dias corridos de leitura** e aplicado ao planeador como
**5 dias úteis** por defeito. Ao guardar, o plano é recalculado e a regra fica
persistida para ISOPs futuros.

Para estes SKUs, o planeador calcula primeiro a data de envio ao fornecedor
(entrega ao cliente menos o prazo útil e o buffer configurado). A libertação
simulada de material ocorre cinco dias úteis antes desse envio, não cinco dias
antes da entrega ao cliente. O Gantt mostra separadamente **Entrega ao cliente**,
**Envio para subcontratação**, **Prazo de produção**, **Referência de material**
e **Libertação de material**.

Um envio em atraso aparece no gate próprio e exige aprovação. A vista de
expedição distingue peças concluídas na fábrica, peças no subcontratante e peças
já disponíveis para o cliente.

## Capacidade

A vista de capacidade mostra produção, setup e carga por máquina. Em semana, o
campo `workday_count` indica quantos dias úteis entram no bucket.

Legenda operacional:

- Azul: produção
- Laranja: setup
- Cinzento: sem carga
- Tracejado: fechado
- Vermelho: carga > capacidade

## Gantt

O botão **Gantt** abre a vista gráfica; **Tabela** abre a lista ordenável e
pesquisável de segmentos. O seletor fica à esquerda da barra para alternar
rapidamente entre as duas vistas.

Os turnos vêm da configuração ativa, não de valores fixos. Em vista de dia único
podes filtrar por todos os turnos ou por um turno específico. A navegação diária
fica disponível tanto no Gantt como na tabela.

## Boas práticas

- Carrega um ISOP novo antes de mexer em exceções quando houver dúvidas sobre a
  origem dos dados.
- Usa **Ver dados ISOP** para confirmar valores brutos; usa **Correções de
  planeamento** para alterar apenas o que deve sobreviver a novos uploads.
- Revê o impacto antes de guardar subcontratações ou correções críticas.
- Não uses o terminal/Shell para operação normal; estes ecrãs já gravam de forma
  transacional e recalculam o plano.
