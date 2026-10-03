import { createContext, useContext } from "react";
import type { ReactNode } from "react";

export type ConfirmVariant = "default" | "danger";

export type ConfirmOptions = {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: ConfirmVariant;
};

export type PromptOptions = ConfirmOptions & {
  defaultValue?: string;
  inputLabel?: string;
  placeholder?: string;
  required?: boolean;
};

export type ConfirmContextValue = {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  prompt: (options: PromptOptions) => Promise<string | null>;
};

export const ConfirmContext = createContext<ConfirmContextValue | null>(null);

const unavailableContext: ConfirmContextValue = {
  confirm: async () => false,
  prompt: async () => null,
};

export function useConfirm() {
  return useContext(ConfirmContext) ?? unavailableContext;
}
