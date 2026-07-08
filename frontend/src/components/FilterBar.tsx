import { useEffect, useState } from "react";
import { fetchFilterOptions, type SearchFilters } from "../api/client";

interface FilterBarProps {
  filters: SearchFilters;
  onChange: (filters: SearchFilters) => void;
}

export function FilterBar({ filters, onChange }: FilterBarProps) {
  const [crafts, setCrafts] = useState<string[]>([]);
  const [categories, setCategories] = useState<string[]>([]);

  useEffect(() => {
    fetchFilterOptions()
      .then((opts) => {
        setCrafts(opts.crafts);
        setCategories(opts.categories);
      })
      .catch(() => {
        // Dropdowns simply stay empty if options can't load
      });
  }, []);

  function set<K extends keyof SearchFilters>(key: K, value: SearchFilters[K] | undefined) {
    onChange({ ...filters, [key]: value });
  }

  const hasActive =
    filters.craft !== undefined ||
    filters.difficulty !== undefined ||
    filters.free !== undefined ||
    filters.category !== undefined;

  return (
    <div className="filter-bar">
      <select
        className="filter-select"
        value={filters.craft ?? ""}
        onChange={(e) => set("craft", e.target.value || undefined)}
        aria-label="Craft type"
      >
        <option value="">All crafts</option>
        {crafts.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>

      <select
        className="filter-select"
        value={filters.difficulty ?? ""}
        onChange={(e) =>
          set("difficulty", (e.target.value || undefined) as SearchFilters["difficulty"])
        }
        aria-label="Difficulty"
      >
        <option value="">Any difficulty</option>
        <option value="beginner">Beginner</option>
        <option value="intermediate">Intermediate</option>
        <option value="advanced">Advanced</option>
      </select>

      <select
        className="filter-select"
        value={filters.free === undefined ? "" : String(filters.free)}
        onChange={(e) => set("free", e.target.value === "" ? undefined : e.target.value === "true")}
        aria-label="Price"
      >
        <option value="">Free & paid</option>
        <option value="true">Free only</option>
        <option value="false">Paid only</option>
      </select>

      <select
        className="filter-select"
        value={filters.category ?? ""}
        onChange={(e) => set("category", e.target.value || undefined)}
        aria-label="Category"
      >
        <option value="">All categories</option>
        {categories.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>

      {hasActive && (
        <button type="button" className="filter-clear" onClick={() => onChange({})}>
          Clear
        </button>
      )}
    </div>
  );
}
