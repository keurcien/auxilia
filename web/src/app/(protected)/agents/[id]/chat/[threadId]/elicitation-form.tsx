"use client";

import { type ComponentProps, useState } from "react";
import { ExternalLinkIcon } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  type ElicitationAnswer,
  type ElicitationChoices,
  type ElicitationField,
  type ElicitationInterrupt,
  type ElicitationRequest,
  type ElicitationResponse,
  elicitationChoices,
} from "@/lib/transcript";

/** Answers per request key, then per field. Maps, because every key here is
 *  the server's to choose. */
type FormValues = Map<string, Map<string, unknown>>;

/**
 * An MCP server asking for input mid tool call (`langchain.mcp` raises it as
 * an interrupt). One form for every request in the round; submitting accepts
 * them all, declining declines them all — the server then decides what to do.
 */
export function ElicitationForm({
  interrupt,
  interruptId,
  respond,
  disabled = false,
}: {
  interrupt: ElicitationInterrupt;
  /** Required: an unaddressed answer could land on another pending interrupt. */
  interruptId: string;
  respond: (response: ElicitationResponse, interruptId: string | null) => void;
  disabled?: boolean;
}) {
  const [values, setValues] = useState<FormValues>(
    () => new Map(interrupt.requests.map((r) => [r.key, defaults(r)])),
  );
  const [sent, setSent] = useState(false);

  const answer = (build: (r: ElicitationRequest) => ElicitationAnswer) => {
    setSent(true);
    respond(
      {
        responses: Object.fromEntries(
          interrupt.requests.map((r) => [r.key, build(r)]),
        ),
      },
      interruptId,
    );
  };
  const off = disabled || sent;
  const incomplete = interrupt.requests.some((r) =>
    missingAnswers(r, values.get(r.key) ?? new Map()),
  );

  return (
    <form
      className="my-3 space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        answer((r) =>
          r.mode === "form"
            ? { action: "accept", content: Object.fromEntries(values.get(r.key) ?? []) }
            : { action: "accept" },
        );
      }}
    >
      {interrupt.requests.map((request) => (
        <fieldset key={request.key} disabled={off} className="space-y-2">
          <p className="text-sm">{request.message}</p>
          {request.mode === "url" ? (
            <a
              href={request.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-petrol underline"
            >
              Open link <ExternalLinkIcon className="size-3" />
            </a>
          ) : (
            // The question spans the step; the controls keep a readable width.
            <div className="max-w-md space-y-4">
            {Object.entries(request.requested_schema.properties ?? {}).map(
              ([name, field], _, all) => (
                <FieldInput
                  key={name}
                  name={name}
                  field={field}
                  // One question needs no heading; several chip groups do, or
                  // they read as one list.
                  titled={all.length > 1}
                  required={request.requested_schema.required?.includes(name) ?? false}
                  value={values.get(request.key)?.get(name)}
                  onChange={(v) => {
                    setValues((prev) =>
                      new Map(prev).set(
                        request.key,
                        new Map(prev.get(request.key)).set(name, v),
                      ),
                    );
                  }}
                />
              ),
            )}
            </div>
          )}
        </fieldset>
      ))}
      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={off || incomplete}
          className="cursor-pointer rounded-md bg-petrol px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {interrupt.requests.every((r) => r.mode === "url") ? "Done" : "Submit"}
        </button>
        <button
          type="button"
          disabled={off}
          onClick={() => {
            answer(() => ({ action: "decline" }));
          }}
          className="cursor-pointer rounded-md border border-input bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:border-border-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          Decline
        </button>
      </div>
    </form>
  );
}

/** One schema property, without label or help text: options and booleans
 *  as chips, anything else as an input whose placeholder is the title. */
function FieldInput({
  name,
  field,
  required,
  titled,
  value,
  onChange,
}: {
  name: string;
  field: ElicitationField;
  required: boolean;
  titled: boolean;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const title = field.title ?? name;
  const choices = elicitationChoices(field);
  if (choices) {
    const chips = (
      <ChoiceChips
        label={title}
        choices={choices}
        value={value}
        onChange={onChange}
        max={field.maxItems}
      />
    );
    return titled ? (
      <div className="space-y-1.5">
        <p className="text-xs font-medium text-muted-foreground">{title}</p>
        {chips}
      </div>
    ) : (
      chips
    );
  }
  if (field.type === "boolean") {
    return (
      <Chip
        on={value === true}
        aria-pressed={value === true}
        onClick={() => {
          // Unset until tapped, so an unanswered optional boolean is not
          // sent as `false`; once tapped it toggles true / false.
          onChange(value !== true);
        }}
      >
        {title}
      </Chip>
    );
  }
  return (
    <Input
      aria-label={title}
      placeholder={title}
      required={required}
      type={inputType(field)}
      step={field.type === "integer" ? 1 : field.type === "number" ? "any" : undefined}
      value={typeof value === "string" || typeof value === "number" ? value : ""}
      onChange={(e) => {
        const raw = e.target.value;
        const numeric = field.type === "number" || field.type === "integer";
        onChange(numeric && raw !== "" ? Number(raw) : raw);
      }}
    />
  );
}

function Chip({
  on,
  className,
  ...props
}: ComponentProps<"button"> & { on: boolean }) {
  return (
    <button
      type="button"
      className={cn(
        "w-full cursor-pointer rounded-md border px-3 py-2 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        on
          ? "border-petrol bg-petrol text-white"
          : "border-input bg-card text-foreground hover:border-border-hover",
        className,
      )}
      {...props}
    />
  );
}

/** Server-supplied options as chips: one pick (radio) or several (toggles,
 *  capped at the schema's `maxItems`). */
function ChoiceChips({
  label,
  choices,
  value,
  onChange,
  max,
}: {
  label: string;
  choices: ElicitationChoices;
  value: unknown;
  onChange: (value: unknown) => void;
  max?: number;
}) {
  const picked = choices.multi
    ? Array.isArray(value)
      ? (value as string[])
      : []
    : typeof value === "string"
      ? [value]
      : [];
  const full = max != null && picked.length >= max;
  return (
    <div
      role={choices.multi ? "group" : "radiogroup"}
      aria-label={label}
      className="flex flex-col gap-1.5"
    >
      {choices.options.map((option) => {
        const on = picked.includes(option.value);
        return (
          <Chip
            key={option.value}
            on={on}
            role={choices.multi ? undefined : "radio"}
            aria-checked={choices.multi ? undefined : on}
            aria-pressed={choices.multi ? on : undefined}
            disabled={!on && choices.multi && full}
            onClick={() => {
              if (!choices.multi) onChange(option.value);
              else
                onChange(
                  on
                    ? picked.filter((v) => v !== option.value)
                    : [...picked, option.value],
                );
            }}
          >
            {option.label}
          </Chip>
        );
      })}
    </div>
  );
}

/** Chips aren't native inputs, so `required` / `minItems` are checked here. */
function missingAnswers(request: ElicitationRequest, answers: Map<string, unknown>) {
  if (request.mode !== "form") return false;
  const { properties = {}, required = [] } = request.requested_schema;
  return Object.entries(properties).some(([name, field]) => {
    const v = answers.get(name);
    if (field.type === "boolean") return required.includes(name) && v === undefined;
    const choices = elicitationChoices(field);
    if (!choices) return false;
    const count = Array.isArray(v) ? v.length : v ? 1 : 0;
    const min = field.minItems ?? (required.includes(name) ? 1 : 0);
    return count < min;
  });
}

function inputType(field: ElicitationField): string {
  if (field.type === "number" || field.type === "integer") return "number";
  if (field.format === "date") return "date";
  if (field.format === "email") return "email";
  if (field.format === "uri") return "url";
  return "text";
}

/** The schema's own defaults; anything else starts unanswered. */
function defaults(request: ElicitationRequest): Map<string, unknown> {
  if (request.mode !== "form") return new Map();
  return new Map(
    Object.entries(request.requested_schema.properties ?? {})
      .filter(([, f]) => f.default !== undefined)
      .map(([name, f]) => [name, f.default]),
  );
}
