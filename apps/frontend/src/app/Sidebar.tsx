import { Badge, Tooltip } from 'antd';
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Eye,
  Package,
  CalendarRange,
  Boxes,
  Settings,
  BarChart3,
  Repeat,
  FlaskConical,
  Database,
  ShoppingCart,
  Clock,
  Brain,
  ShieldAlert,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { TrustIndexBadge } from '@/components/Common/TrustIndexBadge';
import { useMrpRiskCount, useSidebarCollapsed, useSidebarMobileOpen, useUIActions } from '@/stores/useUIStore';
import { badgeTooltip } from '@/utils/explicitText';
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
  items?: NavItem[];
  badgeCount?: number;
}

const NAV_MODULES: NavModule[] = [
  {
    id: 'overview',
    label: 'Visão Geral',
    icon: Eye,
    basePath: '/console',
    items: [{ label: 'Dia-a-dia', path: '/console', icon: Eye }],
  },
  {
    id: 'plan',
    label: 'Plano',
    icon: CalendarRange,
    basePath: '/plan',
    items: [
      { label: 'Gantt', path: '/plan', icon: BarChart3 },
      { label: 'Replan', path: '/plan/replan', icon: Repeat },
      { label: 'What If', path: '/plan/whatif', icon: FlaskConical },
      { label: 'Dados', path: '/plan/data', icon: Database },
    ],
  },
  {
    id: 'materials',
    label: 'Materiais',
    icon: Boxes,
    basePath: '/mrp',
    items: [
      { label: 'Vista Geral', path: '/mrp', icon: Package },
      { label: 'Encomendas', path: '/mrp/orders', icon: ShoppingCart },
      { label: 'CTP', path: '/mrp/ctp', icon: Clock },
    ],
  },
  {
    id: 'intelligence',
    label: 'Análise',
    icon: Brain,
    basePath: '/intelligence',
    items: [{ label: 'Intelligence', path: '/intelligence', icon: Brain }],
  },
  {
    id: 'risk',
    label: 'Risco',
    icon: ShieldAlert,
    basePath: '/risk',
    items: [{ label: 'Mapa de Risco', path: '/risk', icon: ShieldAlert }],
  },
];

export function Sidebar() {
  const location = useLocation();
  const collapsed = useSidebarCollapsed();
  const mobileOpen = useSidebarMobileOpen();
  const { toggleSidebar, closeMobileSidebar } = useUIActions();
  const mrpRiskCount = useMrpRiskCount();
  const [expandedModules, setExpandedModules] = useState<Set<string>>(() => {
    const active = NAV_MODULES.find((m) => location.pathname.startsWith(m.basePath));
    return new Set(active ? [active.id] : ['overview']);
  });

  function isModuleActive(mod: NavModule): boolean {
    return location.pathname.startsWith(mod.basePath);
  }

  function isItemActive(path: string): boolean {
    if (path === '/console') return location.pathname === '/console';
    if (path === '/plan') return location.pathname === '/plan';
    if (path === '/mrp') return location.pathname === '/mrp';
    if (path === '/intelligence') return location.pathname === '/intelligence';
    if (path === '/risk') return location.pathname === '/risk';
    return location.pathname.startsWith(path);
  }

  const isSettingsActive = location.pathname.startsWith('/settings');

  // Close mobile sidebar on navigation
  const pathname = location.pathname;
  useEffect(() => {
    closeMobileSidebar();
  }, [pathname, closeMobileSidebar]);

  // Close mobile sidebar when resizing to desktop
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 769px)');
    const handler = (e: MediaQueryListEvent) => {
      if (e.matches) closeMobileSidebar();
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [closeMobileSidebar]);

  function toggleModule(id: string) {
    setExpandedModules((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <>
      {mobileOpen && (
        <div
          className="sidebar-overlay"
          role="presentation"
          onClick={closeMobileSidebar}
          onKeyDown={(e) => {
            if (e.key === 'Escape') closeMobileSidebar();
          }}
        />
      )}
      <aside
        className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''} ${mobileOpen ? 'sidebar--mobile-open' : ''}`}
        aria-label="Navegação principal"
      >
        <div className="sidebar__logo">
          <Link to="/console" className="sidebar__logo-link">
            <span className="sidebar__logo-icon">PP1</span>
            {!collapsed && <span className="sidebar__logo-text">ProdPlan</span>}
          </Link>
        </div>

        <TrustIndexBadge collapsed={collapsed} />

        <nav className="sidebar__nav" aria-label="Módulos do sistema">
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
                  onClick={() => (collapsed ? toggleSidebar() : toggleModule(mod.id))}
                  title={collapsed ? mod.label : undefined}
                >
                  {(() => {
                    const badge = mod.id === 'materials' ? mrpRiskCount : mod.badgeCount;
                    const module = mod.id === 'materials' ? 'materials' as const
                      : mod.id === 'plan' ? 'plan' as const
                      : 'alerts' as const;
                    return badge ? (
                      <Tooltip title={badgeTooltip(module, badge)} placement="right">
                        <Badge count={badge} size="small" offset={[4, -4]}>
                          <Icon size={18} />
                        </Badge>
                      </Tooltip>
                    ) : (
                      <Icon size={18} />
                    );
                  })()}
                  {!collapsed && <span className="sidebar__module-label">{mod.label}</span>}
                  {!collapsed && mod.items && (
                    <ChevronDown
                      size={14}
                      className={`sidebar__chevron ${expanded ? 'sidebar__chevron--open' : ''}`}
                    />
                  )}
                </button>

                {!collapsed && expanded && mod.items && (
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
          <Link
            to="/settings"
            className={`sidebar__settings-btn ${isSettingsActive ? 'sidebar__settings-btn--active' : ''}`}
            title={collapsed ? 'Definições' : undefined}
            aria-label="Definições"
          >
            <Settings size={16} />
            {!collapsed && <span>Definições</span>}
          </Link>
          <button
            type="button"
            className="sidebar__collapse-btn"
            onClick={toggleSidebar}
            title={collapsed ? 'Expandir sidebar' : 'Colapsar sidebar'}
            aria-label={collapsed ? 'Expandir sidebar' : 'Colapsar sidebar'}
          >
            {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </button>
          <div className="sidebar__user">
            <div className="sidebar__avatar">MN</div>
            {!collapsed && (
              <div className="sidebar__user-info">
                <span className="sidebar__user-name">Martim Nicolau</span>
              </div>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
