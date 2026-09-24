import React from 'react';

interface ApiErrorBoundaryProps {
  message?: string;
  onRetry?: () => void;
  children: React.ReactNode;
}

interface ApiErrorBoundaryState {
  hasError: boolean;
  errorMessage: string | null;
}

export class ApiErrorBoundary extends React.Component<ApiErrorBoundaryProps, ApiErrorBoundaryState> {
  constructor(props: ApiErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, errorMessage: null };
  }

  static getDerivedStateFromError(error: unknown): ApiErrorBoundaryState {
    return {
      hasError: true,
      errorMessage: error instanceof Error ? error.message : 'Unexpected render failure.',
    };
  }

  componentDidCatch(): void {
    this.setState((s) => (s.hasError ? s : { ...s, hasError: true }));
  }

  private handleRetry = (): void => {
    if (this.props.onRetry) {
      this.setState({ hasError: false, errorMessage: null });
      this.props.onRetry();
    } else {
      this.setState({ hasError: false, errorMessage: null });
    }
  };

  render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        <div className="text-center py-16 bg-neutral-950 rounded-lg border border-neutral-800">
          <p className="text-sm text-neutral-300">
            {this.props.message || this.state.errorMessage || 'Unable to load dashboard summary.'}
          </p>
          <button
            onClick={this.handleRetry}
            className="mt-4 px-3.5 py-1.5 bg-neutral-100 hover:bg-white text-neutral-950 text-xs font-medium rounded-md transition-colors"
          >
            Retry Connection
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ApiErrorBoundary;
