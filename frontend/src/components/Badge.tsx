interface BadgeProps {
  variant: "beginner" | "intermediate" | "advanced" | "free" | "paid";
  children: string;
}

export function Badge({ variant, children }: BadgeProps) {
  return <span className={`badge badge-${variant}`}>{children}</span>;
}

/** Map Ravelry's 0-10 difficulty average to a display tier. */
export function difficultyVariant(
  difficulty: string | null | undefined
): { variant: "beginner" | "intermediate" | "advanced"; label: string } | null {
  if (!difficulty) return null;
  const value = parseFloat(difficulty);
  // 0 means "no ratings yet" in Ravelry data, not beginner
  if (Number.isNaN(value) || value <= 0) return null;
  if (value < 3.5) return { variant: "beginner", label: "Beginner" };
  if (value < 6.5) return { variant: "intermediate", label: "Intermediate" };
  return { variant: "advanced", label: "Advanced" };
}
