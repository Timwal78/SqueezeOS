import { Routes, Route } from "react-router"
import AppShell from "./components/AppShell"
import Home from "./pages/Home"
import RegistryPage from "./pages/RegistryPage"
import HoneytrapPage from "./pages/HoneytrapPage"
import HustlerPage from "./pages/HustlerPage"
import Login from "./pages/Login"
import NotFound from "./pages/NotFound"

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/registry" element={<RegistryPage />} />
        <Route path="/honeytrap" element={<HoneytrapPage />} />
        <Route path="/hustler" element={<HustlerPage />} />
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AppShell>
  )
}
