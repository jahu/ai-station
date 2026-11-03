import "./SpeechEngineFields.css";
import { speechDirections, type SpeechCapabilities } from "./speech-delivery";

export default function SpeechEngineFields({
  engine,
  direction,
  pace,
  capabilities,
  onEngine,
  onDirection,
  onPace,
  voiceSource,
  onVoiceSource,
}: {
  engine: string;
  direction: string;
  pace: string;
  capabilities?: SpeechCapabilities;
  onEngine: (value: string) => void;
  onDirection: (value: string) => void;
  onPace: (value: string) => void;
  voiceSource?: "reference" | "model";
  onVoiceSource?: (value: "reference" | "model") => void;
}) {
  const fish = capabilities?.engines?.fish_s2_pro;
  const checking = !capabilities || fish?.readiness === "checking";
  return (
    <div className="speech-engine-fields">
      <label>
        Speech model
        <select
          aria-label="Speech model"
          value={engine}
          onChange={(event) => onEngine(event.target.value)}
        >
          <option value="">Chatterbox · Polish voice</option>
          <option value="fish_s2_pro" disabled={!fish?.available}>
            Fish S2 Pro · Expressive
            {fish?.available
              ? ""
              : checking
                ? " · Checking…"
                : " · Not configured"}
          </option>
        </select>
      </label>
      {engine === "fish_s2_pro" && (
        <section className="speech-direction" aria-label="Expressive speech">
          <div className="speech-direction-heading">
            <strong>Direct the performance</strong>
            <span>LOCAL · 2 GPUs</span>
          </div>
          {onVoiceSource && (
            <label>
              Voice source
              <select
                aria-label="Voice source"
                value={voiceSource ?? "reference"}
                onChange={(event) =>
                  onVoiceSource(event.target.value as "reference" | "model")
                }
              >
                <option
                  value="model"
                  disabled={!fish?.voice_sources?.includes("model")}
                >
                  Generate a voice
                </option>
                <option value="reference">Use a recording</option>
              </select>
            </label>
          )}
          <p className="muted">
            {voiceSource === "model"
              ? "Fish creates the voice. Best for whispers and expressive delivery; it won't imitate a specific person. Your words stay unchanged."
              : "Your recording provides the voice and is transcribed locally. A neutral reference can soften emotional delivery. Your words stay unchanged."}
          </p>
          {voiceSource === "model" &&
            !fish?.voice_sources?.includes("model") && (
              <p className="notice" role="status">
                Update AI Station to generate voices without a recording, or
                choose Use a recording.
              </p>
            )}
          <div className="speech-direction-grid">
            <label>
              Voice direction
              <select
                aria-label="Voice direction"
                value={direction}
                onChange={(event) => onDirection(event.target.value)}
              >
                {speechDirections.map(([key, title]) => (
                  <option key={key} value={key}>
                    {title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Speaking pace
              <select
                aria-label="Speaking pace"
                value={pace}
                onChange={(event) => onPace(event.target.value)}
              >
                <option value="natural">Natural</option>
                <option value="slow">Slower</option>
                <option value="fast">Faster</option>
              </select>
            </label>
          </div>
          {!fish?.available && (
            <p role="status">
              {checking
                ? "Checking expressive speech on this workstation…"
                : (fish?.reason ??
                  "This expressive model is not ready. Choose another model or check setup.")}
            </p>
          )}
          <small className="muted">
            Built with Fish Audio · Noncommercial model. Commercial use requires
            a separate Fish Audio license.{" "}
            {fish?.license_url && (
              <a href={fish.license_url} target="_blank" rel="noreferrer">
                Model license
              </a>
            )}
          </small>
        </section>
      )}
    </div>
  );
}
