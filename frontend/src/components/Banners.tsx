/** Shown whenever any displayed value is synthetic (CLAUDE.md rule 4). */
export function SyntheticBanner({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <div className="banner synthetic" role="status">
      DEMO / SYNTHETIC DATA — not official statistics
    </div>
  );
}

/** Model outputs (scores, forecasts) are labelled so they are never mistaken for statistics. */
export function ModelBadge({ children = "Model prediction" }: { children?: string }) {
  return <span className="badge model">{children}</span>;
}

export function OfficialBadge() {
  return <span className="badge official">Official statistic</span>;
}
