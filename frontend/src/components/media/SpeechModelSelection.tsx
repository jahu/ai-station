import "./SpeechEngineFields.css";
import type { Run } from "../../api";
import { Link } from "react-router-dom";
import { speechDirections } from "./speech-delivery";

export default function SpeechModelSelection({
  run,
  preparation,
}: {
  run?: Run;
  preparation?: Run;
}) {
  if (run?.parameters?.backend !== "fish_s2_pro") return null;
  const direction =
    speechDirections.find(([key]) => key === run.parameters.direction)?.[1] ??
    "Natural";
  const pace =
    run.parameters.pace === "slow"
      ? "Slower"
      : run.parameters.pace === "fast"
        ? "Faster"
        : "Natural pace";
  return (
    <div className="speech-selection" aria-label="Speech model selection">
      <strong>Fish S2 Pro · {direction}</strong>
      <small>{pace} · Local · Built with Fish Audio</small>
      {preparation &&
        preparation.id === run.parameters.reference_transcription_run_id && (
          <small>
            {["queued", "claimed", "preparing", "running"].includes(
              preparation.status,
            )
              ? "Preparing your voice reference locally… "
              : preparation.status === "succeeded"
                ? "Voice reference prepared locally. "
                : "Voice reference preparation stopped. "}
            <Link to={`/runs/${preparation.id}`}>Reference details</Link>
          </small>
        )}
      {!preparation &&
        (
          run.parameters.reference_text_provenance as
            { kind?: string } | undefined
        )?.kind === "cached_asr" && (
          <small>
            Reference transcript reused.{" "}
            <Link to={`/runs/${run.parameters.reference_transcription_run_id}`}>
              Reference details
            </Link>
          </small>
        )}
    </div>
  );
}
