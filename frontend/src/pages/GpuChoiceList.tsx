import { useId, type KeyboardEvent } from "react";
import { useListKeyboard } from "./useListKeyboard";

export type GpuChoice = {
  index: number;
  name?: string;
  uuid?: string;
};

export function GpuChoiceList({
  gpus,
  selected,
  onChange,
  disabled,
}: {
  gpus: GpuChoice[];
  selected: number[];
  onChange: (gpus: number[]) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    gpus,
    (gpu) => String(gpu.index),
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented || disabled) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    const gpu = gpus[index];
    if (!gpu) return;
    event.preventDefault();
    const checked = selected.includes(Number(gpu.index));
    onChange(
      checked
        ? selected.filter((item) => item !== Number(gpu.index))
        : [...selected, Number(gpu.index)],
    );
  };
  if (!gpus.length) return null;
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Arrow keys choose a GPU while the list is focused. Space or Enter
        selects it. An empty selection uses the CPU. There is no inspectable
        allocation Run.
      </p>
      <div
        ref={listRef}
        className="gpu-choice-list"
        aria-labelledby={labelId}
        onKeyDown={handleKey}
      >
        {gpus.map((gpu, i) => {
          const current = i === index;
          const checked = selected.includes(Number(gpu.index));
          const shortId = (gpu.uuid ?? String(gpu.index)).slice(0, 8);
          return (
            <div
              key={gpu.index}
              aria-label={`Allocate GPU ${gpu.index} ${shortId}`}
              {...itemProps(i, String(gpu.index))}
            >
              <label className="project-checkbox">
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={disabled}
                  tabIndex={current ? 0 : -1}
                  onChange={(event) =>
                    onChange(
                      event.target.checked
                        ? [...selected, Number(gpu.index)]
                        : selected.filter((item) => item !== Number(gpu.index)),
                    )
                  }
                />
                GPU {gpu.index}
                {gpu.name ? ` · ${gpu.name}` : ""}
              </label>
            </div>
          );
        })}
      </div>
    </>
  );
}
