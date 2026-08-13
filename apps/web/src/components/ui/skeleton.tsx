import { cn } from "@/lib/utils";

/** A loading placeholder — `aria-hidden` because its sibling loading state
 * (see `components/status.tsx`) is what screen readers are told about. */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}
