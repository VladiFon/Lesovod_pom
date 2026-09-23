import React, { useId } from "react";

/**
 * TextAreaField — многострочный вариант TextField (↔ QTextEdit с
 * setFixedHeight(56/80) в screens/plots/screen_core.py: причины рубки,
 * вредители, мероприятия, члены комиссии). Тот же визуальный язык
 * (surface-alt, фокус — рамка Pine), просто textarea вместо input.
 */
export default function TextAreaField({
  label,
  hint,
  error,
  rows = 3,
  className = "",
  textareaClassName = "",
  ...rest
}) {
  const id = useId();
  return (
    <div className={className}>
      {label && (
        <label htmlFor={id} className="block text-[11.5px] font-semibold text-muted mb-1">
          {label}
        </label>
      )}
      <textarea
        id={id}
        rows={rows}
        className={[
          "w-full bg-surface border rounded-[10px] px-2.5 py-2 text-[13.5px] text-ink placeholder:text-faint outline-none transition-colors resize-y",
          "focus:bg-surface focus:border-pine",
          error ? "border-error" : "border-border",
          textareaClassName,
        ].join(" ")}
        {...rest}
      />
      {hint && !error && <p className="text-faint text-xs mt-1.5">{hint}</p>}
      {error && <p className="text-error text-xs mt-1.5">{error}</p>}
    </div>
  );
}
