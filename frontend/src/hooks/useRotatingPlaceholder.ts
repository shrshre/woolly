import { useEffect, useState } from "react";

const FADE_MS = 450;

/** Cycles through sample strings with a fade-out / fade-in between each.
 *  Pauses while `paused` is true (e.g. the user has typed or the field is focused). */
export function useRotatingPlaceholder(
  samples: readonly string[],
  paused = false,
  intervalMs = 3500,
): { text: string; visible: boolean } {
  const [index, setIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (paused) setVisible(true);
  }, [paused]);

  useEffect(() => {
    if (paused || samples.length <= 1) return;

    let fadeTimeout: number | undefined;

    const id = window.setInterval(() => {
      setVisible(false);
      fadeTimeout = window.setTimeout(() => {
        setIndex((i) => (i + 1) % samples.length);
        setVisible(true);
      }, FADE_MS);
    }, intervalMs);

    return () => {
      window.clearInterval(id);
      if (fadeTimeout !== undefined) window.clearTimeout(fadeTimeout);
    };
  }, [paused, samples.length, intervalMs]);

  return {
    text: samples[index] ?? samples[0] ?? "",
    visible,
  };
}
