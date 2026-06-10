import type { ChangeScope } from "../types";

const FILTERS: Array<{ value: ChangeScope | "all"; label: string }> = [
  { value: "all", label: "All" },
  { value: "api", label: "API" },
  { value: "frontend", label: "Frontend" },
  { value: "database", label: "Database" },
  { value: "infra", label: "Infra" },
  { value: "mixed", label: "Mixed" },
];

type DiffTypeFilterProps = {
  active: ChangeScope | "all";
  onChange: (value: ChangeScope | "all") => void;
};

export function DiffTypeFilter({ active, onChange }: DiffTypeFilterProps) {
  return (
    <div className="filter-chips" role="tablist" aria-label="Filter runs by change type">
      {FILTERS.map((filter) => (
        <button
          className={`filter-chip${active === filter.value ? " filter-chip--active" : ""}`}
          key={filter.value}
          onClick={() => onChange(filter.value)}
          type="button"
        >
          {filter.label}
        </button>
      ))}
    </div>
  );
}
