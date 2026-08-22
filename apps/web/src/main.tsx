import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { NotificationProvider } from "./components/Notifications";
import "./styles.css";
import "./print.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HashRouter>
      <ErrorBoundary>
        <NotificationProvider>
          <App />
        </NotificationProvider>
      </ErrorBoundary>
    </HashRouter>
  </React.StrictMode>,
);
