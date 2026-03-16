import { Breadcrumb } from 'antd';
import { Menu, MessageSquare, Search } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { NotificationBell } from '../components/Common/NotificationBell';
import { TrustGateBanner } from '../components/Common/TrustGateBanner';
import { ContextPanel } from '../components/ContextPanel/ContextPanel';
import { FocusStrip } from '../components/FocusStrip/FocusStrip';
import { AmbientBackground } from '../components/ui/AmbientBackground';
import { useDeliveryAlertGenerator } from '../features/alerts/useDeliveryAlertGenerator';
import { useNightShiftAlertGenerator } from '../features/alerts/useNightShiftAlertGenerator';
import { useStockAlertGenerator } from '../features/alerts/useStockAlertGenerator';
import { ChatPanel } from '../features/copilot/ChatPanel';
import {
  useCopilotPanelOpen,
  useSidebarCollapsed,
  useSidebarMobileOpen,
  useUIActions,
} from '../stores/useUIStore';
import { Sidebar } from './Sidebar';
import './Layout.css';

interface LayoutProps {
  children: ReactNode;
}

const ROUTE_LABELS: Record<string, string> = {
  console: 'Visão Geral',
  plan: 'Plano',
  mrp: 'Materiais',
  settings: 'Settings',
  replan: 'Replan',
  whatif: 'What If',
  data: 'Dados',
  orders: 'Encomendas',
  ctp: 'CTP',
  machines: 'Máquinas',
  shifts: 'Turnos',
  'setup-matrix': 'Setup Matrix',
  operators: 'Operadores',
  customers: 'Clientes',
  scheduling: 'Scheduling',
  rules: 'Regras',
  formulas: 'Fórmulas',
  definitions: 'Definições',
  workflows: 'Workflows',
  strategy: 'Estratégia',
};

const MOBILE_BREAKPOINT = 768;

function AppHeader() {
  useStockAlertGenerator();
  useNightShiftAlertGenerator();
  useDeliveryAlertGenerator();
  const mobileOpen = useSidebarMobileOpen();
  const {
    toggleSidebar,
    openMobileSidebar,
    closeMobileSidebar,
    openCommandPalette,
    toggleCopilotPanel,
  } = useUIActions();
  const location = useLocation();

  const segments = location.pathname.split('/').filter(Boolean);
  const breadcrumbItems = [
    { title: <Link to="/">Home</Link> },
    ...segments.map((seg, i) => {
      const path = `/${segments.slice(0, i + 1).join('/')}`;
      const label = ROUTE_LABELS[seg] ?? seg;
      const isLast = i === segments.length - 1;
      return {
        title: isLast ? label : <Link to={path}>{label}</Link>,
      };
    }),
  ];

  function handleHamburgerClick() {
    if (window.innerWidth <= MOBILE_BREAKPOINT) {
      if (mobileOpen) closeMobileSidebar();
      else openMobileSidebar();
    } else {
      toggleSidebar();
    }
  }

  return (
    <header className="app-header">
      <button
        type="button"
        className="app-header__hamburger"
        onClick={handleHamburgerClick}
        title="Toggle sidebar"
      >
        <Menu size={18} />
      </button>
      <Breadcrumb items={breadcrumbItems} />
      <div className="app-header__actions">
        <button
          type="button"
          className="app-header__copilot-btn"
          onClick={toggleCopilotPanel}
          title="Copilot (Ctrl+Shift+K)"
        >
          <MessageSquare size={16} />
        </button>
        <NotificationBell />
        <button type="button" className="app-header__search-pill" onClick={openCommandPalette}>
          <Search size={14} />
          <span>Pesquisar...</span>
          <kbd>&#8984;K</kbd>
        </button>
      </div>
    </header>
  );
}

export function AppLayout({ children }: LayoutProps) {
  const sidebarCollapsed = useSidebarCollapsed();
  const copilotOpen = useCopilotPanelOpen();
  const { closeCopilotPanel } = useUIActions();

  return (
    <div className={`app-layout ${sidebarCollapsed ? 'app-layout--collapsed' : ''}`}>
      <AmbientBackground />
      <Sidebar />
      <main className="app-layout__main" aria-label="Conteúdo principal">
        <AppHeader />
        <TrustGateBanner />
        <div className="app-layout__content">{children}</div>
      </main>
      <FocusStrip />
      <ContextPanel />
      <ChatPanel open={copilotOpen} onClose={closeCopilotPanel} />
    </div>
  );
}
