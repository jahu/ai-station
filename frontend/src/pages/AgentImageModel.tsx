import type { ImageMediaRequest } from "./agent-media";
import { changeAgentImageModel } from "./agent-image-model";

export default function AgentImageModel({
  request,
  disabled,
  onChange,
}: {
  request: ImageMediaRequest;
  disabled: boolean;
  onChange: (request: ImageMediaRequest) => void;
}) {
  return (
    <label>
      Image model
      <select
        aria-label="Agent image model"
        value={request.backend ?? "qwen"}
        disabled={disabled}
        onChange={(event) =>
          onChange(
            changeAgentImageModel(
              request,
              event.target.value as "qwen" | "juggernaut",
            ),
          )
        }
      >
        <option value="qwen">Qwen</option>
        <option value="juggernaut">Juggernaut XL</option>
      </select>
    </label>
  );
}
