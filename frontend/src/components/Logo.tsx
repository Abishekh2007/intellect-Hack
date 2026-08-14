export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span
      className="brand-gradient inline-flex items-center justify-center rounded-lg shadow-[var(--shadow-glow)]"
      style={{ width: size, height: size }}
      aria-hidden
    >
      <svg width={size * 0.6} height={size * 0.6} viewBox="0 0 24 24" fill="none">
        <rect x="3" y="13" width="4" height="8" rx="1.4" fill="white" opacity="0.95" />
        <rect x="10" y="8" width="4" height="13" rx="1.4" fill="white" opacity="0.8" />
        <rect x="17" y="3" width="4" height="18" rx="1.4" fill="white" opacity="0.65" />
      </svg>
    </span>
  );
}
