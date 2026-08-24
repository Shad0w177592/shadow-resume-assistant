import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { apiRequest } from "./api";
import { useNotifications } from "./components/Notifications";
import { Onboarding, type BootstrapState } from "./pages/Onboarding";
import { SettingsPage } from "./pages/Settings";
import { HomePage } from "./pages/Home";
import { ProfilePage } from "./pages/Profile";
import { JobsPage } from "./pages/Jobs";
import { ImportPage } from "./pages/Import";
import { WorkbenchPage } from "./pages/Workbench";
import { WorkbenchLandingPage } from "./pages/WorkbenchLanding";

const pages = [
  ["/", "首页", "开始整理资料并生成第一份岗位简历。"],
  ["/profile", "个人资料", "集中维护个人信息、经历、技能和成果。"],
  ["/jobs", "目标岗位", "粘贴岗位描述并查看证据匹配。"],
  ["/workbench", "简历工作台", "选择岗位并生成、修改和导出简历。"],
  ["/settings", "设置", "管理 AI 服务、本地数据和软件信息。"],
] as const;

export function App() {
  const { notify } = useNotifications();
  const [bootstrap, setBootstrap] = useState<BootstrapState | null>(
    window.shadowDesktop ? null : {
      privacy_accepted: true,
      initialized: true,
      onboarding_step: 3,
      api_key_configured: false,
      data_directory: "浏览器测试环境",
    },
  );

  useEffect(() => {
    if (!window.shadowDesktop) return;
    apiRequest<BootstrapState>("/api/bootstrap")
      .then(setBootstrap)
      .catch((error) => notify(error.message, "error"));
  }, [notify]);

  if (!bootstrap) return <main className="startup-state">正在启动本地服务…</main>;
  if (!bootstrap.initialized) {
    return <Onboarding initial={bootstrap} onComplete={() => setBootstrap({ ...bootstrap, initialized: true, onboarding_step: 3 })} />;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark" aria-hidden="true">影</span><span className="brand-copy">影子简历助手<small>LOCAL RESUME DESK</small></span></div>
        <nav aria-label="主导航">
          {pages.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              {label}
            </NavLink>
          ))}
        </nav>
        <p className="local-note"><span aria-hidden="true">▣</span> 数据仅保存在这台电脑</p>
      </aside>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/imports" element={<ImportPage />} />
        <Route path="/workbench" element={<WorkbenchLandingPage />} />
        <Route path="/workbench/:jobId" element={<WorkbenchPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </div>
  );
}
