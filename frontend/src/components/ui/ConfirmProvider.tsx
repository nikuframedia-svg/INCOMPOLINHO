import { useCallback, useMemo, useRef, useState } from "react";
import { T } from "../../theme/tokens";
import {
  ConfirmContext,
  type ConfirmOptions,
  type ConfirmVariant,
  type PromptOptions,
} from "./confirmContext";

type PendingConfirm = {
  type: "confirm";
  options: ConfirmOptions;
  resolve: (value: boolean) => void;
};

type PendingPrompt = {
  type: "prompt";
  options: PromptOptions;
  resolve: (value: string | null) => void;
};

type PendingDialog = PendingConfirm | PendingPrompt;

const buttonStyle = (variant: ConfirmVariant, primary = false): React.CSSProperties => ({
  background: primary ? (variant === "danger" ? T.red : T.blue) : T.elevated,
  border: primary ? "none" : `1px solid ${T.border}`,
  borderRadius: 8,
  color: primary ? "#fff" : T.secondary,
  cursor: "pointer",
  fontFamily: "inherit",
  fontSize: 12,
  fontWeight: primary ? 700 : 500,
  padding: "8px 14px",
});

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [pending, setPending] = useState<PendingDialog | null>(null);
  const [inputValue, setInputValue] = useState("");
  const pendingRef = useRef<PendingDialog | null>(null);

  const clear = useCallback(() => {
    pendingRef.current = null;
    setPending(null);
    setInputValue("");
  }, []);

  const confirm = useCallback((options: ConfirmOptions) => new Promise<boolean>((resolve) => {
    const dialog: PendingConfirm = { type: "confirm", options, resolve };
    pendingRef.current = dialog;
    setPending(dialog);
  }), []);

  const prompt = useCallback((options: PromptOptions) => new Promise<string | null>((resolve) => {
    const dialog: PendingPrompt = { type: "prompt", options, resolve };
    pendingRef.current = dialog;
    setInputValue(options.defaultValue ?? "");
    setPending(dialog);
  }), []);

  const cancel = useCallback(() => {
    const dialog = pendingRef.current;
    if (!dialog) return;
    if (dialog.type === "confirm") dialog.resolve(false);
    else dialog.resolve(null);
    clear();
  }, [clear]);

  const accept = useCallback(() => {
    const dialog = pendingRef.current;
    if (!dialog) return;
    if (dialog.type === "prompt") {
      const value = inputValue.trim();
      if (dialog.options.required !== false && !value) return;
      dialog.resolve(value);
    } else {
      dialog.resolve(true);
    }
    clear();
  }, [clear, inputValue]);

  const value = useMemo(() => ({ confirm, prompt }), [confirm, prompt]);
  const variant = pending?.options.variant ?? "default";
  const confirmLabel = pending?.options.confirmLabel ?? "Confirmar";
  const cancelLabel = pending?.options.cancelLabel ?? "Cancelar";
  const promptDisabled = pending?.type === "prompt" && pending.options.required !== false && !inputValue.trim();

  return (
    <ConfirmContext.Provider value={value}>
      {children}
      {pending && (
        <div
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) cancel();
          }}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 5000,
            background: "rgba(18, 16, 13, 0.38)",
            backdropFilter: "blur(12px)",
            WebkitBackdropFilter: "blur(12px)",
            display: "grid",
            placeItems: "center",
            padding: 20,
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-dialog-title"
            style={{
              width: "min(460px, calc(100vw - 32px))",
              background: T.card,
              border: `1px solid ${T.border}`,
              borderRadius: 14,
              boxShadow: "0 24px 80px rgba(0,0,0,0.18)",
              padding: 22,
            }}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div id="confirm-dialog-title" style={{ color: T.primary, fontSize: 16, fontWeight: 800 }}>
              {pending.options.title}
            </div>
            <div style={{ color: T.secondary, fontSize: 13, lineHeight: 1.5, marginTop: 10, whiteSpace: "pre-line" }}>
              {pending.options.message}
            </div>
            {pending.type === "prompt" && (
              <label style={{ display: "grid", gap: 6, marginTop: 16 }}>
                <span style={{ color: T.tertiary, fontSize: 11 }}>{pending.options.inputLabel ?? "Motivo"}</span>
                <textarea
                  autoFocus
                  value={inputValue}
                  onChange={(event) => setInputValue(event.target.value)}
                  placeholder={pending.options.placeholder}
                  rows={3}
                  style={{
                    background: T.elevated,
                    border: `1px solid ${T.border}`,
                    borderRadius: 8,
                    color: T.primary,
                    fontFamily: "inherit",
                    fontSize: 12,
                    outline: "none",
                    padding: "8px 10px",
                    resize: "vertical",
                  }}
                />
              </label>
            )}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 20 }}>
              <button type="button" onClick={cancel} style={buttonStyle(variant)}>
                {cancelLabel}
              </button>
              <button
                type="button"
                disabled={promptDisabled}
                onClick={accept}
                style={{ ...buttonStyle(variant, true), opacity: promptDisabled ? 0.45 : 1, cursor: promptDisabled ? "default" : "pointer" }}
              >
                {confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
