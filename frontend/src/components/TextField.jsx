import React, { useId } from "react";

/**
 * TextField — подписанное поле ввода (↔ QLineEdit#SearchInput +
 * FieldCaption в styles.py). Не было в списке компонентов Этапа 3 —
 * добавлено здесь, в Этапе 4, потому что формы (Настройки, а затем
 * Таксация/Делянки) держатся на этом паттерне буквально везде;
 * дублировать разметку поля в каждой странице не имеет смысла.
 */
export default function TextField({
  label,
  hint,
  error,
  type = "text",
  suffix,
  className = "",
  inputClassName = "",
  ...rest
}) {
  const id = useId();
  return (
    <div className={className}>
      {label && (
        <label htmlFor={id} className="block text-xs font-semibold tracking-wide text-muted-2 uppercase mb-1.5">
          {label}
        </label>
      )}
      <div className="relative">
        <input
          id={id}
          type={type}
          className={[
            "w-full bg-surface-alt border rounded-md px-3.5 py-2.5 text-base text-ink placeholder:text-faint outline-none transition-colors",
            "focus:bg-surface focus:border-pine",
            error ? "border-error" : "border-transparent",
            suffix ? "pr-11" : "",
            inputClassName,
          ].join(" ")}
          {...rest}
        />
        {suffix && <div className="absolute right-1.5 top-1/2 -translate-y-1/2">{suffix}</div>}
      </div>
      {hint && !error && <p className="text-faint text-xs mt-1.5">{hint}</p>}
      {error && <p className="text-error text-xs mt-1.5">{error}</p>}
    </div>
  );
}
