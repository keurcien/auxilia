import { ShieldAlertIcon } from "lucide-react";
import type { RefusalInfo } from "@/lib/transcript";
import { cn } from "@/lib/utils";

/** Renders a model refusal as a system notice, so a declined turn is visible
 *  instead of an empty bubble. */
export const RefusalNotice = ({
  refusal,
  className,
}: {
  refusal: RefusalInfo;
  className?: string;
}) => (
  <div
    className={cn(
      "flex items-start gap-3 rounded-lg border border-border bg-muted/50 p-4",
      className,
    )}
  >
    <ShieldAlertIcon className="mt-0.5 size-5 shrink-0 text-meta dark:text-panel-dim" />
    <div className="min-w-0 flex-1 space-y-1">
      <p className="text-sm font-medium text-foreground">
        The model declined to respond
      </p>
      <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground">
        {refusal.explanation}
      </p>
    </div>
  </div>
);
