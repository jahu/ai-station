import DashboardActivity from "./DashboardActivity";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  Cpu,
  HardDrive,
  Layers,
  MemoryStick,
  Microchip,
  Thermometer,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type Sample, useHardware, useStatus } from "../api";
import {
  Empty,
  ErrorNotice,
  Loading,
  Meter,
  PageTitle,
} from "../components/common";
import { Button } from "../components/ui/button";
import { number } from "../lib/utils";

export default function Dashboard() {
  const hardware = useHardware();
  const status = useStatus();
  const history = useQuery({
    queryKey: ["history"],
    queryFn: () => api<Sample[]>("/system/history"),
    refetchInterval: 15000,
  });
  const data = hardware.data;
  const chart = (history.data ?? [])
    .filter((s) => s.payload.cpu)
    .map((s) => ({
      time: new Date(s.sampled_at).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      }),
      cpu: s.payload.cpu?.utilization,
      gpu: s.payload.gpus?.[0]?.utilization,
    }));
  const counts = status.data?.counts ?? {};
  const active = [
    "claimed",
    "preparing",
    "running",
    "cancel_requested",
    "waiting_for_approval",
  ].reduce((n, key) => n + (counts[key] ?? 0), 0);
  return (
    <>
      <PageTitle
        eyebrow="WORKSTATION / OVERVIEW"
        title="Your workspace, in focus."
        action={
          <Button variant="secondary" asChild>
            <Link to="/system">
              <Activity size={15} />
              System details
              <ArrowUpRight size={14} />
            </Link>
          </Button>
        }
      >
        Attention first: inspect, stop or acknowledge work, then local
        resources.
      </PageTitle>
      <nav className="dashboard-actions" aria-label="Quick actions">
        <Button asChild>
          <Link to="/chat">Chat</Link>
        </Button>
        <Button variant="secondary" asChild>
          <Link to="/images">Generate image</Link>
        </Button>
        <Button variant="secondary" asChild>
          <Link to="/agents">Create agent</Link>
        </Button>
        <Button variant="secondary" asChild>
          <Link to="/projects">Open project</Link>
        </Button>
      </nav>
      <ErrorNotice error={hardware.error ?? status.error} />
      {hardware.isPending && <Loading />}
      <DashboardActivity />
      <section className="dashboard-compute" aria-labelledby="compute-heading">
        <div className="section-label">
          <h2 id="compute-heading">Compute</h2>
          <span className="muted">
            Host telemetry · refreshes every 5 seconds
          </span>
        </div>
      <div className="gpu-grid">
        {data?.gpus.map((gpu) => (
          <section
            className="panel gpu-card"
            key={gpu.uuid}
            aria-labelledby={`gpu-${gpu.index}-heading`}
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
        {data && !data.gpus.length && (
          <section className="panel" aria-label="GPU detection">
            <Empty title="No GPUs detected">
              CPU monitoring is available. Check Diagnostics for NVIDIA
              detection details.
            </Empty>
          </section>
        )}
      </div>
      <div className="metrics-grid">
        <section className="panel metric" aria-label="CPU utilization">
          <Cpu size={18} />
          <span>CPU utilization</span>
          <strong>{number(data?.cpu.utilization, "%")}</strong>
          <Meter
            value={data?.cpu.utilization ?? null}
            label="CPU utilization"
          />
        </section>
        <section className="panel metric" aria-label="System memory">
          <MemoryStick size={18} />
          <span>System memory</span>
          <strong>
            {data ? `${(data.memory.used_mib / 1024).toFixed(1)} GB` : "—"}
          </strong>
          <small>
            of {data ? (data.memory.total_mib / 1024).toFixed(1) : "—"} GB
          </small>
          <Meter
            value={data?.memory.used_mib ?? null}
            total={data?.memory.total_mib}
            label="System memory"
          />
        </section>
        <section className="panel metric" aria-label="Storage available">
          <HardDrive size={18} />
          <span>Storage available</span>
          <strong>
            {data ? `${(data.disk.free_bytes / 1024 ** 3).toFixed(0)} GB` : "—"}
          </strong>
          <small>application data volume</small>
          <Meter
            value={data?.disk.used_bytes ?? null}
            total={data?.disk.total_bytes}
            label="Storage used"
          />
        </section>
        <section className="panel metric" aria-label="Runs in progress">
          <Layers size={18} />
          <span>Runs in progress</span>
          <strong>
            {status.data ? active : "—"} <em>active</em>
          </strong>
          <small>{counts.queued ?? 0} waiting in queue</small>
          <Link to="/runs" className="text-link">
            Inspect runs <ArrowUpRight size={14} />
          </Link>
        </section>
        </div>
      </section>
      <div className="dashboard-bottom">
        <section className="panel" aria-labelledby="resource-activity-heading">
          <div className="panel-heading">
            <h2 id="resource-activity-heading">Resource activity</h2>
            <span className="muted">Recent samples</span>
          </div>
          <ErrorNotice error={history.error} />
          {chart.length > 1 ? (
            <div
              className="chart"
              role="img"
              aria-label={`Resource activity. Latest CPU ${
                chart.at(-1)?.cpu == null
                  ? "unavailable"
                  : `${Math.round(Number(chart.at(-1)?.cpu))} percent`
              }. First GPU ${
                chart.at(-1)?.gpu == null
                  ? "unavailable"
                  : `${Math.round(Number(chart.at(-1)?.gpu))} percent`
              }.`}
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={chart}>
                  <defs>
                    <linearGradient id="cpu-fill" x1="0" y1="0" x2="0" y2="1">
                      <stop
                        offset="0%"
                        stopColor="#b9f48a"
                        stopOpacity={0.22}
                      />
                      <stop offset="100%" stopColor="#b9f48a" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#292c2f" vertical={false} />
                  <XAxis
                    dataKey="time"
                    tick={{ fill: "#838a91", fontSize: 11 }}
                    minTickGap={70}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    domain={[0, 100]}
                    tick={{ fill: "#838a91", fontSize: 11 }}
                    width={32}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#1b1d20",
                      border: "1px solid #373a3d",
                      borderRadius: 8,
                    }}
                  />
                  <Area
                    type="monotone"
                    name="CPU %"
                    dataKey="cpu"
                    stroke="#b9f48a"
                    fill="url(#cpu-fill)"
                    connectNulls={false}
                  />
                  <Area
                    type="monotone"
                    name="First GPU %"
                    dataKey="gpu"
                    stroke="#9d9af5"
                    fill="transparent"
                    connectNulls={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Empty title="Building your activity history">
              The scheduler records real hardware samples every 15 seconds.
            </Empty>
          )}
          <div className="chart-legend">
            <span>
              <i /> CPU
            </span>
            <span>
              <i className="purple" /> First detected GPU
            </span>
          </div>
        </section>
      </div>
      <div className="footnote">
        <span className="status-dot" /> Local-first by design. External services
        remain under your control.
      </div>
    </>
  );
}
