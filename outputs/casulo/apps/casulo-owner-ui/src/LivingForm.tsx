interface LivingFormProps {
  state: string;
  evidenceCount: number;
  reducedMotion: boolean;
}

const ACTIVE_STATES = new Set(["THINKING", "FIRST_FORM", "FORMATION"]);

export function LivingForm({ state, evidenceCount, reducedMotion }: LivingFormProps) {
  const nodeCount = Math.max(1, Math.min(7, evidenceCount + 1));
  const nodes = Array.from({ length: nodeCount }, (_, index) => {
    const angle = (Math.PI * 2 * index) / nodeCount - Math.PI / 2;
    return { x: 160 + Math.cos(angle) * 86, y: 160 + Math.sin(angle) * 86 };
  });
  const active = ACTIVE_STATES.has(state);
  return (
    <div
      className={`living-form living-form--${state.toLowerCase()} ${active ? "is-active" : ""} ${reducedMotion ? "is-still" : ""}`}
      role="img"
      aria-label={`Forma viva do Casulo no estado ${state}; ${evidenceCount} evidências aceitas`}
    >
      <div className="living-form__field" />
      <svg className="living-form__graph" viewBox="0 0 320 320" aria-hidden="true">
        <defs>
          <radialGradient id="core" cx="45%" cy="38%">
            <stop offset="0" stopColor="#fff8df" stopOpacity=".94" />
            <stop offset=".34" stopColor="#e5a33b" stopOpacity=".7" />
            <stop offset="1" stopColor="#102a56" stopOpacity=".08" />
          </radialGradient>
          <filter id="softGlow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="8" />
          </filter>
        </defs>
        {nodes.slice(1).map((node, index) => (
          <path
            key={`path-${index}`}
            className="living-form__thread"
            d={`M160 160 Q${(160 + node.x) / 2 + (index % 2 ? 18 : -18)} ${(160 + node.y) / 2} ${node.x} ${node.y}`}
          />
        ))}
        {nodes.map((node, index) => (
          <g key={`node-${index}`} className="living-form__node" style={{ "--node-index": index } as React.CSSProperties}>
            <circle cx={node.x} cy={node.y} r={index === 0 ? 7 : 4.2} />
            <circle className="living-form__node-glow" cx={node.x} cy={node.y} r={index === 0 ? 18 : 12} />
          </g>
        ))}
        <circle className="living-form__core-glow" cx="160" cy="160" r="58" fill="url(#core)" filter="url(#softGlow)" />
        <circle className="living-form__core" cx="160" cy="160" r="32" fill="url(#core)" />
      </svg>
      <span className="living-form__state">{labelForState(state)}</span>
    </div>
  );
}

function labelForState(state: string): string {
  const labels: Record<string, string> = {
    SILENCE: "em silêncio",
    PRESENCE: "presente",
    LISTENING: "escutando",
    THINKING: "compreendendo",
    CONVERSATION: "conversando",
    FIRST_FORM: "primeira forma",
    FORMATION: "ganhando forma",
    MATERIALIZED: "materializada",
    CANCELLED: "preservada",
    RECOVERABLE_FAILURE: "aguardando retomada",
  };
  return labels[state] ?? "presente";
}
