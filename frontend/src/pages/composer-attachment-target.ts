import { createContext } from "react";

// Undefined preserves the inline layout outside a conversation composer.
export const ComposerAttachmentTarget = createContext<
  HTMLElement | null | undefined
>(undefined);
