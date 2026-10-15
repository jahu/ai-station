export type NewProjectScope = {
  name: string;
  auto_install_dependencies?: boolean;
  auto_validate?: boolean;
  executor: "local" | "cursor" | "codex";
  external_ai: boolean;
  model: string;
  max_repair_attempts: number;
};

export const newProjectScope: NewProjectScope = {
  name: "",
  auto_install_dependencies: true,
  auto_validate: true,
  executor: "local",
  external_ai: false,
  model: "auto",
  max_repair_attempts: 0,
};
