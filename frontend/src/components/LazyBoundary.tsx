import { Suspense, type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { ErrorBoundary } from './ErrorBoundary';

const Spinner = (
  <div className="flex-1 flex items-center justify-center p-6 text-fg-muted">
    <Loader2 size={20} className="animate-spin" />
  </div>
);

interface LazyBoundaryProps {
  children: ReactNode;
  title: string;
  fallback?: ReactNode;
}

/** Suspense per un componente caricato con React.lazy; se il chunk non arriva (es. dopo un deploy) mostra l'errore invece di far cadere l'app. */
export const LazyBoundary = ({ children, title, fallback = Spinner }: LazyBoundaryProps) => (
  <ErrorBoundary title={title}>
    <Suspense fallback={fallback}>{children}</Suspense>
  </ErrorBoundary>
);
