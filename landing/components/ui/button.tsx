import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500/50 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "relative bg-gradient-to-b from-purple-500 to-purple-600 text-white shadow-[0_0_0_1px_rgba(168,85,247,0.4),0_8px_32px_-8px_rgba(168,85,247,0.6)] hover:shadow-[0_0_0_1px_rgba(168,85,247,0.6),0_12px_40px_-8px_rgba(168,85,247,0.8)] hover:-translate-y-0.5",
        ghost: "text-zinc-300 hover:text-white hover:bg-white/5",
        outline:
          "border border-white/10 bg-white/[0.02] text-zinc-200 hover:bg-white/[0.05] hover:border-white/20",
      },
      size: {
        default: "h-10 px-5 py-2",
        sm: "h-9 px-3.5",
        lg: "h-12 px-7 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
