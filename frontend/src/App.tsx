import { Shell } from "./components/Shell";
import { ConfirmProvider } from "./components/ui/ConfirmProvider";

export default function App() {
  return (
    <ConfirmProvider>
      <Shell />
    </ConfirmProvider>
  );
}
