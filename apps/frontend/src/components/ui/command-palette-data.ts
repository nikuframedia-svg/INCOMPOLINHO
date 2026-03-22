import Fuse from 'fuse.js';
import {
  BarChart3,
  Boxes,
  CalendarRange,
  Clock,
  Database,
  Eye,
  FlaskConical,
  type LucideIcon,
  Repeat,
  Settings,
  ShoppingCart,
} from 'lucide-react';

export interface PaletteItem {
  id: string;
  label: string;
  section: string;
  path: string;
  icon: LucideIcon;
  keywords?: string;
}

export const PAGES: PaletteItem[] = [
  {
    id: 'console',
    label: 'Visão Geral',
    section: 'Páginas',
    path: '/console',
    icon: Eye,
    keywords: 'console dashboard overview',
  },
  {
    id: 'plan',
    label: 'Gantt',
    section: 'Páginas',
    path: '/plan',
    icon: BarChart3,
    keywords: 'gantt scheduling plano',
  },
  {
    id: 'replan',
    label: 'Replan',
    section: 'Páginas',
    path: '/plan/replan',
    icon: Repeat,
    keywords: 'replan replaneamento',
  },
  {
    id: 'whatif',
    label: 'What If',
    section: 'Páginas',
    path: '/plan/whatif',
    icon: FlaskConical,
    keywords: 'whatif cenário scenario simulação',
  },
  {
    id: 'data',
    label: 'Dados',
    section: 'Páginas',
    path: '/plan/data',
    icon: Database,
    keywords: 'upload isop dados data importar',
  },
  {
    id: 'mrp',
    label: 'Materiais',
    section: 'Páginas',
    path: '/mrp',
    icon: Boxes,
    keywords: 'mrp materiais stock inventário',
  },
  {
    id: 'orders',
    label: 'Encomendas',
    section: 'Páginas',
    path: '/mrp/orders',
    icon: ShoppingCart,
    keywords: 'encomendas orders pedidos clientes',
  },
  {
    id: 'ctp',
    label: 'CTP',
    section: 'Páginas',
    path: '/mrp/ctp',
    icon: Clock,
    keywords: 'ctp capable to promise prazo',
  },
  {
    id: 'settings',
    label: 'Settings',
    section: 'Páginas',
    path: '/settings',
    icon: Settings,
    keywords: 'configurações settings preferências',
  },
  {
    id: 'machines',
    label: 'Máquinas',
    section: 'Settings',
    path: '/settings/machines',
    icon: Settings,
    keywords: 'máquinas machines prensa PRM',
  },
  {
    id: 'shifts',
    label: 'Turnos',
    section: 'Settings',
    path: '/settings/shifts',
    icon: Settings,
    keywords: 'turnos shifts horário',
  },
  {
    id: 'setup-matrix',
    label: 'Setup Matrix',
    section: 'Settings',
    path: '/settings/setup-matrix',
    icon: Settings,
    keywords: 'setup matrix ferramenta',
  },
  {
    id: 'operators',
    label: 'Operadores',
    section: 'Settings',
    path: '/settings/operators',
    icon: Settings,
    keywords: 'operadores operators equipa',
  },
  {
    id: 'scheduling',
    label: 'Scheduling Config',
    section: 'Settings',
    path: '/settings/scheduling',
    icon: CalendarRange,
    keywords: 'scheduling atcs dispatch configuração',
  },
];

export const fuse = new Fuse(PAGES, {
  keys: ['label', 'keywords', 'section'],
  threshold: 0.4,
  includeScore: true,
});
