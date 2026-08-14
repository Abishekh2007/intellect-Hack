export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span
      className="inline-flex items-center justify-center rounded-md bg-primary"
      style={{ width: size, height: size }}
      aria-hidden
    >
      <svg width={size * 0.58} height={size * 0.58} viewBox="0 0 24 24" fill="none">
        <rect x="3" y="13" width="4" height="8" rx="1" fill="white" />
        <rect x="10" y="8" width="4" height="13" rx="1" fill="white" />
        <rect x="17" y="3" width="4" height="18" rx="1" fill="white" />
      </svg>
    </span>
  );
}
