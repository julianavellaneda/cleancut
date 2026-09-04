import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

/*
 * The pill the redesign uses for status, label and severity. Tinted from the
 * ramps rather than filled with the accent itself: these sit inside dense rows
 * and a saturated block at that size reads as a button.
 */
const badgeVariants = cva(
  "inline-flex items-center justify-center rounded-full border border-transparent px-2.5 py-0.5 text-[11px] font-medium w-fit whitespace-nowrap shrink-0 [&>svg]:size-3 gap-1 transition-colors",
  {
    variants: {
      variant: {
        default: "bg-acc-200 text-acc-700",
        secondary:
          "bg-surface2 text-text",
        destructive:
          "bg-danger-100 text-danger-700",
        outline:
          "border-divider text-text bg-transparent",
        ghost: "text-muted",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
