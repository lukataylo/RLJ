// In-cab voice playback. Speaks an answer using ElevenLabs audio (audio/mpeg
// bytes from POST /tts, played through expo-av's Audio.Sound) when expo-av is
// installed, and falls back to on-device TTS (expo-speech) otherwise — so a
// missing expo-av or a TTS failure still gets the driver a spoken answer.
//
// expo-av is listed in package.json but may be absent in an offline tree, so it
// is resolved through a guarded require() (typed as any) rather than a static
// import: that keeps the bundle from crashing when the module isn't present and
// keeps this file type-checking without the package installed.

import * as Speech from "expo-speech";

function loadExpoAv(): any | null {
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    return require("expo-av");
  } catch {
    return null;
  }
}

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/** Base64-encode raw bytes (RN lacks Buffer / reliable btoa for binary). */
function bytesToBase64(buf: ArrayBuffer): string {
  const b = new Uint8Array(buf);
  let out = "";
  for (let i = 0; i < b.length; i += 3) {
    const c0 = b[i];
    const c1 = i + 1 < b.length ? b[i + 1] : 0;
    const c2 = i + 2 < b.length ? b[i + 2] : 0;
    out += B64[c0 >> 2];
    out += B64[((c0 & 3) << 4) | (c1 >> 4)];
    out += i + 1 < b.length ? B64[((c1 & 15) << 2) | (c2 >> 6)] : "=";
    out += i + 2 < b.length ? B64[c2 & 63] : "=";
  }
  return out;
}

/**
 * Play ElevenLabs MPEG `bytes` if present and expo-av is available; otherwise
 * (or on any playback error) speak `fallbackText` with expo-speech. Resolves
 * once playback has started / the fallback has been spoken.
 */
export async function speakAnswer(
  bytes: ArrayBuffer | null,
  fallbackText: string,
): Promise<void> {
  const av = bytes && bytes.byteLength > 0 ? loadExpoAv() : null;
  if (bytes && av?.Audio?.Sound) {
    try {
      const uri = `data:audio/mpeg;base64,${bytesToBase64(bytes)}`;
      const { sound } = await av.Audio.Sound.createAsync(
        { uri },
        { shouldPlay: true },
      );
      sound.setOnPlaybackStatusUpdate((st: any) => {
        if (st?.didJustFinish) sound.unloadAsync().catch(() => {});
      });
      return;
    } catch {
      // fall through to on-device speech
    }
  }
  try {
    Speech.stop();
    Speech.speak(fallbackText, { language: "en-GB" });
  } catch {
    // nothing more we can do
  }
}
