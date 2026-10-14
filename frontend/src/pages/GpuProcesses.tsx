import { useQuery } from "@tanstack/react-query";
import { api, type GPU } from "../api";
import { Badge, ErrorNotice, Loading } from "../components/common";
import { number, time } from "../lib/utils";

export type GpuProcessObservation = {
  status: "available" | "partial" | "unavailable";
  sampled_at: string | null;
  truncated: boolean;
  processes: {
    gpu_uuid: string;
    pid: number;
    name: string;
    memory_used_mib: number | null;
  }[];
};

export default function GpuProcesses({ gpus }: { gpus: GPU[] }) {
  const observation = useQuery({
    queryKey: ["gpu-processes"],
    queryFn: () => api<GpuProcessObservation>("/system/gpu-processes"),
    refetchInterval: 5000,
  });
  const data = observation.data;
  return (
    <section className="panel content-panel" aria-label="GPU compute processes">
      <div className="row spread">
        <h2>GPU compute processes</h2>
        {data && (
          <Badge status={observation.error ? "unavailable" : data.status} />
        )}
      </div>
      <p className="muted">
        Which programs have a compute context on your GPUs. Observed{" "}
        {time(data?.sampled_at ?? null)}.
      </p>
      <ErrorNotice error={observation.error} />
      {observation.isPending ? (
        <Loading />
      ) : (
        !observation.error &&
        data && (
          <>
            {data.status === "unavailable" ? (
              <p>Compute-process reporting is unavailable on this host.</p>
            ) : (
              <>
                {data.processes.length ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>GPU</th>
                          <th>Program</th>
                          <th>PID</th>
                          <th>VRAM</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.processes.map((row) => {
                          const gpu = gpus.find((g) => g.uuid === row.gpu_uuid);
                          return (
                            <tr key={`${row.gpu_uuid}:${row.pid}`}>
                              <td>
                                {gpu ? `GPU ${gpu.index}` : row.gpu_uuid}
                                <small className="muted">{gpu?.name}</small>
                              </td>
                              <td>{row.name}</td>
                              <td>{row.pid}</td>
                              <td>{number(row.memory_used_mib, " MiB")}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p>
                    {data.status === "available"
                      ? "No compute processes were reported."
                      : "No valid process records were returned."}
                  </p>
                )}
                {(data.status === "partial" || data.truncated) && (
                  <p className="notice">
                    This observation is incomplete; some processes may not be
                    shown.
                  </p>
                )}
              </>
            )}
          </>
        )
      )}
      <p className="muted">
        Graphics-only programs and other GPU memory use may not appear here.
        This list does not grant control over any process.
      </p>
    </section>
  );
}
