# Evidência da auditoria do solver — 02/10/2026

Documento principal: [plano](../plano-solver-2026-10-02.md).
Contrato interno: [AGENTS.md](../../AGENTS.md).

| Artefacto | Conteúdo |
|---|---|
| ultimos-30-pedidos.md (artefacto local não incluído) | Pedidos, padrões e identificadores dos turnos |
| [pesquisa.md](pesquisa.md) | Método, fontes primárias, comparação e limites |
| diagnostico.json (artefacto local não incluído) | Primeira auditoria conservada: 236 combinações, uma antecipação válida; 1,786 s/110 MiB |
| reproducao-final.json (artefacto local não incluído) | Verificação pelo reproducer guardado: mesmo caso; 3,081 s/113,89 MiB |
| benchmark.json (artefacto local não incluído) | Uma execução da compactação atual: 5,281 s/121,98 MiB; oito candidatos, zero movimentos |
| comparators.json (artefacto local não incluído) | Contraexemplo sintético dos ranks e do proxy de tempo |
| manifest.json (artefacto local não incluído) | Versões, hashes dos ficheiros auditados e âmbito de verificação |
| [reproduzir_auditoria.py](reproduzir_auditoria.py) | Pesquisa limitada em objetos destacados, base de dados só de leitura |

As medidas são observações locais, não percentis nem garantias. O script usa os
alocadores/validadores atuais e o contrato antigo que ainda veta setups extra;
o candidato BFP186 passa mesmo nesse contrato mais restritivo. A política futura
confirmada admite setup adicional para antecipar sem perdas de entrega/física.

## Reproduzir o caso no snapshot auditado

A partir de `/home/luis/projects/INCOMPOLINHO`, com a versão de código do manifesto:

```bash
.venv/bin/python docs/auditoria-solver-2026-10-02/reproduzir_auditoria.py \
  --database /home/luis/projects/INCOMPOLINHO/data/plans.db \
  --snapshot-id 046b5d08b9884672ba2f9cf7e0f024d7 \
  --as-of 2026-10-02 \
  --output /tmp/incompolinho-antecipacoes-reproduzidas.json
```

O snapshot histórico tem de continuar na base de dados. Omitir `--snapshot-id`
analisa o plano ativo nessa altura, que pode já ser diferente. `--as-of` fixa a
fronteira da proteção; não usar a data atual implicitamente numa reprodução
histórica. No Linux, o processo limita a afinidade a um núcleo permitido.

O output é um relatório, nunca um novo plano ativo. O script não chama endpoints,
não modifica a base de dados, não aplica movimentos e não exporta o payload
completo da fábrica para esta pasta de documentação.

Para repetir a medição do ciclo existente sobre o plano ativo, o script já
existente aceita:

```bash
.venv/bin/python scripts/benchmark_improvement.py \
  --database /home/luis/projects/INCOMPOLINHO/data/plans.db \
  --freeze-day 15 --repeat 1 \
  --output /tmp/incompolinho-benchmark-compactacao.json
```

Esse comando não fixa afinidade; a medição registada nesta auditoria usou um
launcher com `os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})`. O script
lê o plano ativo, portanto o seu hash/revisão deve coincidir para comparar.

## Testes executados

```bash
.venv/bin/python -m pytest -q \
  tests/test_improvement_contract.py tests/test_alternative_repair.py \
  tests/test_mounting_evidence.py tests/test_subcontract_release.py \
  tests/test_candidate_retention.py tests/test_window.py
```

Resultado: 204 passaram em 2,20 s, com uma warning de dependência existente.
O reproducer passou Ruff. A suíte integral não foi executada nesta intervenção
documental; consta dos critérios de saída da implementação.
