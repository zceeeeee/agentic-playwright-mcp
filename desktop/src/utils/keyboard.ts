export type EnterKeyAction = "submit" | "newline" | "none";

export function getEnterKeyAction(
  key: string,
  ctrlKey: boolean,
  isComposing = false
): EnterKeyAction {
  if (key !== "Enter" || isComposing) return "none";
  return ctrlKey ? "newline" : "submit";
}
