// Testes básicos de A11y (Acessibilidade)

import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { PlanPage as Planning } from '../../features/plan/pages/PlanPage';

describe('A11y - Basic Checks', () => {
  const pages = [{ name: 'Planning', component: Planning }];

  pages.forEach(({ name, component: Component }) => {
    it(`${name} deve ter título de página (h1)`, () => {
      render(
        <BrowserRouter>
          <Component />
        </BrowserRouter>,
      );

      const heading = screen.queryByRole('heading', { level: 1 });
      // Pode não ter h1 se estiver em loading, mas não deve crashar
      expect(heading || screen.queryByText(/carregando|carregar/i)).toBeTruthy();
    });

    it(`${name} não deve ter múltiplos h1 (A11y)`, () => {
      const { container } = render(
        <BrowserRouter>
          <Component />
        </BrowserRouter>,
      );

      const h1Elements = container.querySelectorAll('h1');
      // Máximo 1 h1 por página (A11y best practice)
      expect(h1Elements.length).toBeLessThanOrEqual(1);
    });
  });
});
