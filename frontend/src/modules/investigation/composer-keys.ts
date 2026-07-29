export type ComposerKeyIntent = "submit" | "edit";

export type ComposerKeyEvent = {
  key: string;
  shiftKey?: boolean;
  ctrlKey?: boolean;
  altKey?: boolean;
  metaKey?: boolean;
  nativeEvent?: {
    isComposing?: boolean;
  };
};

export function getComposerKeyIntent(event: ComposerKeyEvent): ComposerKeyIntent {
  if (event.key !== "Enter") return "edit";
  if (event.nativeEvent?.isComposing) return "edit";
  if (event.shiftKey || event.ctrlKey || event.altKey || event.metaKey) return "edit";
  return "submit";
}
