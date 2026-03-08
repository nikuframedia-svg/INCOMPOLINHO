import type { LucideIcon } from 'lucide-react';
import { Building2, ChevronRight, Clock, Grid3x3, Sliders, UserCog, Wrench } from 'lucide-react';
import { Link } from 'react-router-dom';

interface SettingsCard {
  title: string;
  description: string;
  icon: LucideIcon;
  path: string;
}

const SETTINGS_CARDS: SettingsCard[] = [
  {
    title: 'Máquinas',
    description: 'Configuração de prensas e capacidades',
    icon: Wrench,
    path: '/settings/machines',
  },
  {
    title: 'Turnos',
    description: 'Horários e turnos de produção',
    icon: Clock,
    path: '/settings/shifts',
  },
  {
    title: 'Setup Matrix',
    description: 'Tempos de setup entre ferramentas',
    icon: Grid3x3,
    path: '/settings/setup-matrix',
  },
  {
    title: 'Operadores',
    description: 'Equipas e competências',
    icon: UserCog,
    path: '/settings/operators',
  },
  {
    title: 'Clientes',
    description: 'Gestão de clientes e prioridades',
    icon: Building2,
    path: '/settings/customers',
  },
  {
    title: 'Scheduling',
    description: 'Pesos, políticas e constraints',
    icon: Sliders,
    path: '/settings/scheduling',
  },
];

const gridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
  gap: 16,
};

const cardStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 16,
  padding: 20,
  background: 'var(--bg-card)',
  borderRadius: 8,
  border: '1px solid var(--border-default)',
  textDecoration: 'none',
  transition: 'border-color 0.15s, background 0.15s',
};

const cardHoverHandlers = (e: React.MouseEvent<HTMLAnchorElement>) => {
  const el = e.currentTarget;
  el.style.borderColor = 'var(--accent)';
  el.style.background = 'var(--bg-raised)';
};

const cardLeaveHandlers = (e: React.MouseEvent<HTMLAnchorElement>) => {
  const el = e.currentTarget;
  el.style.borderColor = 'var(--border-default)';
  el.style.background = 'var(--bg-card)';
};

export function SettingsPage() {
  return (
    <div style={{ padding: 32, display: 'flex', flexDirection: 'column', gap: 24 }}>
      <h2 style={{ color: 'var(--text-primary)', fontSize: 'var(--text-h3)', fontWeight: 600 }}>
        Configurações
      </h2>
      <div style={gridStyle}>
        {SETTINGS_CARDS.map((card) => {
          const Icon = card.icon;
          return (
            <Link
              key={card.path}
              to={card.path}
              style={cardStyle}
              onMouseEnter={cardHoverHandlers}
              onMouseLeave={cardLeaveHandlers}
            >
              <Icon size={24} style={{ color: 'var(--accent)', flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    color: 'var(--text-primary)',
                    fontWeight: 500,
                    fontSize: 'var(--text-body)',
                  }}
                >
                  {card.title}
                </div>
                <div
                  style={{
                    color: 'var(--text-muted)',
                    fontSize: 'var(--text-small)',
                    marginTop: 4,
                  }}
                >
                  {card.description}
                </div>
              </div>
              <ChevronRight size={16} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
            </Link>
          );
        })}
      </div>
    </div>
  );
}
