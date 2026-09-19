import { BrowserRouter, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { UserProvider } from "./lib/user";
import { ApprovalsPage } from "./pages/ApprovalsPage";
import { ConsolePage } from "./pages/ConsolePage";
import { MemoryPage } from "./pages/MemoryPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { RunsPage } from "./pages/RunsPage";

export default function App() {
  return (
    <UserProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<ConsolePage />} />
            <Route path="approvals" element={<ApprovalsPage />} />
            <Route path="memory" element={<MemoryPage />} />
            <Route path="runs" element={<RunsPage />} />
            <Route path="runs/:runId" element={<RunDetailPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </UserProvider>
  );
}
