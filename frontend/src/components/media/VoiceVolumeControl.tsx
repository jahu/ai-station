import "./VoiceVolumeControl.css";

export default function VoiceVolumeControl({
  value,
  onChange,
}: {
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="voice-volume-control">
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        <strong>Even voice volume</strong>
        <small>
          Balance loud and quiet speech while keeping the words, pace and
          pauses.
        </small>
      </span>
    </label>
  );
}
