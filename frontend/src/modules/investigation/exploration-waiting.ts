export function shouldShowExplorationWaiting(submitting: boolean, submittingExplorationId: string | null, selectedExplorationId: string) {
  return submitting && submittingExplorationId === selectedExplorationId;
}
