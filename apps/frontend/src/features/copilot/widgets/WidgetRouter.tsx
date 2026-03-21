/**
 * WidgetRouter — renders structured widget data from copilot tool calls.
 */

import type { CopilotWidget } from '../copilotApi';
import { AlertsWidget } from './AlertsWidget';
import { DecisionsWidget } from './DecisionsWidget';
import { KpiCompareWidget } from './KpiCompareWidget';
import { MachineLoadWidget } from './MachineLoadWidget';
import { ProductionWidget } from './ProductionWidget';
import { RobustnessWidget } from './RobustnessWidget';
import { SkuDetailWidget } from './SkuDetailWidget';
import { SuggestionsWidget } from './SuggestionsWidget';

const WIDGET_MAP: Record<string, React.FC<{ data: Record<string, unknown> }>> = {
  machine_load: MachineLoadWidget,
  production_table: ProductionWidget,
  alerts_list: AlertsWidget,
  robustness: RobustnessWidget,
  sku_detail: SkuDetailWidget,
  decisions_table: DecisionsWidget,
  kpi_compare: KpiCompareWidget,
  suggestions: SuggestionsWidget,
};

export function WidgetRouter({ widgets }: { widgets: CopilotWidget[] }) {
  return (
    <div className="copilot-widgets">
      {widgets.map((w, i) => {
        const Component = WIDGET_MAP[w.type];
        if (!Component) return null;
        return <Component key={`${w.type}-${i}`} data={w.data} />;
      })}
    </div>
  );
}
