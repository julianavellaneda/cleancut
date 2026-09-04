/**
 * The waveform's imperative handle - the half of it the keyboard drives.
 *
 * `WaveformHandle` is the only way the review page can start, stop or move
 * playback, and all three methods are arithmetic over a duration that is zero
 * until WaveSurfer says "ready". That is the shape of every bug this file
 * pins: a `playClip` before the audio loaded divided by zero and seeked to
 * `NaN`, a pre-roll ran off the front of the file, and the auto-pause timer
 * from one clip paused the *next* one a second into playback - easy to hit now
 * that `P` retriggers a clip as fast as it can be pressed.
 *
 * WaveSurfer itself is mocked: it decodes real audio through an element jsdom
 * has no decoder for. The mock is a recorder, not a reimplementation - the
 * assertions are about what the component asks WaveSurfer to do.
 */

import { createRef } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import WaveSurfer from "wavesurfer.js";

import { Waveform, WaveformHandle } from "./Waveform";
import { Violation } from "@/lib/api";
import { THEME_EVENT, THEME_STORAGE_KEY } from "@/lib/theme";

const ws = vi.hoisted(() => {
  const listeners = new Map<string, ((...args: unknown[]) => void)[]>();
  return {
    listeners,
    duration: 0,
    load: vi.fn(),
    on: vi.fn((event: string, cb: (...args: unknown[]) => void) => {
      listeners.set(event, [...(listeners.get(event) ?? []), cb]);
    }),
    getDuration: vi.fn(() => ws.duration),
    seekTo: vi.fn(),
    play: vi.fn(),
    pause: vi.fn(),
    playPause: vi.fn(),
    setOptions: vi.fn(),
    destroy: vi.fn(),
    emit(event: string, ...args: unknown[]) {
      (listeners.get(event) ?? []).forEach(cb => cb(...args));
    },
  };
});

interface RegionOptions {
  id: string;
  color: string;
  start: number;
  end: number;
}

const regions = vi.hoisted(() => ({
  // The real plugin hands back a region that knows its own id and takes a
  // click handler; the component uses both.
  addRegion: vi.fn((options: RegionOptions) => ({ id: options.id, on: vi.fn() })),
  clearRegions: vi.fn(),
}));

vi.mock("wavesurfer.js", () => ({
  default: { create: vi.fn(() => ws) },
}));

vi.mock("wavesurfer.js/dist/plugins/regions.js", () => ({
  default: { create: vi.fn(() => regions) },
}));

function violation(overrides: Partial<Violation> = {}): Violation {
  return {
    id: "v1",
    job_id: "job-1",
    text: "um",
    start_time: 1,
    end_time: 2,
    label: "Filler Word",
    rule_violated: null,
    severity: "low",
    reasoning: "a hesitation",
    status: "pending",
    action: "cut",
    is_approximate: false,
    is_ambiguous: false,
    ...overrides,
  };
}

/** Render the waveform and hand back its imperative handle. */
function renderWaveform({
  violations = [] as Violation[],
  mediaRef,
}: { violations?: Violation[]; mediaRef?: React.RefObject<HTMLMediaElement | null> } = {}) {
  const ref = createRef<WaveformHandle>();
  const onViolationClick = vi.fn();
  const { unmount } = render(
    <Waveform
      ref={ref}
      audioUrl="http://example.test/audio"
      violations={violations}
      selectedViolation={null}
      onViolationClick={onViolationClick}
      mediaRef={mediaRef}
    />
  );
  return { ref, onViolationClick, unmount };
}

/** What WaveSurfer reports once the file has decoded. */
function becomeReady(duration = 60) {
  ws.duration = duration;
  act(() => ws.emit("ready"));
}

beforeEach(() => {
  vi.clearAllMocks();
  ws.listeners.clear();
  ws.duration = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("before the audio is ready", () => {
  it("ignores playClip and seekTo rather than seeking to NaN", async () => {
    // duration is 0 here, and every one of these divides by it.
    const { ref } = renderWaveform();

    act(() => ref.current!.playClip(10, 12));
    act(() => ref.current!.seekTo(10));

    expect(ws.play).not.toHaveBeenCalled();
    expect(ws.seekTo).not.toHaveBeenCalled();
  });

  it("disables the transport controls", () => {
    renderWaveform();

    expect(screen.getByRole("button", { name: "Play" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "-5s" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "+5s" })).toBeDisabled();
  });
});

describe("playClip", () => {
  beforeEach(() => vi.useFakeTimers());

  it("starts half a second early and pauses half a second after the span", () => {
    const { ref } = renderWaveform();
    becomeReady(60);

    act(() => ref.current!.playClip(10, 12));

    expect(ws.seekTo).toHaveBeenLastCalledWith(9.5 / 60);
    expect(ws.play).toHaveBeenCalledTimes(1);
    expect(ws.pause).not.toHaveBeenCalled();

    // 9.5s -> 12.5s is a three second clip.
    act(() => vi.advanceTimersByTime(2999));
    expect(ws.pause).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(1));
    expect(ws.pause).toHaveBeenCalledTimes(1);
  });

  it("clamps the pre-roll at the start of the file", () => {
    const { ref } = renderWaveform();
    becomeReady(60);

    // 0.2 - 0.5 is negative, which seeks backwards past the beginning.
    act(() => ref.current!.playClip(0.2, 1));

    expect(ws.seekTo).toHaveBeenLastCalledWith(0);
  });

  it("cancels the previous clip's pause timer when retriggered", () => {
    // `P` is one keypress, so clips overlap constantly. An uncleared timer from
    // the first pauses the second a moment after it starts.
    const { ref } = renderWaveform();
    becomeReady(60);

    act(() => ref.current!.playClip(10, 12));
    act(() => vi.advanceTimersByTime(1000));
    act(() => ref.current!.playClip(30, 40));

    // The first clip's timer would have fired at 3000ms.
    act(() => vi.advanceTimersByTime(2500));
    expect(ws.pause).not.toHaveBeenCalled();

    // The second clip's own timer still does, on its own schedule.
    act(() => vi.advanceTimersByTime(8500));
    expect(ws.pause).toHaveBeenCalledTimes(1);
  });

  it("does not pause after the component is gone", () => {
    // Navigating away mid-clip: the unmount effect clears the timer, so the
    // callback never reaches a destroyed WaveSurfer.
    const { ref, unmount } = renderWaveform();
    becomeReady(60);
    act(() => ref.current!.playClip(10, 12));

    act(() => unmount());
    act(() => vi.advanceTimersByTime(10_000));

    expect(ws.pause).not.toHaveBeenCalled();
  });
});

describe("seekTo", () => {
  beforeEach(() => vi.useFakeTimers());

  it("clamps to the file rather than seeking outside it", () => {
    const { ref } = renderWaveform();
    becomeReady(60);

    act(() => ref.current!.seekTo(90));
    expect(ws.seekTo).toHaveBeenLastCalledWith(1);

    act(() => ref.current!.seekTo(-5));
    expect(ws.seekTo).toHaveBeenLastCalledWith(0);

    act(() => ref.current!.seekTo(15));
    expect(ws.seekTo).toHaveBeenLastCalledWith(15 / 60);
  });

  it("drops a pending clip timer, which belongs to the clip just left", () => {
    // Clicking a transcript line mid-clip: the old auto-pause would otherwise
    // stop playback a second or two after the seek landed.
    const { ref } = renderWaveform();
    becomeReady(60);

    act(() => ref.current!.playClip(10, 12));
    act(() => ref.current!.seekTo(40));
    act(() => vi.advanceTimersByTime(10_000));

    expect(ws.pause).not.toHaveBeenCalled();
  });
});

describe("with a video element driving playback", () => {
  beforeEach(() => vi.useFakeTimers());

  it("moves the media element, not WaveSurfer", () => {
    const media = { currentTime: 0, play: vi.fn(), pause: vi.fn() };
    const mediaRef = { current: media as unknown as HTMLMediaElement };

    const { ref } = renderWaveform({ mediaRef });
    becomeReady(60);

    act(() => ref.current!.playClip(10, 12));

    expect(media.currentTime).toBe(9.5);
    expect(media.play).toHaveBeenCalledTimes(1);
    expect(ws.play).not.toHaveBeenCalled();

    act(() => vi.advanceTimersByTime(3000));
    expect(media.pause).toHaveBeenCalledTimes(1);
    expect(ws.pause).not.toHaveBeenCalled();

    act(() => ref.current!.seekTo(20));
    expect(media.currentTime).toBe(20);
    expect(ws.seekTo).not.toHaveBeenCalled();
  });

  it("does not load the url itself, since the element owns the media", () => {
    const media = { currentTime: 0, play: vi.fn(), pause: vi.fn() };
    renderWaveform({ mediaRef: { current: media as unknown as HTMLMediaElement } });

    expect(ws.load).not.toHaveBeenCalled();
  });
});

describe("the transport", () => {
  it("hands togglePlayPause straight to WaveSurfer", () => {
    const { ref } = renderWaveform();
    becomeReady(60);

    act(() => ref.current!.togglePlayPause());

    expect(ws.playPause).toHaveBeenCalledTimes(1);
  });

  it("follows WaveSurfer's own play and pause events", async () => {
    renderWaveform();
    becomeReady(60);

    expect(screen.getByRole("button", { name: "Play" })).toBeEnabled();

    act(() => ws.emit("play"));
    expect(screen.getByRole("button", { name: "Pause" })).toBeInTheDocument();

    act(() => ws.emit("pause"));
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();

    // A clip that runs to the end never emits "pause", only "finish".
    act(() => ws.emit("play"));
    act(() => ws.emit("finish"));
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("skips five seconds either way, clamped to the file", async () => {
    renderWaveform();
    becomeReady(60);
    act(() => ws.emit("timeupdate", 30));

    await userEvent.click(screen.getByRole("button", { name: "+5s" }));
    expect(ws.seekTo).toHaveBeenLastCalledWith(35 / 60);

    await userEvent.click(screen.getByRole("button", { name: "-5s" }));
    expect(ws.seekTo).toHaveBeenLastCalledWith(25 / 60);

    act(() => ws.emit("timeupdate", 2));
    await userEvent.click(screen.getByRole("button", { name: "-5s" }));
    expect(ws.seekTo).toHaveBeenLastCalledWith(0);

    act(() => ws.emit("timeupdate", 58));
    await userEvent.click(screen.getByRole("button", { name: "+5s" }));
    expect(ws.seekTo).toHaveBeenLastCalledWith(1);
  });

  it("shows the elapsed and total time", () => {
    renderWaveform();
    becomeReady(125);
    act(() => ws.emit("timeupdate", 65));

    expect(screen.getByText("1:05 / 2:05")).toBeInTheDocument();
  });
});

describe("regions", () => {
  it("colours each suggestion by its action, and fades a decided one", () => {
    renderWaveform({
      violations: [
        violation({ id: "cut", action: "cut", status: "pending", start_time: 1, end_time: 2 }),
        violation({ id: "mute", action: "mute", status: "pending", start_time: 3, end_time: 4 }),
        violation({ id: "gone", action: "cut", status: "rejected", start_time: 5, end_time: 6 }),
      ],
    });
    becomeReady(60);

    const byId: Record<string, RegionOptions> = Object.fromEntries(
      regions.addRegion.mock.calls.map(([r]) => [r.id, r])
    );

    // Keyed off the *action*, because that is what the export will do to the
    // file: the first accent for a cut, the second for a mute. Severity used to
    // be the key here and moved to a word in the list and the detail panel.
    expect(byId.cut.color).toBe("var(--acc-200)");
    expect(byId.mute.color).toBe("var(--acc2-200)");
    // A rejected suggestion keeps its place but stops competing for attention.
    expect(byId.gone.color).toBe("var(--faint)");
  });

  it("hands the plugin custom properties, not resolved colours", () => {
    // The whole reason a theme flip does not have to repaint the regions: the
    // browser re-resolves `var()` on the element itself. Only the canvas needs
    // real values, and that is what `setOptions` below is for.
    renderWaveform({ violations: [violation()] });
    becomeReady(60);

    const [{ color }] = regions.addRegion.mock.calls[0];
    expect(color).toMatch(/^var\(--/);
  });

  it("redraws from scratch when the list changes, so a stale span cannot linger", () => {
    renderWaveform({ violations: [violation()] });
    becomeReady(60);

    expect(regions.clearRegions).toHaveBeenCalled();
    expect(regions.addRegion).toHaveBeenCalledTimes(1);
  });

  it("selects the suggestion behind a region the user clicks", () => {
    const first = violation({ id: "v1" });
    const second = violation({ id: "v2", start_time: 30, end_time: 31 });
    const { onViolationClick } = renderWaveform({ violations: [first, second] });
    becomeReady(60);

    // Each region gets its own handler closed over its own violation - the
    // waveform is the only place a suggestion can be picked by *when* it
    // happens rather than by where it sits in the list.
    const [, handler] = regions.addRegion.mock.results[1].value.on.mock.calls[0];
    act(() => handler());

    expect(onViolationClick).toHaveBeenCalledWith(second);
  });

  it("draws nothing until the audio is ready", () => {
    renderWaveform({ violations: [violation()] });

    expect(regions.addRegion).not.toHaveBeenCalled();
  });
});

describe("the parent's time callback", () => {
  /**
   * Read through a ref, not called as a prop. The handler that calls it is
   * registered inside the effect that *creates* WaveSurfer, so closing over the
   * prop leaves two bad options: leave it out of the dependencies and the
   * handler keeps calling the first render's callback forever, or list it and
   * every unmemoized parent render destroys the player and reloads the audio.
   * This asserts against both at once.
   */
  it("stays current without rebuilding the player", () => {
    const first = vi.fn();
    const second = vi.fn();
    const withCallback = (onTimeUpdate: (time: number) => void) => (
      <Waveform
        audioUrl="http://example.test/audio"
        violations={[]}
        selectedViolation={null}
        onViolationClick={vi.fn()}
        onTimeUpdate={onTimeUpdate}
      />
    );

    const { rerender } = render(withCallback(first));
    becomeReady(60);
    act(() => ws.emit("timeupdate", 4));
    expect(first).toHaveBeenCalledWith(4);

    // A parent that does not memoize its callback - which is every parent the
    // component cannot see.
    rerender(withCallback(second));
    act(() => ws.emit("timeupdate", 9));

    expect(second).toHaveBeenCalledWith(9);
    expect(first).toHaveBeenCalledTimes(1);
    expect(ws.destroy).not.toHaveBeenCalled();
    expect(ws.load).toHaveBeenCalledTimes(1);
  });
});

describe("a theme flip", () => {
  afterEach(() => {
    document.documentElement.removeAttribute("data-theme");
    window.localStorage.removeItem(THEME_STORAGE_KEY);
  });

  /**
   * The canvas is the one place `var()` cannot reach: WaveSurfer resolves the
   * three colours once and fills a canvas gradient with them. Rebuilding the
   * instance would recolour it - and re-fetch and re-decode the whole file to
   * do it, dropping the playhead on the way. `setOptions` is the fix.
   */
  it("recolours the canvas without rebuilding the player", () => {
    renderWaveform();
    becomeReady(60);
    const buildsBefore = (WaveSurfer.create as unknown as Mock).mock.calls.length;

    act(() => {
      document.documentElement.setAttribute("data-theme", "dark");
      window.dispatchEvent(new Event(THEME_EVENT));
    });

    expect(ws.setOptions).toHaveBeenCalled();
    expect((WaveSurfer.create as unknown as Mock).mock.calls).toHaveLength(buildsBefore);
    expect(ws.load).toHaveBeenCalledTimes(1);
  });
});
