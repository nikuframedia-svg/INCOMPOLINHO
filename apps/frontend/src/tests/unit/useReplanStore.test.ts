// Testes unitários para useReplanStore (simplified — legacy backend logic removed)

import { beforeEach, describe, expect, it } from 'vitest';
import { useReplanStore } from '../../stores/useReplanStore';

describe('useReplanStore', () => {
  beforeEach(() => {
    useReplanStore.setState({ onApplyCallback: null });
  });

  it('deve ter estado inicial correcto', () => {
    const state = useReplanStore.getState();
    expect(state.onApplyCallback).toBeNull();
  });

  it('deve permitir set/get de onApplyCallback', () => {
    const cb = () => {};
    useReplanStore.setState({ onApplyCallback: cb });
    expect(useReplanStore.getState().onApplyCallback).toBe(cb);
  });

  it('deve limpar onApplyCallback', () => {
    useReplanStore.setState({ onApplyCallback: () => {} });
    useReplanStore.setState({ onApplyCallback: null });
    expect(useReplanStore.getState().onApplyCallback).toBeNull();
  });
});
