import React from "react";

/**
 * Button — три варианта 1:1 с кнопками десктопа (styles.py):
 *   primary   ↔ QPushButton#SearchButton (заливка Deep Pine)
 *   secondary ↔ базовый QPushButton (контур Deep Pine, белый фон)
 *   danger    ↔ QPushButton#DangerButton (контур Error)
 * plus "ghost" — для UploadButton-подобных второстепенных действий.
 */
const VARIANTS = {
  primary:
    "bg-pine text-white border border-pine hover:bg-pine-hover active:bg-pine-active disabled:bg-border disabled:text-muted-2 disabled:border-border",
  secondary:
    "bg-surface text-muted border border-border hover:border-pine hover:text-pine active:bg-mint-soft disabled:bg-hover disabled:text-disabled disabled:border-border",
  danger:
    "bg-transparent text-error border border-error hover:bg-error-soft disabled:border-border disabled:text-faint",
  ghost:
    "bg-surface text-pine border border-border hover:bg-hover disabled:border-border disabled:text-faint",
};

const SIZES = {
  sm: "h-7 px-2.5 text-xs",
  md: "h-8 px-3 text-[12.5px]",
  lg: "h-9 px-4 text-[13.5px]",
};

export default function Button({
  variant = "secondary",
  size = "md",
  icon = null,
  iconPosition = "left",
  loading = false,
  disabled = false,
  className = "",
  children,
  ...rest
}) {
  return (
    <button
      disabled={disabled || loading}
      className={[
        "inline-flex items-center justify-center gap-2 font-ui font-semibold rounded-[9px] whitespace-nowrap",
        "transition-colors duration-150 disabled:cursor-not-allowed",
        VARIANTS[variant],
        SIZES[size],
        className,
      ].join(" ")}
      {...rest}
    >
      {loading ? (
        <span
          className="h-3.5 w-3.5 rounded-full border-2 border-current border-t-transparent animate-spin"
          aria-hidden="true"
        />
      ) : (
        icon && iconPosition === "left" && <span className="shrink-0">{icon}</span>
      )}
      {children}
      {!loading && icon && iconPosition === "right" && <span className="shrink-0">{icon}</span>}
    </button>
  );
}
