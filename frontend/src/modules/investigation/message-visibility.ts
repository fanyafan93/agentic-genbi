import type { ExplorationMessage } from "./types";

export function isExplorationStarterMessage(message: ExplorationMessage) {
  return (
    message.role === "agent" &&
    message.title === "开始探索" &&
    message.body.includes("我会先搜索资源库里的已有报表、SQL、ETL 和字典")
  );
}

export function isRepeatedExplorationStarter(messages: ExplorationMessage[], index: number) {
  const message = messages[index];
  if (!isExplorationStarterMessage(message)) return false;
  const previousUserMessages = messages.slice(0, index).filter((item) => item.role === "user").length;
  return previousUserMessages > 1;
}

export function shouldShowExplorationMessage(message: ExplorationMessage) {
  return !isExplorationStarterMessage(message);
}
