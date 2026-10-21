// hooks/useAudioControls.js
import { useState, useRef, useEffect, useCallback } from "react";

export function useAudioControls() {
  const [speaking, setSpeaking] = useState(false);
  const audioCtxRef = useRef(null);
  const audioSourceRef = useRef(null);
  const [isTTSPlaying, setIsTTSPlaying] = useState(false);
  const [speakingMessageId, setSpeakingMessageId] = useState(null);
  const [autoTTS, setAutoTTS] = useState(false);
  const [silent, setSilent] = useState(false);
  const autoTTSRef = useRef(autoTTS);
  const silentRef = useRef(silent);
  const audioResponseRef = useRef(null);

  useEffect(() => {
    autoTTSRef.current = autoTTS;
  }, [autoTTS]);

  useEffect(() => {
    silentRef.current = silent;
  }, [silent]);

  const playPing = useCallback(() => {
    const audio = new window.Audio("/ping.mp3");
    audio.play();
  }, []);

  const speak = useCallback(
    async (msg, onDone, overrides) => {
      const text = msg.text;


      setSpeaking(true);
      setSpeakingMessageId(msg.message_id);
      setIsTTSPlaying(true);

      if (audioSourceRef.current) {
        try {
          audioSourceRef.current.stop();
        } catch (e) {}
        audioSourceRef.current = null;
      }
      if (audioCtxRef.current) {
        try {
          audioCtxRef.current.close();
        } catch (e) {}
        audioCtxRef.current = null;
      }

      let cancelled = false;

      const body = overrides
        ? JSON.stringify({ text, overrides })
        : JSON.stringify({ text });

      try {
        // Do this immediately while a manual Play click may still count as
        // a browser user gesture. It is harmless for the existing ElevenLabs lane.
        const audioCtx = new window.AudioContext();
        audioCtxRef.current = audioCtx;

        const source = audioCtx.createBufferSource();
        audioSourceRef.current = source;

        const resumePromise = audioCtx.resume().catch((err) => {
          console.warn("[TTS] AudioContext resume failed:", err);
        });

        const response = await fetch("/api/tts/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
        });

        if (!response.ok) throw new Error("TTS request failed");

        console.log(
          "[TTS] response:",
          response.status,
          response.headers.get("content-type"),
        );

        const buffer = await response.arrayBuffer();

        if (cancelled) return;

        console.log("[TTS] downloaded bytes:", buffer.byteLength);
        console.log("[TTS] AudioContext state before decode:", audioCtx.state);

        await resumePromise;

        let decoded;
        try {
          // slice() avoids decodeAudioData detaching the original ArrayBuffer.
          decoded = await audioCtx.decodeAudioData(buffer.slice(0));
        } catch (err) {
          console.error("[TTS] decodeAudioData FAILED:", err);
          throw err;
        }

        if (audioCtxRef.current !== audioCtx || cancelled) return;

        console.log(
          "[TTS] decoded:",
          `${decoded.duration.toFixed(2)}s`,
          `${decoded.sampleRate}Hz`,
          `${decoded.numberOfChannels}ch`,
        );

        if (audioCtx.state !== "running") {
          console.warn("[TTS] context not running; retrying resume:", audioCtx.state);
          await audioCtx.resume();
        }

        source.buffer = decoded;
        source.connect(audioCtx.destination);

        console.log("[TTS] starting source; context:", audioCtx.state);

        source.start(0);
        source.onended = () => {
          if (audioSourceRef.current === source) {
            audioSourceRef.current = null;
          }
          if (audioCtxRef.current === audioCtx) {
            audioCtxRef.current = null;
          }
          setSpeaking(false);
          setIsTTSPlaying(false);
          if (onDone) onDone();
        };
      } catch (err) {
        console.error("[TTS] playback failed:", err);

        if (!cancelled) {
          setSpeaking(false);
          setIsTTSPlaying(false);
          if (onDone) onDone();
        }
      }

      return () => {
        cancelled = true;
      };
    },
    []
  );

  useEffect(() => {
    audioResponseRef.current = (incoming) => {
      if (autoTTSRef.current) {
        speak(incoming, () => setIsTTSPlaying(false));
      } else {
        if (silentRef.current === false) {
          playPing();
        }
      }
    };
  }, [speak, playPing]);

  function Equalizer({ isActive }) {
    if (!isActive) return null;
    return (
      <span className="ml-1 equalizer">
        <span className="equalizer-bar" />
        <span className="equalizer-bar" />
        <span className="equalizer-bar" />
      </span>
    );
  }

  return {
    speaking,
    setSpeaking,
    speak,
    isTTSPlaying,
    setIsTTSPlaying,
    audioSourceRef,
    audioCtxRef,
    Equalizer,
    speakingMessageId,
    setSpeakingMessageId,
    autoTTS,
    setAutoTTS,
    silent,
    setSilent,
    audioResponseRef,
  };
}