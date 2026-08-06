export type SystemContextUpdate =
  | { baseInstructions: string }
  | { systemPrompt: string };

export class SystemContextSettingsError extends Error {
  constructor(public readonly code: string) {
    super(code);
  }
}

export function validateSystemContextUpdate(
  input: Record<string, unknown>,
): SystemContextUpdate {
  const hasBase = Object.prototype.hasOwnProperty.call(input, "baseInstructions");
  const hasSystem = Object.prototype.hasOwnProperty.call(input, "systemPrompt");
  if (hasBase === hasSystem) {
    throw new SystemContextSettingsError("context_update_invalid");
  }

  if (hasBase && typeof input.baseInstructions === "string") {
    const baseInstructions = input.baseInstructions.trim();
    if (baseInstructions) return { baseInstructions };
  }
  if (hasSystem && typeof input.systemPrompt === "string") {
    const systemPrompt = input.systemPrompt.trim();
    if (systemPrompt) return { systemPrompt };
  }
  throw new SystemContextSettingsError("context_update_invalid");
}
