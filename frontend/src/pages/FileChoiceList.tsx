import { useId, type KeyboardEvent } from "react";
import { parseFilePaths } from "./filePaths";
import { useListKeyboard } from "./useListKeyboard";

export function FileChoiceList({
  files,
  onChange,
  label,
  required,
}: {
  files: string;
  onChange: (files: string) => void;
  label: string;
  required?: boolean;
}) {
  const labelId = useId();
  const paths = parseFilePaths(files);
  const { listRef, index, onKeyDown, itemProps } = useListKeyboard(
    paths,
    (path) => path,
  );
  const handleKey = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown(event);
    if (event.defaultPrevented) return;
    if (event.key !== " " && event.key !== "Enter") return;
    const target = event.target as HTMLElement;
    if (target.closest("a, button, textarea, input, summary, select")) return;
    const path = paths[index];
    if (!path) return;
    event.preventDefault();
    onChange(paths.filter((item) => item !== path).join("\n"));
  };
  return (
    <div className="file-choice">
      <label>
        {label}
        <textarea
          aria-label={label}
          required={required}
          rows={3}
          value={files}
          placeholder="src/app.py&#10;README.md"
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
      <small>
        Relative paths, one per line. You can include new files. At most ten.
      </small>
      {paths.length > 0 && (
        <>
          <p id={labelId} className="dashboard-note">
            Arrow keys choose a file while the list is focused. Space or Enter
            removes the focused path. Enter does not start a coding Run. There
            is no inspectable file-selection Run.
          </p>
          <div
            ref={listRef}
            className="file-choice-list"
            aria-labelledby={labelId}
            onKeyDown={handleKey}
          >
            {paths.map((path, i) => {
              const current = i === index;
              return (
                <div
                  key={path}
                  aria-label={`Edit file ${path}`}
                  {...itemProps(i, path)}
                >
                  <label className="project-checkbox">
                    <input
                      type="checkbox"
                      checked
                      tabIndex={current ? 0 : -1}
                      onChange={() =>
                        onChange(
                          paths.filter((item) => item !== path).join("\n"),
                        )
                      }
                    />
                    {path}
                  </label>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
