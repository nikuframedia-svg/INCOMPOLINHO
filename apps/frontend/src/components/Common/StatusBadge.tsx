import './StatusBadge.css';

interface StatusBadgeProps {
  status: string;
  size?: 'sm' | 'md' | 'lg';
}

const statusColors: Record<string, string> = {
  // Plan statuses
  CANDIDATE: 'orange',
  OFFICIAL: 'green',
  DRAFT: 'gray',

  // PR statuses
  OPEN: 'blue',
  APPROVED: 'green',
  MERGED: 'purple',
  REJECTED: 'red',
  ROLLED_BACK: 'orange',

  // Job statuses
  QUEUED: 'gray',
  RUNNING: 'blue',
  COMPLETED: 'green',
  SUCCEEDED: 'green',
  FAILED: 'red',
  CANCELLED: 'orange',
  TIMEBOXED: 'yellow',

  // Scenario statuses
  PENDING: 'gray',
  COMPUTING: 'blue',
  COMPUTED: 'green',
  PR_CREATED: 'purple',

  // Suggestion statuses
  ACCEPTED: 'green',
  IMPLEMENTED: 'purple',
  EXPIRED: 'gray',
};

export function StatusBadge({ status, size = 'md' }: StatusBadgeProps) {
  const color = statusColors[status] || 'gray';

  return (
    <span className={`status-badge status-badge--${color} status-badge--${size}`}>{status}</span>
  );
}
