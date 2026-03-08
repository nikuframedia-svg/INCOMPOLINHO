import { IntelligencePage as NikufraIntel } from '../../features/intelligence';
import { useUIStore } from '../../stores/useUIStore';

export function Intelligence() {
  const panelOpen = useUIStore((s) => s.contextPanelOpen);
  return (
    <div style={{ marginRight: panelOpen ? 360 : 0, transition: 'margin-right 0.25s ease' }}>
      <NikufraIntel />
    </div>
  );
}
