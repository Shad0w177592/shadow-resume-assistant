import type { ButtonHTMLAttributes, InputHTMLAttributes, PropsWithChildren, ReactNode } from "react";

export function Button({ className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={`button ${className}`.trim()} {...props} />;
}

export function TextInput({ label, error, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  const id = props.id ?? `field-${props.name ?? label}`;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined} {...props} />
      {error && <small id={`${id}-error`} role="alert">{error}</small>}
    </div>
  );
}

export function Card({ children, title }: PropsWithChildren<{ title?: string }>) {
  return <section className="card">{title && <h2>{title}</h2>}{children}</section>;
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <span className="square" aria-hidden="true" />
      <strong>{title}</strong>
      <p>{description}</p>
      {action}
    </div>
  );
}

export function Progress({ label, value }: { label: string; value: number }) {
  const safeValue = Math.max(0, Math.min(100, value));
  return (
    <div className="progress-wrap">
      <div className="progress-label"><span>{label}</span><span>{safeValue}%</span></div>
      <progress value={safeValue} max={100} aria-label={label} />
    </div>
  );
}

export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="stepper" aria-label="步骤">
      {steps.map((step, index) => (
        <li key={step} aria-current={index === current ? "step" : undefined} className={index <= current ? "active" : ""}>
          <span>{index + 1}</span>{step}
        </li>
      ))}
    </ol>
  );
}

export function Dialog({ open, title, children, onClose }: PropsWithChildren<{ open: boolean; title: string; onClose: () => void }>) {
  if (!open) return null;
  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title" onMouseDown={(event) => event.stopPropagation()}>
        <header><h2 id="dialog-title">{title}</h2><Button aria-label="关闭" onClick={onClose}>×</Button></header>
        {children}
      </section>
    </div>
  );
}
