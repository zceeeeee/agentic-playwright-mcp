export type ApiConnectionTestStatus = "idle" | "testing" | "success" | "error";

export interface ApiConnectionTestState {
  status: ApiConnectionTestStatus;
  message: string;
  elapsedMs: number;
}

export type ApiConnectionTestAction =
  | { type: "edit" }
  | { type: "start" }
  | { type: "succeed"; message: string; elapsedMs: number }
  | { type: "fail"; message: string; elapsedMs: number };

export const initialApiConnectionTestState: ApiConnectionTestState = {
  status: "idle",
  message: "",
  elapsedMs: 0
};

export function apiConnectionTestReducer(
  state: ApiConnectionTestState,
  action: ApiConnectionTestAction
): ApiConnectionTestState {
  switch (action.type) {
    case "edit":
      return state.status === "testing" ? state : initialApiConnectionTestState;
    case "start":
      return { status: "testing", message: "", elapsedMs: 0 };
    case "succeed":
      return {
        status: "success",
        message: action.message,
        elapsedMs: action.elapsedMs
      };
    case "fail":
      return {
        status: "error",
        message: action.message,
        elapsedMs: action.elapsedMs
      };
  }
}
