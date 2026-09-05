"use client";

import { useEffect } from "react";
import type { BaseMessage } from "@langchain/core/messages";
import { STREAM_CONTROLLER, useProjection } from "@langchain/react";
import type {
  AnyStream,
  AssembledToolCall,
  SubagentDiscoverySnapshot,
} from "@langchain/react";
import {
  messagesProjection,
  toolCallsProjection,
  valuesProjection,
} from "@langchain/langgraph-sdk/stream";
import type { ProjectionSpec } from "@langchain/langgraph-sdk/stream";
import type {
  SubscriptionHandle,
  ThreadStream,
} from "@langchain/langgraph-sdk/client";

/**
 * Subagent-scoped projections that survive a run boundary.
 *
 * The SDK's `useMessages` / `useToolCalls` / `useValues` open one server
 * subscription per subagent namespace and iterate it with a single
 * `for await`. When the root run reaches a terminal lifecycle the thread
 * client *pauses* every user subscription; the SDK's scoped projections do
 * not opt into resuming (`resumeOnPause` is reserved for `useChannel` /
 * `useExtension`), so their loop ends there and the card is frozen for the
 * rest of the page's life — even though the handle is resumed and keeps
 * buffering events when the next run starts.
 *
 * That is exactly the HITL shape: a subagent's gated tool interrupts the
 * run (terminal `interrupted`), the user approves, the resumed run streams
 * the tool result and the subagent's next turn under the same namespace…
 * into a dead projection. The card kept showing the pre-approval call as
 * pending, and the approval collector re-sent the stale decision against the
 * next interrupt (a 400 from the backend).
 *
 * These hooks reuse the SDK's own projection specs and only wrap the thread
 * they subscribe through, so a paused handle's iterator waits for the
 * resume instead of finishing. Upstream `main` still has the default, so
 * this cannot be fixed by a version bump yet.
 */

const EMPTY_MESSAGES: BaseMessage[] = [];
const EMPTY_TOOL_CALLS: AssembledToolCall[] = [];
const KEY_SUFFIX = "resume-across-runs";

export function useSubagentMessages(
  stream: AnyStream,
  subagent: SubagentDiscoverySnapshot,
): BaseMessage[] {
  useResolveSubagentNamespace(stream, subagent);
  const namespace = subagent.namespace;
  return useProjection(
    registryOf(stream),
    () => resumeAcrossRuns(messagesProjection(namespace)),
    `messages|${namespace.join("|")}|${KEY_SUFFIX}`,
    EMPTY_MESSAGES,
  );
}

export function useSubagentToolCalls(
  stream: AnyStream,
  subagent: SubagentDiscoverySnapshot,
): AssembledToolCall[] {
  useResolveSubagentNamespace(stream, subagent);
  const namespace = subagent.namespace;
  return useProjection(
    registryOf(stream),
    () => resumeAcrossRuns(toolCallsProjection(namespace)),
    `toolCalls|${namespace.join("|")}|${KEY_SUFFIX}`,
    EMPTY_TOOL_CALLS,
  );
}

export function useSubagentValues(
  stream: AnyStream,
  subagent: SubagentDiscoverySnapshot,
): Record<string, unknown> | undefined {
  const namespace = subagent.namespace;
  return useProjection<Record<string, unknown> | undefined>(
    registryOf(stream),
    () =>
      resumeAcrossRuns(
        valuesProjection<Record<string, unknown>>(namespace, "messages"),
      ),
    `values|messages|${namespace.join("|")}|${KEY_SUFFIX}`,
    undefined,
  );
}

/** The stream's controller (the SDK exposes it under a well-known symbol). */
function controllerOf(stream: AnyStream) {
  const { [STREAM_CONTROLLER]: controller } = stream;
  return controller;
}

const registryOf = (stream: AnyStream) => controllerOf(stream).registry;

/** Mirror of the SDK's internal `useResolveSubagentNamespace`: a snapshot
 *  still on its default `tools:<toolCallId>` namespace needs the controller
 *  to look up the real execution namespace before a scoped projection can
 *  target it. The controller de-dupes the call. */
function useResolveSubagentNamespace(
  stream: AnyStream,
  subagent: SubagentDiscoverySnapshot,
) {
  const controller = controllerOf(stream);
  const needsResolution =
    subagent.namespace.length === 1 &&
    subagent.namespace[0] === `tools:${subagent.id}`;
  const toolCallId = needsResolution ? subagent.id : null;
  useEffect(() => {
    if (toolCallId == null) return;
    void controller.resolveSubagentNamespace(toolCallId);
  }, [controller, toolCallId]);
}

/** The same projection, subscribing through a thread whose subscriptions
 *  resume across runs. A distinct key keeps it apart from the SDK's own
 *  registry entry for the namespace. */
export function resumeAcrossRuns<T>(spec: ProjectionSpec<T>): ProjectionSpec<T> {
  return {
    ...spec,
    key: `${spec.key}|${KEY_SUFFIX}`,
    open: (params) =>
      spec.open({ ...params, thread: withResumingSubscribe(params.thread) }),
  };
}

function withResumingSubscribe(thread: ThreadStream): ThreadStream {
  return new Proxy(thread, {
    get(target, prop) {
      if (prop === "subscribe") {
        return async (...args: Parameters<ThreadStream["subscribe"]>) =>
          resumingHandle(await target.subscribe(...args));
      }
      const value: unknown = Reflect.get(target, prop, target);
      return typeof value === "function"
        ? (value as (...a: unknown[]) => unknown).bind(target)
        : value;
    },
  });
}

/** A handle whose async iteration outlives a pause: the SDK ends the
 *  iterator when the thread client pauses on a terminal lifecycle; this one
 *  waits for the resume and keeps yielding (buffered events included). */
export function resumingHandle<H extends SubscriptionHandle>(handle: H): H {
  return new Proxy(handle, {
    get(target, prop) {
      if (prop === Symbol.asyncIterator) {
        return () => resumingIterator(target);
      }
      const value: unknown = Reflect.get(target, prop, target);
      return typeof value === "function"
        ? (value as (...a: unknown[]) => unknown).bind(target)
        : value;
    },
  });
}

/** Ends only when the handle is closed (unsubscribed or the session ended).
 *  A failing handle ends the iteration too — the same outcome as the SDK's
 *  own projection loop, which catches and stops. */
export function resumingIterator<T>(
  handle: AsyncIterable<T> & {
    readonly isPaused: boolean;
    waitForResume(): Promise<void>;
  },
): AsyncIterableIterator<T> {
  const done: IteratorReturnResult<undefined> = { done: true, value: undefined };
  let inner: AsyncIterator<T> | null = null;
  let finished = false;
  return {
    async next() {
      if (finished) return done;
      try {
        for (;;) {
          inner ??= iteratorOf(handle);
          const result = await inner.next();
          // `return()` may have run while we awaited: nothing after cleanup.
          if (finished) break;
          if (!result.done) return result;
          // The SDK's handle ends an iterator for a pause or a close.
          inner = null;
          if (isClosed(handle)) break;
          if (handle.isPaused) {
            await handle.waitForResume();
            if (finished) break;
            continue;
          }
          // Neither paused nor known-closed: treat as closed.
          if (!knowsClosed(handle)) break;
        }
      } catch {
        // A failing handle ends the iteration, as in the SDK's own loop.
      }
      finished = true;
      return done;
    },
    async return() {
      finished = true;
      const current = inner ?? iteratorOf(handle);
      inner = null;
      try {
        await current.return?.();
      } catch {
        // Closing a handle that is already gone is not an error.
      }
      return done;
    },
    [Symbol.asyncIterator]() {
      return this;
    },
  };
}

/** `iterable[Symbol.asyncIterator]()` without a computed member call. */
function iteratorOf<T>(iterable: AsyncIterable<T>): AsyncIterator<T> {
  const { [Symbol.asyncIterator]: open } = iterable;
  return open.call(iterable);
}

// `closed` is a TypeScript-private field on the SDK's handle but a plain
// public property at runtime; it is what tells a pause from the end.
const knowsClosed = (handle: object): boolean =>
  typeof (handle as { closed?: unknown }).closed === "boolean";
const isClosed = (handle: object): boolean =>
  (handle as { closed?: unknown }).closed === true;
