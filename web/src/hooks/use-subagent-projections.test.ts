import { describe, expect, it } from "vitest";
import { resumingIterator } from "./use-subagent-projections";

/** The SDK's SubscriptionHandle, reduced to the behaviour under test: an
 *  iterator that ends on pause (and on close), a resume that wakes waiters,
 *  events buffered while paused. */
class FakeHandle<T> {
  closed = false;
  paused = false;
  private queue: T[] = [];
  private waiters: ((r: IteratorResult<T>) => void)[] = [];
  private resumeResolve: (() => void) | undefined;

  push(event: T) {
    const waiter = this.waiters.shift();
    if (waiter) waiter({ done: false, value: event });
    else this.queue.push(event);
  }
  pause() {
    this.paused = true;
    while (this.waiters.length) this.waiters.shift()?.({ done: true, value: undefined });
  }
  resume() {
    this.paused = false;
    this.resumeResolve?.();
    this.resumeResolve = undefined;
  }
  close() {
    this.closed = true;
    this.paused = false;
    while (this.waiters.length) this.waiters.shift()?.({ done: true, value: undefined });
    this.resumeResolve?.();
  }
  get isPaused() {
    return this.paused;
  }
  waitForResume(): Promise<void> {
    if (!this.paused) return Promise.resolve();
    return new Promise((resolve) => {
      this.resumeResolve = resolve;
    });
  }
  [Symbol.asyncIterator](): AsyncIterator<T> {
    return {
      next: async () => {
        if (this.queue.length > 0) return { done: false, value: this.queue.shift() as T };
        if (this.closed || this.paused) return { done: true, value: undefined };
        return new Promise((resolve) => {
          this.waiters.push(resolve);
        });
      },
      return: async () => {
        this.close();
        return { done: true, value: undefined };
      },
    };
  }
}

const tick = () => new Promise((r) => setTimeout(r, 0));

describe("resumingIterator", () => {
  it("keeps yielding across a pause and ends on close", async () => {
    const handle = new FakeHandle<string>();
    const seen: string[] = [];
    let ended = false;
    const consume = (async () => {
      for await (const e of resumingIterator(handle)) seen.push(e);
      ended = true;
    })();

    handle.push("run1-a");
    await tick();
    handle.pause(); // terminal lifecycle of run 1
    await tick();
    expect(seen).toEqual(["run1-a"]);
    expect(ended).toBe(false);

    handle.push("run2-buffered"); // arrives while paused: buffered
    handle.resume(); // input.respond accepted → next run
    await tick();
    handle.push("run2-b");
    await tick();
    expect(seen).toEqual(["run1-a", "run2-buffered", "run2-b"]);

    handle.close();
    await consume;
    expect(ended).toBe(true);
  });

  it("the SDK's plain iteration ends at the pause (the behaviour worked around)", async () => {
    const handle = new FakeHandle<string>();
    const seen: string[] = [];
    const consume = (async () => {
      for await (const e of handle) seen.push(e);
    })();
    handle.push("a");
    await tick();
    handle.pause();
    await consume; // ends here
    handle.resume();
    handle.push("b");
    expect(seen).toEqual(["a"]);
  });

  it("closing the consumer closes the handle", async () => {
    const handle = new FakeHandle<string>();
    const it = resumingIterator(handle);
    handle.push("a");
    expect((await it.next()).value).toBe("a");
    await it.return();
    expect(handle.closed).toBe(true);
  });
});
