# Critérios de revisão (Incompol / PP1)

- **Física primeiro:** nenhuma alteração pode produzir sobreposições de máquina/ferramenta/equipa, produção fora de turno, antes do material (R) ou em máquina não permitida. Gates e `validate_plan` têm de continuar a recusar.
- **Lote económico = uma produção** (nunca partido, nunca múltiplos) e lotes começados preservados (o feito nunca muda).
- **Entregas:** uma melhoria automática nunca piora nenhuma encomenda individual.
- **Recusas com causas** em pt-PT, sem ids internos `LOT_`; sem `alert(`; sem `HTTPException(4xx, str(exc))`.
- **Configuração viva** (`config/factory.yaml`, `data/`) nunca entra em commits nem é alterada por testes.
- **Simplicidade:** sem camadas/abstrações novas sem necessidade atual; reutilizar `plans/refusal.py`, `plans/manual_edits.py`, `config/changes.py`, stores existentes.
- **Áreas sensíveis:** `plans/frozen.py` (histórico/âncoras), `plans/store.py` (commit), `replan/jobs.py` (orçamento 80 s), `scheduler/validation.py`.
- Achados: confirmar com execução ou código; separar defeito, lacuna de prova e sugestão.
