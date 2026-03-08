import { useParams } from 'react-router-dom';
import { StubPage } from '@/components/Common/StubPage';

export function ConsoleDay() {
  const { date } = useParams<{ date: string }>();
  return (
    <StubPage
      title={`Console — ${date ?? 'Dia'}`}
      description="Vista detalhada do dia em desenvolvimento."
    />
  );
}
