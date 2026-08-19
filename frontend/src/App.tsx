import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import ProductCreate from './pages/ProductCreate';
import ProductDetail from './pages/ProductDetail';
import GenerationEditor from './pages/GenerationEditor';
import HistoryPage from './pages/History';
import KnowledgePage from './pages/Knowledge';
import Login from './pages/Login';
import DesignSkillsPage from './pages/DesignSkills';
import CreativeProjectsPage from './pages/CreativeProjects';
import CreativeCanvasPage from './pages/CreativeCanvas';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="login" element={<Login />} />
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="products/new" element={<ProductCreate />} />
          <Route path="products/:id" element={<ProductDetail />} />
          <Route path="generations/:id" element={<GenerationEditor />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="knowledge" element={<KnowledgePage />} />
          <Route path="design-skills" element={<DesignSkillsPage />} />
          <Route path="creative-projects" element={<CreativeProjectsPage />} />
          <Route path="creative-projects/:id" element={<CreativeCanvasPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
