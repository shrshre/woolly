import { RotatingSearchInput } from "./RotatingSearchInput";

const SEARCH_SAMPLES = [
  "cozy winter sweater",
  "quick gift for beginners",
  "no seaming required",
  "colorful stranded project",
  "something for my cat",
] as const;

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
      <RotatingSearchInput
        value={value}
        onChange={onChange}
        disabled={disabled}
        ariaLabel="Search patterns"
        samples={SEARCH_SAMPLES}
      />
      <button type="submit" className="search-submit" aria-label="Search" disabled={disabled}>
        <i className="ti ti-arrow-right" aria-hidden="true"></i>
      </button>
    </form>
  );
}
