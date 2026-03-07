import { SchedulingPage as NikufraEngine } from '../../features/scheduling';
import useUIStore from '../../stores/useUIStore';

function Planning() {
  const panelOpen = useUIStore((s) => s.contextPanelOpen);
  return (
    <div style={{ marginRight: panelOpen ? 360 : 0, transition: 'margin-right 0.25s ease' }}>
      <NikufraEngine />
    </div>
  );
}

export default Planning;
