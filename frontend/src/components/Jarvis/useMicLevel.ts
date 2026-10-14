import { useEffect, useState } from 'react';

/** RMS of time-domain samples (0..255, centred at 128) scaled to 0..1. */
export function levelFromSamples(samples: ArrayLike<number>, gain = 4): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) {
    const v = (samples[i] - 128) / 128;
    sum += v * v;
  }
  return Math.min(1, Math.sqrt(sum / samples.length) * gain);
}

/**
 * Live microphone level while `active`, for the HUD waveform.
 *
 * Opens its own analysis stream (useSpeech keeps its MediaRecorder stream
 * private); the browser reuses the permission already granted. Returns null
 * when the level can't be measured, so callers can fall back to a fixed level.
 */
export function useMicLevel(active: boolean): number | null {
  const [level, setLevel] = useState<number | null>(null);

  useEffect(() => {
    if (!active || !navigator.mediaDevices?.getUserMedia || typeof AudioContext === 'undefined') {
      setLevel(null);
      return;
    }
    let cancelled = false;
    let raf = 0;
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) return;
        ctx = new AudioContext();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        ctx.createMediaStreamSource(stream).connect(analyser);
        const buf = new Uint8Array(analyser.fftSize);
        let smoothed = 0;
        const tick = () => {
          analyser.getByteTimeDomainData(buf);
          // Fast attack, slow release reads as "voice" rather than jitter.
          const target = levelFromSamples(buf);
          smoothed = target > smoothed ? target : smoothed * 0.85 + target * 0.15;
          setLevel(smoothed);
          raf = requestAnimationFrame(tick);
        };
        tick();
      } catch {
        if (!cancelled) setLevel(null);
      }
    })();

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      stream?.getTracks().forEach((t) => t.stop());
      void ctx?.close().catch(() => {});
      setLevel(null);
    };
  }, [active]);

  return level;
}
