// ═══════════════════════════════════════════════════════════
//  explicitText-ui.ts — Empty states, confirmations, toasts
// ═══════════════════════════════════════════════════════════

import type { EmptyStateText, ConfirmationText } from './explicitText';

// ── Empty States ────────────────────────────────────────────

export function emptyStateMessage(
  context: 'schedule' | 'orders' | 'mrp' | 'alerts' | 'replan' | 'console',
): EmptyStateText {
  switch (context) {
    case 'schedule':
    case 'console':
      return {
        title: 'Ainda nao ha dados carregados',
        description:
          'Para comecar, carrega o ficheiro ISOP do ERP. ' +
          'O PP1 analisa os dados e cria o plano automaticamente.',
        actionLabel: 'Carregar ISOP',
      };
    case 'orders':
      return {
        title: 'Nenhuma encomenda encontrada',
        description: 'Carrega um ficheiro ISOP para ver as encomendas por cliente e prazo.',
        actionLabel: 'Carregar ISOP',
      };
    case 'mrp':
      return {
        title: 'Sem dados MRP',
        description:
          'Importa o ficheiro ISOP na página Planning para gerar a análise de materiais. ' +
          'O PP1 calcula stocks, cobertura e riscos automaticamente.',
        actionLabel: 'Ir para Planning',
      };
    case 'alerts':
      return {
        title: 'Nenhum problema detectado',
        description:
          'A fabrica funciona conforme o plano. Todas as prensas activas. ' +
          'Todas as entregas no prazo.',
        actionLabel: 'Simular cenario',
      };
    case 'replan':
      return {
        title: 'Sem replaneamento activo',
        description:
          'Usa os cenarios rapidos para simular avarias, encomendas urgentes ou optimizacao. ' +
          'O PP1 calcula o impacto e sugere soluções.',
        actionLabel: 'Escolher cenario',
      };
  }
}

// ── Confirmation Text ───────────────────────────────────────

export function confirmationText(
  action: string,
  params: {
    count?: number;
    targetMachine?: string;
    otdBefore?: number;
    otdAfter?: number;
    detail?: string;
  },
): ConfirmationText {
  const { count, targetMachine, otdBefore, otdAfter, detail } = params;

  switch (action) {
    case 'apply_replan':
      return {
        title: count
          ? `Aplicar — mover ${count} lote${count > 1 ? 's' : ''}${targetMachine ? ` para ${targetMachine}` : ''}`
          : 'Aplicar replaneamento',
        detail: detail ?? 'O plano sera actualizado com as mudancas propostas.',
        consequence:
          otdBefore != null && otdAfter != null
            ? `OTD-D: ${otdBefore.toFixed(0)}% → ${otdAfter.toFixed(0)}%`
            : 'Verificar impacto antes de aplicar.',
      };
    case 'apply_whatif':
      return {
        title: 'Aplicar cenario simulado',
        detail: detail ?? 'O cenario simulado substitui o plano actual.',
        consequence:
          otdBefore != null && otdAfter != null
            ? `OTD-D muda de ${otdBefore.toFixed(0)}% para ${otdAfter.toFixed(0)}%`
            : 'Verificar resultados antes de confirmar.',
      };
    case 'mark_down':
      return {
        title: `Registar paragem${targetMachine ? ` — ${targetMachine}` : ''}`,
        detail: 'A máquina será marcada como parada no plano actual.',
        consequence:
          'O PP1 vai recalcular o plano e propor redistribuição de carga.',
      };
    default:
      return {
        title: action,
        detail: detail ?? '',
        consequence: '',
      };
  }
}

// ── Badge Tooltip ───────────────────────────────────────────

export function badgeTooltip(
  module: 'materials' | 'alerts' | 'plan',
  count: number,
): string {
  if (count === 0) return '';

  switch (module) {
    case 'materials':
      return `${count} SKU${count > 1 ? 's' : ''} com stock critico ou em risco de stockout`;
    case 'alerts':
      return `${count} alerta${count > 1 ? 's' : ''} activo${count > 1 ? 's' : ''} — verificar consola`;
    case 'plan':
      return `${count} operação${count > 1 ? 'ões' : ''} bloqueada${count > 1 ? 's' : ''} ou em overflow`;
  }
}

// ── Trade-off Text ──────────────────────────────────────────

export function tradeoffText(
  action: string,
  benefit: string,
  cost: string,
): string {
  return `${action}: ${benefit}. ${cost}.`;
}

// ── Toast Messages ──────────────────────────────────────────

export function toastMessage(
  action: 'replan_applied' | 'whatif_applied' | 'andon_started' | 'andon_recovered' | 'optimized',
  params: {
    count?: number;
    targetMachine?: string;
    machineId?: string;
    otdDelta?: number;
    detail?: string;
  } = {},
): string {
  const { count, targetMachine, machineId, otdDelta, detail } = params;

  switch (action) {
    case 'replan_applied':
      return count && targetMachine
        ? `Feito. ${count} lote${count > 1 ? 's' : ''} movido${count > 1 ? 's' : ''} para ${targetMachine}.${otdDelta ? ` OTD-D ${otdDelta > 0 ? '+' : ''}${otdDelta.toFixed(0)}%.` : ''}`
        : detail ?? 'Plano actualizado com sucesso.';
    case 'whatif_applied':
      return `Cenario aplicado.${otdDelta ? ` OTD-D ${otdDelta > 0 ? '+' : ''}${otdDelta.toFixed(0)}%.` : ''}`;
    case 'andon_started':
      return `Paragem registada${machineId ? ` — ${machineId}` : ''}.`;
    case 'andon_recovered':
      return `${machineId ?? 'Máquina'} recuperada. Plano actualizado.`;
    case 'optimized':
      return `Plano optimizado.${otdDelta ? ` OTD-D ${otdDelta > 0 ? 'subiu' : 'desceu'} ${Math.abs(otdDelta!).toFixed(0)}%.` : ''}${count ? ` ${count} lotes reordenados.` : ''}`;
    default:
      return detail ?? 'Accao concluida.';
  }
}
