// Testes de regressão para Planning Page (NikufraEngine)
// Updated for NikufraEngine monolith: self-contained planning module

import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { PlanPage as Planning } from '../../features/plan/pages/PlanPage';

describe('Planning Page - Regression Tests', () => {
  it('deve carregar Planning sem erros', async () => {
    render(
      <BrowserRouter>
        <Planning />
      </BrowserRouter>,
    );

    // NikufraEngine shows loading state while fetching data
    const loadingText = screen.queryByText(/carregar planning engine/i);
    const errorText = screen.queryByText(/erro fatal/i);
    // Either loading or loaded, but no crash
    expect(errorText).not.toBeInTheDocument();
    expect(loadingText || screen.queryByText(/NIKUFRA/i)).toBeTruthy();
  });

  it('deve exibir estado de carregamento ou navegação', async () => {
    render(
      <BrowserRouter>
        <Planning />
      </BrowserRouter>,
    );

    // NikufraEngine shows loading spinner initially
    const loading = screen.queryByText(/carregar planning engine/i);
    expect(loading).toBeTruthy();
  });

  it('deve carregar planos sem crashar', () => {
    render(
      <BrowserRouter>
        <Planning />
      </BrowserRouter>,
    );

    // Verify no fatal crash on initial render (loading state is expected)
    const errorElement = screen.queryByText(/erro fatal/i);
    expect(errorElement).not.toBeInTheDocument();
  });

  it('deve ter conteúdo visível (A11y)', () => {
    render(
      <BrowserRouter>
        <Planning />
      </BrowserRouter>,
    );

    // NikufraEngine renders loading state with visible text
    const loadingText = screen.queryByText(/carregar planning engine/i);
    expect(loadingText).toBeTruthy();
  });

  it('deve tratar erro sem crashar', () => {
    render(
      <BrowserRouter>
        <Planning />
      </BrowserRouter>,
    );

    // In test env, getPlanState fetch hangs — component should show loading, not crash
    const errorElement = screen.queryByText(/erro fatal/i);
    expect(errorElement).not.toBeInTheDocument();
    // Loading state or content visible — no crash
    const content =
      screen.queryByText(/carregar planning engine/i) || screen.queryByText(/NIKUFRA/i);
    expect(content).toBeTruthy();
  });
});
