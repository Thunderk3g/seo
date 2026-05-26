/**
 * Per-route error boundary. Keeps a crashing page (e.g. the 3D content
 * map, whose r3f reconciler fails against React 18) from taking down
 * the whole app shell.
 */
import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** Friendly label shown in the fallback message. */
  label?: string;
  /** Optional hint shown alongside the error (e.g. "downgrade r3f"). */
  hint?: string;
}

interface State {
  error: Error | null;
}

export default class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    // eslint-disable-next-line no-console
    console.error('[RouteErrorBoundary]', this.props.label || 'route', error);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          padding: 24, maxWidth: 760, margin: '40px auto',
          border: '1px solid #FCA5A5', borderRadius: 8, background: '#FEF2F2',
        }}>
          <h2 style={{ margin: 0, color: '#B91C1C', fontSize: 18 }}>
            {this.props.label || 'This page'} failed to load
          </h2>
          <pre style={{
            marginTop: 12, padding: 12, background: '#FFFFFF',
            border: '1px solid #FECACA', borderRadius: 6,
            fontSize: 12, overflow: 'auto', color: '#7F1D1D',
          }}>
            {this.state.error.message}
          </pre>
          {this.props.hint && (
            <p style={{ marginTop: 12, fontSize: 13, color: '#7F1D1D' }}>
              <strong>Hint:</strong> {this.props.hint}
            </p>
          )}
          <p style={{ marginTop: 12, fontSize: 13, color: '#7F1D1D' }}>
            The rest of the app is still usable — pick another item from the sidebar.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}
