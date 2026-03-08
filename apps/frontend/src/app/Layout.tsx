import type { ReactNode } from 'react';
import { ContextPanel } from '../components/ContextPanel/ContextPanel';
import { FocusStrip } from '../components/FocusStrip/FocusStrip';
import { Sidebar } from './Sidebar';
import './Layout.css';

interface LayoutProps {
  children: ReactNode;
}

export function AppLayout({ children }: LayoutProps) {
  return (
    <div className="app-layout">
      <Sidebar />
      <main className="app-layout__main">{children}</main>
      <FocusStrip />
      <ContextPanel />
    </div>
  );
}
