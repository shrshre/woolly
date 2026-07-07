export function SkeletonCard() {
  return (
    <div className="skeleton-card" aria-hidden="true">
      <div className="skeleton-image"></div>
      <div className="skeleton-body">
        <div className="skeleton-line" style={{ width: "55%" }}></div>
        <div className="skeleton-line" style={{ width: "30%" }}></div>
        <div className="skeleton-line" style={{ width: "90%" }}></div>
        <div className="skeleton-line" style={{ width: "70%" }}></div>
      </div>
    </div>
  );
}
