import Button from './Button';
import Icon from './Icon';
import { fmtDuration } from '../format';

export default function ControlBar({
  running,
  elapsed,
  rate,
  onStart,
  onStop,
  onClear,
}: {
  running: boolean;
  elapsed: number;
  rate: number;
  onStart: () => void;
  onStop: () => void;
  onClear: () => void;
}) {
  return (
    <div className="controls">
      <Button variant="primary" icon="play_arrow" onClick={onStart} disabled={running}>
        Start crawl
      </Button>
      <Button variant="danger" icon="stop" onClick={onStop} disabled={!running}>
        Stop
      </Button>
      <Button variant="ghost" icon="clear_all" onClick={onClear}>
        Clear logs
      </Button>

      <div className="divider" />

      <div className="meter">
        <Icon name="schedule" size="16px" />
        Elapsed&nbsp;<b>{fmtDuration(elapsed)}</b>
      </div>
      <div className="meter">
        <Icon name="speed" size="16px" />
        Rate&nbsp;<b>{rate}</b>/min
      </div>

      <div style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
        <Icon name="info" size="14px" style={{ verticalAlign: 'middle' }} />
        &nbsp;Live telemetry via WebSocket · checkpoint every 500 pages
      </div>
    </div>
  );
}
