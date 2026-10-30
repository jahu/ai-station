import { useEffect, useRef, useState, type InputHTMLAttributes } from "react";

/** Keep the typed decimal while the parent quantizes seconds to exact frames. */
export default function NumberInput(
  props: InputHTMLAttributes<HTMLInputElement>,
) {
  const focused = useRef(false);
  const [text, setText] = useState(String(props.value ?? ""));
  useEffect(() => {
    if (!focused.current) setText(String(props.value ?? ""));
  }, [props.value]);
  return (
    <input
      {...props}
      type="number"
      value={text}
      onFocus={(event) => {
        focused.current = true;
        props.onFocus?.(event);
      }}
      onChange={(event) => {
        setText(event.target.value);
        if (
          event.target.value !== "" &&
          Number.isFinite(Number(event.target.value))
        )
          props.onChange?.(event);
      }}
      onBlur={(event) => {
        focused.current = false;
        setText(String(props.value ?? ""));
        props.onBlur?.(event);
      }}
    />
  );
}
