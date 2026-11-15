import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppDataProvider } from "./context/AppData";
import { ToastProvider } from "./components/Toast";
import { Layout } from "./components/Layout";
import { Overview } from "./pages/Overview";
import { DataExplorer } from "./pages/DataExplorer";
import { Harmonization } from "./pages/Harmonization";
import { Uncertainty } from "./pages/Uncertainty";
import { Models } from "./pages/Models";
import { Audit } from "./pages/Audit";
import { LiveAnalysis } from "./pages/LiveAnalysis";

export default function App() {
  return (
    <HashRouter>
      <ToastProvider>
        <AppDataProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<Overview />} />
              <Route path="explorer" element={<DataExplorer />} />
              <Route path="harmonization" element={<Harmonization />} />
              <Route path="uncertainty" element={<Uncertainty />} />
              <Route path="models" element={<Models />} />
              <Route path="audit" element={<Audit />} />
              <Route path="live" element={<LiveAnalysis />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </AppDataProvider>
      </ToastProvider>
    </HashRouter>
  );
}
