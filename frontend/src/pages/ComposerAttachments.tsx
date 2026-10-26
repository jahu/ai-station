import { useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ComposerAttachmentTarget } from "./composer-attachment-target";

export default function ComposerAttachments({
  children,
}: {
  children: ReactNode;
}) {
  const target = useContext(ComposerAttachmentTarget);
  if (target === undefined) return <>{children}</>;
  return target ? createPortal(children, target) : null;
}
