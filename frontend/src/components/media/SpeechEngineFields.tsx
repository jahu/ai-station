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
}: {
  engine: string;
  direction: string;
  pace: string;
  capabilities?: SpeechCapabilities;
  onEngine: (value: string) => void;
  onDirection: (value: string) => void;
  onPace: (value: string) => void;
}) {
  const fish = capabilities?.engines?.fish_s2_pro;
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
              : fish?.readiness === "checking"
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
          <p className="muted">
            Choose how it should sound. Your reference is transcribed locally
            when needed; your script stays unchanged.
          </p>
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
              {fish?.reason ??
                "This expressive model is not ready. Choose another model or check setup."}
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
