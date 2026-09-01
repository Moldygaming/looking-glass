const labels: Record<string, string> = { azure: "Azure", aws: "AWS", gcp: "GCP" };
const tones: Record<string, string> = {
  azure: "bg-sky-400/10 text-sky-300 border-sky-400/20",
  aws: "bg-orange-400/10 text-orange-300 border-orange-400/20",
  gcp: "bg-yellow-400/10 text-yellow-200 border-yellow-400/20",
};

export function ProviderBadge({ provider }: { provider: string }) {
  return (
    <span className={`chip ${tones[provider] || ""}`}>
      {labels[provider] || provider}
    </span>
  );
}
