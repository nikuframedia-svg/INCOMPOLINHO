---
name: prodplan-gantt-chart
description: |
  Gera Gantt chart de scheduling industrial.
  Usar para: criar Gantt, vista scheduling, timeline,
  drag-and-drop, zoom, blocos de produção.
---

# Gantt Industrial PP1

## Duas vistas
1. Recurso: linhas = máquinas, barras = operações
2. Encomenda: linhas = ordens, barras = operações

## Barras
- Comprimento ∝ duração. Cor por estado.
- ontime #2D862D | late #FF0000 | atrisk #FFD700
- setup #4169E1 | idle #D0D0D0
- Tooltip: ordem, SKU, qtd, início/fim, máquina, deadline

## Interação
- Drag-and-drop com verificação de constraints
- Re-scheduling cascata (mover 1 → dependências movem)
- Popup confirmação se dentro zona frozen
- Desfazer/refazer (Ctrl+Z/Y)

## Timeline
- Zoom: horas → dias → semanas
- Overlay turnos (A/B/Noite com cores de fundo)
- Linha "agora" sempre visível
- Markers: changeovers, manutenção

## Capacidade
- Histograma abaixo do Gantt por máquina
- Verde <80% | Amarelo 80-95% | Vermelho >95%

## Performance
- Virtualização para milhares de operações
- Web Worker para cálculos de layout
- requestAnimationFrame para drag suave
- Teclado: Tab navegar, Enter selecionar, setas mover
