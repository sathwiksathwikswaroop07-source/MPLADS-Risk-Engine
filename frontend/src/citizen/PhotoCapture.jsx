import { useCallback, useEffect, useRef, useState } from "react";

// Longest edge of the captured frame. The server re-encodes and strips EXIF
// regardless -- this only avoids sending a needlessly large upload.
const MAX_EDGE = 1600;
const JPEG_QUALITY = 0.85;

// getUserMedia is only available on HTTPS or localhost. On a plain-http host
// the API is simply absent, which is worth saying out loud rather than
// letting the button fail silently.
function cameraSupported() {
  return typeof navigator !== "undefined"
    && navigator.mediaDevices
    && typeof navigator.mediaDevices.getUserMedia === "function";
}

function drawToBlob(video) {
  const scale = Math.min(1, MAX_EDGE / Math.max(video.videoWidth, video.videoHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  // Drawing through a canvas discards EXIF on the client too. The server
  // still re-encodes -- this is defence in depth, not the guarantee.
  return new Promise((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY));
}

/**
 * Capture one photograph, either from the live camera or from a file.
 *
 * Reports the chosen image upward as a Blob. The parent owns whether a
 * photograph is required -- here it is always optional.
 */
export default function PhotoCapture({ photo, onChange, disabled }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const [live, setLive] = useState(false);
  const [error, setError] = useState("");
  const [previewUrl, setPreviewUrl] = useState(null);

  // An object URL is a document-lifetime reference; without this the blob is
  // retained after the preview is replaced or the form unmounts.
  useEffect(() => {
    if (!photo) {
      setPreviewUrl(null);
      return undefined;
    }
    const url = URL.createObjectURL(photo);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  const stop = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    setLive(false);
  }, []);

  // A camera left running after the component goes away keeps the device's
  // recording indicator on, which on a civic page reads as a bug at best.
  useEffect(() => stop, [stop]);

  async function start() {
    setError("");
    if (!cameraSupported()) {
      setError("This browser cannot open a camera here. "
        + "Use “Choose a photo” instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
        audio: false,
      });
      streamRef.current = stream;
      setLive(true);
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
    } catch (err) {
      // Denying the camera is an ordinary choice, not a failure state.
      setError(err?.name === "NotAllowedError"
        ? "Camera permission was declined. You can still attach a photo from your device."
        : "No camera is available. You can still attach a photo from your device.");
      setLive(false);
    }
  }

  async function capture() {
    if (!videoRef.current) return;
    const blob = await drawToBlob(videoRef.current);
    stop();
    onChange(blob);
  }

  function pickFile(event) {
    const file = event.target.files?.[0];
    if (file) onChange(file);
  }

  return (
    <div className="photo-capture">
      {previewUrl ? (
        <div className="capture-preview">
          <img src={previewUrl} alt="The photograph you attached" />
          <button type="button" onClick={() => onChange(null)} disabled={disabled}>
            Remove photo
          </button>
        </div>
      ) : live ? (
        <div className="capture-live">
          {/* muted + playsInline: iOS refuses to autoplay otherwise. */}
          <video ref={videoRef} muted playsInline />
          <div className="capture-actions">
            <button type="button" onClick={capture}>Take photo</button>
            <button type="button" className="ghost" onClick={stop}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="capture-actions">
          <button type="button" onClick={start} disabled={disabled}>
            Open camera
          </button>
          {/* capture="environment" opens the camera directly on a phone and
              the file picker on a laptop, so this is both the fallback and
              the better path on desktop. */}
          <label className="capture-file">
            Choose a photo
            <input type="file" accept="image/jpeg,image/png"
                   capture="environment" onChange={pickFile}
                   disabled={disabled} />
          </label>
        </div>
      )}

      {error && <p className="capture-note">{error}</p>}
    </div>
  );
}
