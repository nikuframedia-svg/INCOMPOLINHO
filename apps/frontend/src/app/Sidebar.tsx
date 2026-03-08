import {
  Building2,
  Calendar,
  ChevronDown,
  ClipboardList,
  Clock,
  Database,
  Grid3x3,
  LayoutDashboard,
  Package,
  Repeat,
  Settings,
  Sliders,
  Sparkles,
  UserCog,
  Wrench,
} from 'lucide-react';
import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import './Sidebar.css';

interface NavItem {
  label: string;
  path: string;
  icon: React.ElementType;
}

interface NavModule {
  id: string;
  label: string;
  icon: React.ElementType;
  basePath: string;
  items: NavItem[];
}

const NAV_MODULES: NavModule[] = [
  {
    id: 'console',
    label: 'Console',
    icon: LayoutDashboard,
    basePath: '/console',
    items: [{ label: 'Dia-a-dia', path: '/console', icon: LayoutDashboard }],
  },
  {
    id: 'plan',
    label: 'Plan',
    icon: Calendar,
    basePath: '/plan',
    items: [
      { label: 'Gantt', path: '/plan', icon: Calendar },
      { label: 'Replan', path: '/plan/replan', icon: Repeat },
      { label: 'What If', path: '/plan/whatif', icon: Sparkles },
      { label: 'Dados', path: '/plan/data', icon: Database },
    ],
  },
  {
    id: 'mrp',
    label: 'MRP',
    icon: ClipboardList,
    basePath: '/mrp',
    items: [
      { label: 'Vista Geral', path: '/mrp', icon: ClipboardList },
      { label: 'Encomendas', path: '/mrp/orders', icon: Package },
      { label: 'CTP', path: '/mrp/ctp', icon: Clock },
    ],
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: Settings,
    basePath: '/settings',
    items: [
      { label: 'Geral', path: '/settings', icon: Settings },
      { label: 'Máquinas', path: '/settings/machines', icon: Wrench },
      { label: 'Turnos', path: '/settings/shifts', icon: Clock },
      { label: 'Setup Matrix', path: '/settings/setup-matrix', icon: Grid3x3 },
      { label: 'Operadores', path: '/settings/operators', icon: UserCog },
      { label: 'Clientes', path: '/settings/customers', icon: Building2 },
      { label: 'Scheduling', path: '/settings/scheduling', icon: Sliders },
    ],
  },
];

export function Sidebar() {
  const location = useLocation();
  const [expandedModules, setExpandedModules] = useState<Set<string>>(() => {
    const active = NAV_MODULES.find((m) => location.pathname.startsWith(m.basePath));
    return new Set(active ? [active.id] : ['console']);
  });

  function isModuleActive(mod: NavModule): boolean {
    return location.pathname.startsWith(mod.basePath);
  }

  function isItemActive(path: string): boolean {
    if (path === '/console') return location.pathname === '/console';
    if (path === '/plan') return location.pathname === '/plan';
    if (path === '/mrp') return location.pathname === '/mrp';
    if (path === '/settings') return location.pathname === '/settings';
    return location.pathname.startsWith(path);
  }

  function toggleModule(id: string) {
    setExpandedModules((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <aside className="sidebar">
      <div className="sidebar__logo">
        <Link to="/console" className="sidebar__logo-link">
          <span className="sidebar__logo-icon">PP1</span>
          <span className="sidebar__logo-text">ProdPlan</span>
        </Link>
      </div>

      <nav className="sidebar__nav">
        {NAV_MODULES.map((mod) => {
          const Icon = mod.icon;
          const active = isModuleActive(mod);
          const expanded = expandedModules.has(mod.id);

          return (
            <div
              key={mod.id}
              className={`sidebar__module ${active ? 'sidebar__module--active' : ''}`}
            >
              <button
                type="button"
                className={`sidebar__module-header ${active ? 'sidebar__module-header--active' : ''}`}
                onClick={() => toggleModule(mod.id)}
              >
                <Icon size={18} />
                <span className="sidebar__module-label">{mod.label}</span>
                <ChevronDown
                  size={14}
                  className={`sidebar__chevron ${expanded ? 'sidebar__chevron--open' : ''}`}
                />
              </button>

              {expanded && (
                <div className="sidebar__items">
                  {mod.items.map((item) => {
                    const ItemIcon = item.icon;
                    return (
                      <Link
                        key={item.path}
                        to={item.path}
                        className={`sidebar__item ${isItemActive(item.path) ? 'sidebar__item--active' : ''}`}
                      >
                        <ItemIcon size={14} />
                        <span>{item.label}</span>
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </nav>

      <div className="sidebar__footer">
        <div className="sidebar__user">
          <div className="sidebar__avatar">MN</div>
          <div className="sidebar__user-info">
            <span className="sidebar__user-name">Martim Nicolau</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
