import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

/*
 * Restyled onto the design tokens in place, rather than replaced: keeping the
 * variant API means later phases change markup, not call signatures.
 *
 * The `default` variant is set in the *display* face. That is not decoration -
 * a primary button in Caprasimo is the single most characteristic detail of
 * this design, and it is what stops the redesign reading as a recolour.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          // Caprasimo ships one weight; `font-normal` overrides the base
          // `font-medium` so the browser does not synthesise a bold.
          "font-heading font-normal bg-acc text-onacc hover:bg-acc-h",
        destructive:
          "bg-danger text-onacc hover:opacity-90",
        outline:
          "border border-divider bg-transparent text-text hover:bg-surface",
        secondary:
          "bg-surface2 text-text hover:bg-surface",
        ghost:
          "bg-transparent text-text hover:bg-surface",
        link: "text-acc underline-offset-4 hover:underline hover:text-acc-h",
      },
      size: {
        default: "h-9 px-5 py-2",
        xs: "h-7 px-3 text-xs",
        sm: "h-8 px-4",
        // The 13px chrome buttons the mockup uses for Maintenance, Refresh,
        // Transcript and the rest of the secondary controls.
        "pill-sm": "h-8 px-3.5 text-[13px]",
        lg: "h-10 px-8",
        icon: "size-9 p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)
function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
