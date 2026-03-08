import { Construction } from 'lucide-react';
import { SkeletonCard } from './SkeletonLoader';

interface StubPageProps {
  title: string;
  description: string;
}

export function StubPage({ title, description }: StubPageProps) {
  return (
    <div style={{ padding: 32 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <Construction size={20} style={{ color: 'var(--text-muted)' }} />
        <h2 style={{ color: 'var(--text-primary)', fontSize: 'var(--text-h3)', fontWeight: 600 }}>
          {title}
        </h2>
      </div>
      <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-body)', marginBottom: 24 }}>
        {description}
      </p>
      <SkeletonCard lines={5} />
    </div>
  );
}
