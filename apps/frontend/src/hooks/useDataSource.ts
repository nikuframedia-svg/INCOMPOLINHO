import { useAppStore } from '../stores/useAppStore';

export function useDataSource() {
  // Use selector to only re-render when dataSource changes (not on any store update)
  return useAppStore((state) => state.dataSource);
}
