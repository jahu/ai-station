import "./SpeechDeliveryControls.css";

import { type SpeechDelivery } from "./speech-delivery";

export default function SpeechDeliveryControls({
  enabled,
  supported,
  disabled,
  value,
  onEnable,
  onChange,
}: {
  enabled: boolean;
  supported: boolean;
  disabled: boolean;
  value: SpeechDelivery;
  onEnable: (enabled: boolean) => void;
  onChange: (value: SpeechDelivery) => void;
}) {
  if (!supported && !enabled) return null;
  return (
    <div className="speech-delivery">
      <label className="speech-delivery-toggle">
        <input
          type="checkbox"
          checked={enabled}
          disabled={disabled || (!supported && !enabled)}
          onChange={(event) => onEnable(event.target.checked)}
        />
        <span>
          <strong>Shape the delivery</strong>
          <small>Adjust expression while keeping your words and voice.</small>
        </span>
      </label>
      {enabled && (
        <div className="speech-delivery-settings">
          {!supported && (
            <p role="alert">
              Delivery controls are unavailable. Turn them off to use the
              standard voice.
            </p>
          )}
          <label>
            <span>
              Expression <output>{value.exaggeration.toFixed(2)}</output>
            </span>
            <input
              aria-label="Expression"
              type="range"
              min={0}
              max={1.5}
              step={0.05}
              value={value.exaggeration}
              disabled={disabled || !supported}
              onChange={(event) =>
                onChange({ ...value, exaggeration: Number(event.target.value) })
              }
            />
            <span className="speech-delivery-scale">
              <small>Restrained</small>
              <small>More expressive</small>
            </span>
          </label>
          <p className="muted">
            Use a clean reference with the delivery you want. Listen to a short
            passage before creating a longer recording.
          </p>
          <details>
            <summary>Fine-tune the voice</summary>
            <label>
              <span>
                Voice guidance <output>{value.cfg_weight.toFixed(2)}</output>
              </span>
              <input
                aria-label="Voice guidance"
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={value.cfg_weight}
                disabled={disabled || !supported}
                onChange={(event) =>
                  onChange({ ...value, cfg_weight: Number(event.target.value) })
                }
              />
              <small className="muted">
                Adjusts conditioning strength; this can also change speaking
                pace.
              </small>
            </label>
            <label>
              <span>
                Variation <output>{value.temperature.toFixed(2)}</output>
              </span>
              <input
                aria-label="Voice variation"
                type="range"
                min={0.05}
                max={1.2}
                step={0.05}
                value={value.temperature}
                disabled={disabled || !supported}
                onChange={(event) =>
                  onChange({
                    ...value,
                    temperature: Number(event.target.value),
                  })
                }
              />
              <small className="muted">
                Lower values are more consistent; higher values allow more
                variation.
              </small>
            </label>
          </details>
        </div>
      )}
    </div>
  );
}
