interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
}

export function SearchBar({ value, onChange, onSubmit, disabled }: SearchBarProps) {
  return (
    <form
      className="search-bar"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <span className="search-icon">
        <i className="ti ti-search" aria-hidden="true"></i>
      </span>
      <input
        type="text"
        className="search-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Try “cozy winter sweater” or “quick gift for beginners”"
        aria-label="Search patterns"
      />
      <button type="submit" className="search-submit" aria-label="Search" disabled={disabled}>
        <i className="ti ti-arrow-right" aria-hidden="true"></i>
      </button>
    </form>
  );
}
