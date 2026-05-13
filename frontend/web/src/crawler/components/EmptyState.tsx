import Icon from './Icon';

export default function EmptyState({
  icon = 'inbox',
  title = 'No data yet',
  hint,
}: {
  icon?: string;
  title?: string;
  hint?: string;
}) {
  return (
    <div className="empty">
      <Icon name={icon} />
      <div style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>{title}</div>
      {hint && <div style={{ fontSize: 12, marginTop: 4 }}>{hint}</div>}
    </div>
  );
}
