import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function ScheduleTimezoneSelect({
  value,
  onChange,
  disabled,
  tabIndex,
  suffix = "",
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  tabIndex?: number;
  suffix?: string;
}) {
  const zones = useQuery({
    queryKey: ["schedule-timezones"],
    queryFn: () => api<string[]>("/agents/timezones"),
    staleTime: Infinity,
  });
  const local = browserTimezone();
  const choices = [
    ...new Set([
      value,
      local,
      "UTC",
      ...(Array.isArray(zones.data)
        ? zones.data.filter((zone) => typeof zone === "string")
        : []),
    ]),
  ];
  return (
    <label>
      Time zone
      <select
        aria-label={`Schedule timezone${suffix}`}
        value={value}
        disabled={disabled}
        tabIndex={tabIndex}
        onChange={(event) => onChange(event.target.value)}
      >
        {choices.map((zone) => (
          <option value={zone} key={zone}>
            {zone === local ? `${zone} · your time` : zone}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function AgentCronFields({
  cron,
  timezone,
  onCron,
  onTimezone,
  disabled,
  tabIndex,
  suffix = "",
}: {
  cron: string;
  timezone: string;
  onCron: (value: string) => void;
  onTimezone: (value: string) => void;
  disabled?: boolean;
  tabIndex?: number;
  suffix?: string;
}) {
  const daily = /^([0-5]?\d) ([01]?\d|2[0-3]) \* \* \*$/.exec(cron);
  const [pattern, setPattern] = useState(daily || !cron ? "daily" : "custom");
  return (
    <>
      <label>
        Calendar schedule
        <select
          aria-label={`Schedule pattern${suffix}`}
          value={pattern}
          disabled={disabled}
          tabIndex={tabIndex}
          onChange={(event) => {
            setPattern(event.target.value);
            if (event.target.value === "daily" && !daily) onCron("0 9 * * *");
          }}
        >
          <option value="daily">Every day</option>
          <option value="custom">Custom cron</option>
        </select>
      </label>
      {pattern === "daily" ? (
        <label>
          Daily at
          <input
            type="time"
            required
            aria-label={`Daily time${suffix}`}
            value={
              daily
                ? `${daily[2].padStart(2, "0")}:${daily[1].padStart(2, "0")}`
                : ""
            }
            disabled={disabled}
            tabIndex={tabIndex}
            onChange={(event) => {
              const [hour, minute] = event.target.value.split(":");
              onCron(
                hour && minute ? `${Number(minute)} ${Number(hour)} * * *` : "",
              );
            }}
          />
        </label>
      ) : (
        <label>
          Cron expression
          <input
            required
            aria-label={`Cron expression${suffix}`}
            value={cron}
            placeholder="0 9 * * 1-5"
            disabled={disabled}
            tabIndex={tabIndex}
            onChange={(event) => onCron(event.target.value)}
          />
        </label>
      )}
      <ScheduleTimezoneSelect
        value={timezone}
        onChange={onTimezone}
        disabled={disabled}
        tabIndex={tabIndex}
        suffix={suffix}
      />
      <p className="muted">
        Uses {timezone}. Skipped clock times do not run; repeated clock times
        run once.
      </p>
    </>
  );
}
