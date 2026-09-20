import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  title?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary ha catturato un errore non gestito:', error, errorInfo);
    this.setState({ error, errorInfo });
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  private handleReload = () => {
    window.location.reload();
  };

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="m-4 p-6 rounded-2xl border border-rose-500/30 bg-rose-950/20 backdrop-blur-md shadow-2xl text-fg space-y-4 max-w-2xl mx-auto">
          <div className="flex items-center gap-3 text-rose-400">
            <div className="p-2.5 rounded-xl bg-rose-500/20 border border-rose-500/40">
              <AlertTriangle size={22} />
            </div>
            <div>
              <h3 className="font-semibold text-base">
                {this.props.title || 'Si è verificato un errore di visualizzazione'}
              </h3>
              <p className="text-xs text-rose-300/80">
                La componente ha riscontrato un problema imprevisto durante il rendering.
              </p>
            </div>
          </div>

          {this.state.error && (
            <div className="p-3 rounded-xl bg-panel/80 border border-border/80 text-xs font-mono text-rose-300 overflow-x-auto max-h-40">
              {this.state.error.toString()}
            </div>
          )}

          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={this.handleReset}
              className="px-4 py-2 rounded-xl bg-panel hover:bg-panel/80 text-xs font-medium border border-border transition cursor-pointer"
            >
              Riprova
            </button>
            <button
              onClick={this.handleReload}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-rose-500 hover:bg-rose-600 text-white text-xs font-semibold shadow-md transition cursor-pointer"
            >
              <RefreshCw size={13} />
              <span>Ricarica Pagina</span>
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
