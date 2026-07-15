export type CommandHistoryDirection = "previous" | "next";

export interface CommandHistoryNavigation {
  value: string;
  index: number | null;
  draft: string;
}

export function collectCommandHistory(
  messages: ReadonlyArray<{ role: string; content: string }>
): string[] {
  const commands: string[] = [];
  for (const message of messages) {
    if (message.role !== "user") continue;
    const command = message.content.trim();
    if (command && commands.at(-1) !== command) commands.push(command);
  }
  return commands;
}

export function navigateCommandHistory(
  history: readonly string[],
  currentValue: string,
  currentIndex: number | null,
  savedDraft: string,
  direction: CommandHistoryDirection
): CommandHistoryNavigation {
  if (!history.length) {
    return { value: currentValue, index: currentIndex, draft: savedDraft };
  }

  if (direction === "previous") {
    const index = currentIndex === null
      ? history.length - 1
      : Math.max(0, currentIndex - 1);
    return {
      value: history[index],
      index,
      draft: currentIndex === null ? currentValue : savedDraft
    };
  }

  if (currentIndex === null) {
    return { value: currentValue, index: null, draft: savedDraft };
  }
  if (currentIndex >= history.length - 1) {
    return { value: savedDraft, index: null, draft: savedDraft };
  }
  const index = currentIndex + 1;
  return { value: history[index], index, draft: savedDraft };
}
