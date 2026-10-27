import { useId } from "react";
import { Microchip, Thermometer } from "lucide-react";
import type { GPU } from "../api";
import { Empty, Meter } from "../components/common";
import { number } from "../lib/utils";
import { useListKeyboard } from "./useListKeyboard";

export default function GpuCards({ gpus }: { gpus: GPU[] }) {
  const labelId = useId();
  const { listRef, onKeyDown, itemProps } = useListKeyboard(
    gpus,
    (gpu) => gpu.uuid,
  );
  if (!gpus.length) {
    return (
      <div className="gpu-grid">
        <section className="panel" aria-label="GPU detection">
          <Empty title="No GPUs detected">
            CPU monitoring is available. Check Diagnostics for NVIDIA detection
            details.
          </Empty>
        </section>
      </div>
    );
  }
  return (
    <>
      <p id={labelId} className="dashboard-note">
        Use arrow keys to move between detected GPUs.
      </p>
      <div
        ref={listRef}
        className="gpu-grid"
        aria-labelledby={labelId}
        onKeyDown={onKeyDown}
      >
        {gpus.map((gpu, i) => (
          <section
            className="panel gpu-card"
            key={gpu.uuid}
            aria-label={`GPU ${gpu.index} ${gpu.uuid.slice(0, 8)}`}
            {...itemProps(i, gpu.uuid)}
          >
            <div className="row spread">
              <span className="chip">
                <Microchip size={14} /> GPU {gpu.index}
              </span>
              <span className="eyebrow">NVIDIA</span>
            </div>
            <h2 id={`gpu-${gpu.index}-heading`}>
              {gpu.name.replace("NVIDIA ", "")}
            </h2>
            <p className="muted">
              {gpu.memory_total_mib == null
                ? "VRAM unavailable"
                : `${(gpu.memory_total_mib / 1024).toFixed(0)} GB dedicated memory`}
            </p>
            <div className="gpu-readout">
              <strong>{number(gpu.utilization, "%")}</strong>
              <span className="muted">utilization</span>
              <span className="temperature">
                <Thermometer size={15} />
                {number(gpu.temperature_c, "°C")}
              </span>
            </div>
            <Meter
              value={gpu.utilization}
              label={`${gpu.name.replace("NVIDIA ", "")} utilization`}
            />
            <div className="gpu-bottom">
              <span>
                VRAM <b>{number(gpu.memory_used_mib, " MiB")}</b>
              </span>
              <span>
                Power <b>{number(gpu.power_watts, " W")}</b>
              </span>
              <span>
                Fan <b>{number(gpu.fan_percent, "%")}</b>
              </span>
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
