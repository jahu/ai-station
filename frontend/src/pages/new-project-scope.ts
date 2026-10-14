export type NewProjectScope = {
  name: string;
  executor: "local" | "cursor" | "codex";
  external_ai: boolean;
  model: string;
  max_repair_attempts: number;
};

export const newProjectScope: NewProjectScope = {
  name: "",
  executor: "local",
  external_ai: false,
  model: "auto",
  max_repair_attempts: 0,
};
