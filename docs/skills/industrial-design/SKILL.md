---
name: prodplan-industrial-design
description: |
  Gera componentes UI industriais ISA-101/ISA-18.2/EEMUA-191.
  Usar para: criar componente, gerar UI, dashboard, Gantt,
  painel alarmes, KPI, qualquer implementação visual.
---

# Design Industrial PP1

## ISA-101 (NUNCA VIOLAR)
- Fundo: #F0F0F0 (dia) / #1A1A1A (noite)
- Cor SÓ para anomalias e status
- 2D simples. ZERO 3D, sombras, gradientes decorativos
- Animação SÓ para alarmes não reconhecidos
- Texto Inter, min 14px, preto/cinzento escuro
- Regra 3 Segundos: KPIs legíveis a 3m
- NUNCA só cor — SEMPRE cor + forma + texto

## Tokens
Status: running #2D862D | stopped #808080 | transition #FFD700 | manual #4169E1
Alarmes: critical #FF0000 | high #FF8C00 | medium #FFD700 | low #00BFFF
Gantt: ontime #2D862D | late #FF0000 | atrisk #FFD700 | setup #4169E1

## Alarmes ISA-18.2
- Não reconhecido + ativo: INTERMITENTE
- Reconhecido + ativo: SÓLIDO
- Max 4 prioridades. Max 5% como HIGH
- Alarme REQUER resposta do operador

## Hierarquia ecrãs
L1: Dashboard KPIs | L2: Gantt/Recursos | L3: Detalhe | L4: Config

## PROIBIDO
Hardcodar cores. 3D. Sombras decorativas. Animações decorativas.
Ícones sem semântica. Alarmes sem resposta. >4 prioridades.
