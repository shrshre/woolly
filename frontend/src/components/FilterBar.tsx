import { useEffect, useRef, useState } from "react";
import { fetchFilterOptions, type SearchFilters } from "../api/client";

interface FilterBarProps {
  filters: SearchFilters;
  onChange: (filters: SearchFilters) => void;
}

/** A single "Filters" button (with a count of active filters) that opens a
 *  popover holding the dropdowns, so the search area stays compact. */
export function FilterBar({ filters, onChange }: FilterBarProps) {
  const [crafts, setCrafts] = useState<string[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

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

  // Close on outside click or Escape while the popover is open.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent | TouchEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("touchstart", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("touchstart", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function set<K extends keyof SearchFilters>(key: K, value: SearchFilters[K] | undefined) {
    onChange({ ...filters, [key]: value });
  }

  const activeCount = [filters.craft, filters.difficulty, filters.free, filters.category].filter(
    (v) => v !== undefined,
  ).length;

  const cls = (active: boolean) => (active ? "filter-select is-active" : "filter-select");

  return (
    <div className="filter-bar" ref={rootRef}>
      <button
        type="button"
        className={activeCount > 0 ? "filter-trigger has-active" : "filter-trigger"}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <i className="ti ti-filter" aria-hidden="true"></i> Filters
        {activeCount > 0 && <span className="filter-count">{activeCount}</span>}
      </button>

      {open && (
        <div className="filter-panel" role="dialog" aria-label="Search filters">
          <label className="filter-field">
            <span className="filter-label">Craft</span>
            <select
              className={cls(filters.craft !== undefined)}
              value={filters.craft ?? ""}
              onChange={(e) => set("craft", e.target.value || undefined)}
            >
              <option value="">All crafts</option>
              {crafts.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>

          <label className="filter-field">
            <span className="filter-label">Difficulty</span>
            <select
              className={cls(filters.difficulty !== undefined)}
              value={filters.difficulty ?? ""}
              onChange={(e) =>
                set("difficulty", (e.target.value || undefined) as SearchFilters["difficulty"])
              }
            >
              <option value="">Any difficulty</option>
              <option value="beginner">Beginner</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
            </select>
          </label>

          <label className="filter-field">
            <span className="filter-label">Price</span>
            <select
              className={cls(filters.free !== undefined)}
              value={filters.free === undefined ? "" : String(filters.free)}
              onChange={(e) =>
                set("free", e.target.value === "" ? undefined : e.target.value === "true")
              }
            >
              <option value="">Free & paid</option>
              <option value="true">Free only</option>
              <option value="false">Paid only</option>
            </select>
          </label>

          <label className="filter-field">
            <span className="filter-label">Category</span>
            <select
              className={cls(filters.category !== undefined)}
              value={filters.category ?? ""}
              onChange={(e) => set("category", e.target.value || undefined)}
            >
              <option value="">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>

          <div className="filter-panel-footer">
            {activeCount > 0 ? (
              <button type="button" className="filter-clear" onClick={() => onChange({})}>
                Clear all
              </button>
            ) : (
              <span></span>
            )}
            <button type="button" className="filter-done" onClick={() => setOpen(false)}>
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
