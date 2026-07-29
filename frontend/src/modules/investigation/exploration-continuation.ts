import type { Exploration } from "@/modules/investigation/types";

export function shouldContinueExploration(exploration: Exploration): boolean {
  if (exploration.id.startsWith("exploration-")) return false;
  return exploration.messages.length > 0;
}
