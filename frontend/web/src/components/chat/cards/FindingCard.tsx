type Severity = 'critical' | 'warning' | 'notice';

export default function FindingCard({
  payload,
}: {
  payload: Record<string, unknown>;
}) {
  const title = String(payload.title ?? 'Recommendation');
  const severity = (String(payload.severity ?? 'notice') as Severity);
  const description = String(payload.description ?? '');
  const recommendation = String(payload.recommendation ?? '');
  const refs = (payload.evidence_refs as string[]) || [];
  return (
    <div className={`seo-card chat-card chat-card-finding sev-${severity}`}>
      <div className="chat-card-finding-head">
        <span className={`chat-card-sev sev-${severity}`}>{severity}</span>
        <div className="chat-card-title">{title}</div>
      </div>
      {description && (
        <p className="chat-card-finding-desc">{description}</p>
      )}
      {recommendation && (
        <p className="chat-card-finding-rec">
          <strong>Action:</strong> {recommendation}
        </p>
      )}
      {refs.length > 0 && (
        <div className="chat-card-finding-refs">
          {refs.map((r, i) => (
            <code key={i}>{r}</code>
          ))}
        </div>
      )}
    </div>
  );
}
