import { useCallback, useEffect, useRef, useState } from 'react';
import type { Toast as ToastType } from '../../stores/useToastStore';
import { useToastStore } from '../../stores/useToastStore';
import './Toast.css';

const icons: Record<ToastType['type'], string> = {
  success: '\u2713',
  error: '\u2717',
  info: 'i',
  warning: '!',
};

function ToastItem({ toast }: { toast: ToastType }) {
  const removeToast = useToastStore((s) => s.actions.removeToast);
  const [removing, setRemoving] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleClose = useCallback(() => {
    setRemoving(true);
    timerRef.current = setTimeout(() => {
      removeToast(toast.id);
    }, 250);
  }, [removeToast, toast.id]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return (
    <div className={`toast toast--${toast.type}${removing ? ' toast-removing' : ''}`} role="alert">
      <span className="toast-icon">{icons[toast.type]}</span>
      <span className="toast-message">{toast.message}</span>
      <button className="toast-close" onClick={handleClose} aria-label="Close">
        &times;
      </button>
    </div>
  );
}

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);

  if (toasts.length === 0) return null;

  return (
    <div className="toast-container">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} />
      ))}
    </div>
  );
}
