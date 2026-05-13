import Icon from './Icon';
import { fmtNum } from '../format';

type Tone = 'primary' | 'accent' | 'green' | 'red' | 'blue' | 'muted';

export default function StatCard({
  tone = 'primary',
  icon,
  label,
  value,
}: {
  tone?: Tone;
  icon: string;
  label: string;
  value: number | string | null | undefined;
}) {
  return (
    <div className={`stat ${tone}`}>
      <div className="icon">
        <Icon name={icon} />
      </div>
      <div>
        <div className="label">{label}</div>
        <div className="value">{typeof value === 'number' ? fmtNum(value) : value ?? '—'}</div>
      </div>
    </div>
  );
}
