export type TimingPolicy = "preserve" | "fit";

export default function StudioTimingChoice({
  value,
  onChange,
}: {
  value?: TimingPolicy;
  onChange: (value: TimingPolicy) => void;
}) {
  return (
    <label>
      Timing
      <select
        aria-label="Narration timing"
        value={value ?? "preserve"}
        onChange={(event) => onChange(event.target.value as TimingPolicy)}
      >
        <option value="preserve">Keep planned shot lengths</option>
        <option value="fit">Fit the planned total length</option>
      </select>
      <small>
        {value === "fit"
          ? "Shorten flexible image holds when narration needs more room. Complete speech and planned video windows are kept; the film grows if they cannot fit."
          : "Keep each shot's planned hold, extending it when needed for complete narration."}
      </small>
    </label>
  );
}
