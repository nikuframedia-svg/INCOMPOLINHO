import { Package, RefreshCw, Wrench, Zap } from 'lucide-react';
import { C } from '@/theme/color-bridge';

export type Scenario = 'machine_down' | 'tool_down' | 'rush_order' | 'optimize';

export const SCENARIOS: {
  id: Scenario;
  icon: typeof Wrench;
  label: string;
  desc: string;
  color: string;
}[] = [
  {
    id: 'machine_down',
    icon: Wrench,
    label: 'Máquina parada',
    desc: 'Simula impacto em entregas e redistribui carga pelas restantes prensas',
    color: C.rd,
  },
  {
    id: 'tool_down',
    icon: Package,
    label: 'Ferramenta indisponível',
    desc: 'Verifica que encomendas sao afectadas e propoe alternativas',
    color: C.yl,
  },
  {
    id: 'rush_order',
    icon: Zap,
    label: 'Encomenda urgente',
    desc: 'Insere prioridade e mostra que entregas existentes podem atrasar',
    color: C.yl,
  },
  {
    id: 'optimize',
    icon: RefreshCw,
    label: 'Optimizar plano',
    desc: 'Redistribui operações para melhorar OTD-D e reduzir setups',
    color: C.ac,
  },
];
