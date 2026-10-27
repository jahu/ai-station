import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Run } from "../../api";
import { randomId } from "../../lib/random-id";
import { Button } from "../ui/button";
import { ErrorNotice } from "../common";
import { useMediaRun } from "./media-run";
import type { GenerationPreferences } from "../../pages/GenerationSettings";

export type TranslationOptions = {
  mode: "inherit" | "on" | "off";
  review: boolean;
  protected_terms: string[];
};
export type TranslationRecovery = "reuse" | "retry" | "original";

export function translationRequest(value: TranslationOptions) {
  return value.mode !== "inherit" ||
    value.review ||
    value.protected_terms.length
    ? { translation: value }
    : {};
}
export type TranslationReceipt = {
  status: string;
  preparation_run_id?: string;
  review_run_id?: string;
  original: Record<string, string>;
  effective?: Record<string, string>;
  policy: { model: string; model_label?: string; target_language: string };
  artifact_id?: string;
};

export function PromptTranslationControl({
  value,
  onChange,
  disabled,
}: {
  value: TranslationOptions;
  onChange: (value: TranslationOptions) => void;
  disabled: boolean;
}) {
  const [names, setNames] = useState(value.protected_terms.join("\n"));
  const preferences = useQuery({
    queryKey: ["generation-preferences"],
    queryFn: () => api<GenerationPreferences>("/generation/preferences"),
    staleTime: 30000,
  });
  const enabled =
    value.mode === "on" ||
    (value.mode === "inherit" && !!preferences.data?.enabled);
  return (
    <div className="prompt-translation-control">
      <label>
        Prompt language
        <select
          disabled={disabled}
          value={value.mode}
          onChange={(event) =>
            onChange({
              ...value,
              mode: event.target.value as TranslationOptions["mode"],
            })
          }
        >
          <option value="inherit">
            Station default
            {preferences.data
              ? preferences.data.enabled
                ? " · Translate to English"
                : " · Keep original"
              : ""}
          </option>
          <option value="on">Translate to English</option>
          <option value="off">Keep original</option>
        </select>
      </label>
      <details>
        <summary>Translation options</summary>
        <p className="muted">
          Only descriptive instructions are translated. The original is
          retained; quoted text, lyrics, numbers and model tokens stay
          unchanged.{" "}
          <Link to="/settings/generation">Choose local translator</Link>
        </p>
        <label className="image-workflow-option">
          <input
            type="checkbox"
            disabled={disabled || !enabled}
            checked={value.review}
            onChange={(event) =>
              onChange({ ...value, review: event.target.checked })
            }
          />
          <span>
            Review before generation
            <small>
              Pause after translating so you can inspect or edit the prompt.
            </small>
          </span>
        </label>
        <label>
          Names or trigger words to preserve
          <textarea
            rows={2}
            maxLength={6432}
            disabled={disabled || !enabled}
            placeholder="One name or token per line"
            value={names}
            onChange={(event) => {
              setNames(event.target.value);
              onChange({
                ...value,
                protected_terms: event.target.value
                  .split("\n")
                  .map((term) => term.trim())
                  .filter(Boolean),
              });
            }}
          />
        </label>
      </details>
    </div>
  );
}

export function PromptReceipt({
  receipt,
  dispatched = true,
}: {
  receipt: TranslationReceipt;
  dispatched?: boolean;
}) {
  return (
    <details className="prompt-translation-receipt">
      <summary>
        {dispatched ? "Prompt sent to model" : "Prompt prepared for model"}
      </summary>
      <p className="muted">
        {receipt.status === "original"
          ? "Original used by your choice"
          : `Local translation · ${receipt.policy.model_label || receipt.policy.model} · ${receipt.policy.target_language.toUpperCase()}`}
      </p>
      {Object.entries(receipt.original).map(([key, original]) => (
        <div key={key}>
          <h4>
            {key === "edit_prompt"
              ? "Edit instruction"
              : key === "negative" || key === "negative_prompt"
                ? "Negative prompt"
                : key === "caption"
                  ? "Music description"
                  : key === "video_prompt"
                    ? "Motion prompt"
                    : "Prompt"}
          </h4>
          <span className="eyebrow">YOUR ORIGINAL</span>
          <p>{original}</p>
          <span className="eyebrow">
            {dispatched ? "SENT TO MODEL" : "PREPARED · NOT DISPATCHED"}
          </span>
          <p>{receipt.effective?.[key] ?? "Not dispatched yet"}</p>
        </div>
      ))}
      {receipt.artifact_id && (
        <Link to={`/library/${receipt.artifact_id}`}>
          Inspect translation receipt
        </Link>
      )}
    </details>
  );
}

export function FreshMediaRetry({ run }: { run: Run }) {
  const fresh = run.metadata?.fresh_media_retry as
    { run_id: string } | undefined;
  if (!fresh) return null;
  return (
    <div className="prompt-translation-panel" role="status">
      <p>A new task was started. This earlier task remains stopped.</p>
      <Link to={`/runs/${fresh.run_id}`}>Open new attempt →</Link>
    </div>
  );
}

export default function PromptTranslation({
  run,
  onRecover,
  onRetried,
}: {
  run: Run;
  onRecover?: (action: TranslationRecovery) => Promise<unknown>;
  onRetried?: (run: Run) => void;
}) {
  const receipt = run.metadata?.prompt_translation as
    TranslationReceipt | undefined;
  const prep = useMediaRun(receipt?.preparation_run_id ?? "");
  const review = useMediaRun(receipt?.review_run_id ?? "");
  const [edited, setEdited] = useState<Record<string, string> | null>(null);
  const [, setSearch] = useSearchParams();
  const cache = useQueryClient();
  const identity = useRef<{ action: string; id: string } | null>(null);
  const panel = useRef<HTMLElement>(null);
  const needsReview =
    review.data?.status === "waiting_for_approval" && run.status === "queued";
  useEffect(() => {
    if (needsReview)
      panel.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [needsReview]);
  const resolve = useMutation({
    mutationFn: async (action: TranslationRecovery) => {
      if (onRecover) {
        await onRecover(action);
        return null;
      }
      if (identity.current?.action !== action)
        identity.current = { action, id: randomId() };
      const current = await api<Run>(`/runs/${run.id}`);
      if (!["failed", "canceled", "interrupted"].includes(current.status)) {
        try {
          await api(`/runs/${run.id}/cancel`, { method: "POST" });
        } catch (cause) {
          const confirmed = await api<Run>(`/runs/${run.id}`);
          if (!["failed", "canceled", "interrupted"].includes(confirmed.status))
            throw cause;
        }
      }
      const path =
        run.executor_type === "photo_pipe"
          ? `/images/runs/${run.id}/retry`
          : `/generation/media/${run.id}/retry`;
      return api<Run>(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          translation: action,
          client_request_id: identity.current.id,
        }),
      });
    },
    onSuccess: (next) => {
      identity.current = null;
      if (!next) return;
      cache.setQueryData(["run", next.id], next);
      void cache.invalidateQueries({ queryKey: ["runs"] });
      if (onRetried) {
        onRetried(next);
        return;
      }
      setSearch((current) => {
        const params = new URLSearchParams(current);
        params.set("run", next.id);
        return params;
      });
    },
  });
  const approve = useMutation({
    mutationFn: () =>
      api(`/generation/translations/${review.data!.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          expected_hash: review.data!.approval?.payload.effective_hash,
          effective: edited ?? review.data!.parameters.effective,
        }),
      }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["conversation"] });
      void cache.invalidateQueries({ queryKey: ["run", run.id] });
      void cache.invalidateQueries({ queryKey: ["run", review.data!.id] });
    },
  });
  if (!receipt) return null;
  if (run.metadata?.fresh_media_retry)
    return (
      <section
        className="prompt-translation-panel"
        aria-label="Prompt translation"
      >
        <FreshMediaRetry run={run} />
        <PromptReceipt
          receipt={receipt}
          dispatched={run.status === "running" || run.status === "succeeded"}
        />
      </section>
    );
  const failed =
    (prep.data &&
      ["failed", "canceled", "interrupted"].includes(prep.data.status)) ||
    (review.data &&
      ["failed", "canceled", "interrupted"].includes(review.data.status));
  const waiting =
    review.data?.status === "waiting_for_approval" && run.status === "queued";
  const ready = ["ready", "original"].includes(receipt.status);
  const canResolve = ["failed", "canceled", "interrupted"].includes(run.status);
  return (
    <section
      className="prompt-translation-panel"
      ref={panel}
      aria-label="Prompt translation"
    >
      {!ready && !failed && !waiting && (
        <p role="status">
          {receipt.status === "waiting_for_review"
            ? "Applying your reviewed prompt before generation…"
            : "Translating your prompt locally before generation…"}
        </p>
      )}
      <ErrorNotice
        error={
          resolve.error ??
          (waiting ? approve.error : null) ??
          prep.error ??
          review.error
        }
      />
      {failed && !ready && (
        <>
          <p role="alert">
            Translation did not complete.{" "}
            {prep.data?.error_message || review.data?.error_message}
          </p>
          <div className="row">
            <Button
              type="button"
              variant="secondary"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate("retry")}
            >
              Retry translation
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate("original")}
            >
              Use original
            </Button>
          </div>
        </>
      )}
      {ready && canResolve && (
        <details>
          <summary>Translation alternatives</summary>
          <p>
            The ordinary retry reuses the recorded effective prompt. Choose
            explicitly to translate again or use your original wording.
          </p>
          <div className="row">
            {run.executor_type !== "photo_pipe" && (
              <Button
                type="button"
                variant="secondary"
                disabled={resolve.isPending}
                onClick={() => resolve.mutate("reuse")}
              >
                Retry generation
              </Button>
            )}
            <Button
              type="button"
              variant="secondary"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate("retry")}
            >
              Translate again
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={resolve.isPending}
              onClick={() => resolve.mutate("original")}
            >
              Use original
            </Button>
          </div>
        </details>
      )}
      {waiting && (
        <div className="translation-review">
          <h3>Review before generation</h3>
          <p>
            Your source files and generation settings are unchanged. Check the
            translated instructions, then continue.
          </p>
          {Object.entries(
            edited ??
              (review.data!.parameters.effective as Record<string, string>),
          ).map(([key, text]) => (
            <label key={key}>
              {key === "negative" || key === "negative_prompt"
                ? "Translated negative prompt"
                : key === "caption"
                  ? "Translated music description"
                  : key === "edit_prompt"
                    ? "Translated edit instruction"
                    : "Translated prompt"}
              <textarea
                rows={3}
                maxLength={Number(
                  (
                    review.data?.parameters.field_limits as
                      Record<string, number> | undefined
                  )?.[key] ?? 10000,
                )}
                value={text}
                disabled={approve.isPending || resolve.isPending}
                onChange={(event) =>
                  setEdited({
                    ...((edited ?? review.data!.parameters.effective) as Record<
                      string,
                      string
                    >),
                    [key]: event.target.value,
                  })
                }
              />
            </label>
          ))}
          <div className="row">
            <Button
              type="button"
              disabled={approve.isPending || resolve.isPending}
              onClick={() => approve.mutate()}
            >
              Use translated prompt
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={approve.isPending || resolve.isPending}
              onClick={() => resolve.mutate("original")}
            >
              Use original
            </Button>
          </div>
        </div>
      )}
      <PromptReceipt
        receipt={receipt}
        dispatched={run.status === "running" || run.status === "succeeded"}
      />
      {receipt.preparation_run_id && (
        <Link to={`/runs/${receipt.preparation_run_id}`}>
          Inspect translation Run
        </Link>
      )}
    </section>
  );
}
