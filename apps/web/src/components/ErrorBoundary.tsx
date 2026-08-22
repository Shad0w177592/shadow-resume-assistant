import { Component, type ErrorInfo, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Application render error", { name: error.name, componentStack: info.componentStack });
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="fatal-error" role="alert">
          <h1>页面暂时无法显示</h1>
          <p>你的本地资料没有被删除。请重新打开页面；如果问题持续出现，可以重启应用。</p>
          <button onClick={() => this.setState({ failed: false })}>重试</button>
        </main>
      );
    }
    return this.props.children;
  }
}

