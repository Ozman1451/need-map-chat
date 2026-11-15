import { cn } from "@/lib/utils";

export function Skeleton({ className, style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={cn("animate-pulse rounded-md bg-white/[0.06]", className)} style={style} />;
}

/** Placeholder chart card shown on the canvas while a tool is running. */
export function ChartSkeleton({ tall }: { tall?: boolean }) {
  return (
    <section data-testid="chart-skeleton" className="rounded-2xl border border-border bg-card/90 p-4">
      <Skeleton className="h-4 w-48" />
      <Skeleton className="mt-2 h-3 w-72 max-w-full" />
      <Skeleton className={cn("mt-4 w-full rounded-xl", tall ? "h-72" : "h-28")} />
    </section>
  );
}
