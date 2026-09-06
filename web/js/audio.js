/**
 * Grabadora de notas de voz.
 *
 * La grabación es **real**: MediaRecorder sobre el micrófono del equipo. Lo
 * único simulado del recorrido es la transcripción, y de eso avisa el
 * backend, no este módulo.
 *
 * Requisitos que impone el navegador y conviene tener presentes:
 *
 * - `getUserMedia` solo existe en un contexto seguro: HTTPS, o localhost.
 *   Sobre http:// en una IP de red la API sencillamente no está, y la
 *   interfaz tiene que decirlo en vez de fallar en silencio.
 * - El permiso de micrófono lo concede la persona, no la aplicación. Si lo
 *   deniega, se le explica cómo revertirlo.
 *
 * El corte a los cinco minutos es del navegador **y** del servidor: aquí se
 * detiene la grabación sola, y allí se rechaza una duración mayor.
 */

import { announce } from './ui.js';

/** Avisos al usuario, en segundos restantes. */
export const WARNING_SECONDS = [60, 30, 10];

const PREFERRED_TYPES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/mp4',
];

function pickMimeType() {
  if (typeof MediaRecorder === 'undefined') return null;
  for (const type of PREFERRED_TYPES) {
    if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(type)) return type;
  }
  return '';
}

export function isSupported() {
  return Boolean(
    typeof MediaRecorder !== 'undefined' &&
      navigator.mediaDevices &&
      navigator.mediaDevices.getUserMedia,
  );
}

/** Por qué no se puede grabar aquí, en palabras que el usuario pueda usar. */
export function unsupportedReason() {
  if (!window.isSecureContext) {
    return (
      'El navegador solo permite usar el micrófono en conexiones seguras. ' +
      'Abre ELSA por HTTPS (o en localhost) para poder grabar.'
    );
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return 'Este navegador no permite grabar audio. Prueba con Chrome, Edge o Firefox actualizados.';
  }
  if (typeof MediaRecorder === 'undefined') {
    return 'Este navegador no admite MediaRecorder, necesario para grabar la nota de voz.';
  }
  return null;
}

/**
 * Crea una grabadora.
 *
 * @param {object} options
 * @param {number} options.maxSeconds  Corte automático.
 * @param {(state: object) => void} options.onChange  Cambió algo que se dibuja.
 * @param {(seconds: number) => void} [options.onWarning]  Quedan N segundos.
 */
export function createRecorder({ maxSeconds = 300, onChange, onWarning } = {}) {
  let recorder = null;
  let stream = null;
  let chunks = [];
  let ticker = null;

  // El tiempo se acumula por tramos: una pausa no debe contar, y restar
  // `Date.now()` contra el inicio la contaría.
  let accumulated = 0;
  let segmentStart = 0;
  let pending = new Set(WARNING_SECONDS);

  const state = {
    status: 'idle', // idle | recording | paused | recorded
    seconds: 0,
    maxSeconds,
    blob: null,
    url: null,
    mimeType: null,
    error: null,
  };

  function emit() {
    if (onChange) onChange(state);
  }

  function elapsed() {
    const live = state.status === 'recording' ? (Date.now() - segmentStart) / 1000 : 0;
    return accumulated + live;
  }

  function tick() {
    state.seconds = elapsed();
    const remaining = Math.ceil(maxSeconds - state.seconds);
    for (const threshold of Array.from(pending)) {
      if (remaining <= threshold) {
        pending.delete(threshold);
        if (onWarning) onWarning(threshold);
        announce(`Quedan ${threshold} segundos de grabación.`);
      }
    }
    if (state.seconds >= maxSeconds) {
      stop({ auto: true });
      return;
    }
    emit();
  }

  function startTicker() {
    stopTicker();
    ticker = setInterval(tick, 250);
  }

  function stopTicker() {
    if (ticker !== null) clearInterval(ticker);
    ticker = null;
  }

  function releaseStream() {
    if (stream) {
      for (const track of stream.getTracks()) track.stop();
      stream = null;
    }
  }

  async function start() {
    const reason = unsupportedReason();
    if (reason) {
      state.error = reason;
      emit();
      return false;
    }
    discard({ keepStatus: true });
    state.error = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      state.error =
        error && error.name === 'NotAllowedError'
          ? 'No diste permiso para usar el micrófono. Concédelo en el candado de la barra ' +
            'de direcciones y vuelve a intentarlo.'
          : 'No se pudo abrir el micrófono. Comprueba que hay uno conectado y disponible.';
      state.status = 'idle';
      emit();
      return false;
    }

    const mimeType = pickMimeType();
    chunks = [];
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    state.mimeType = recorder.mimeType || mimeType || 'audio/webm';

    recorder.addEventListener('dataavailable', (event) => {
      if (event.data && event.data.size > 0) chunks.push(event.data);
    });
    recorder.addEventListener('stop', () => {
      releaseStream();
      const blob = new Blob(chunks, { type: state.mimeType });
      state.blob = blob.size > 0 ? blob : null;
      if (state.url) URL.revokeObjectURL(state.url);
      state.url = state.blob ? URL.createObjectURL(state.blob) : null;
      state.status = state.blob ? 'recorded' : 'idle';
      state.seconds = Math.min(elapsed(), maxSeconds);
      emit();
    });

    accumulated = 0;
    segmentStart = Date.now();
    pending = new Set(WARNING_SECONDS);
    recorder.start();
    state.status = 'recording';
    state.seconds = 0;
    startTicker();
    announce('Grabando.');
    emit();
    return true;
  }

  function pause() {
    if (!recorder || state.status !== 'recording') return;
    recorder.pause();
    accumulated = elapsed();
    state.status = 'paused';
    stopTicker();
    announce('Grabación en pausa.');
    emit();
  }

  function resume() {
    if (!recorder || state.status !== 'paused') return;
    recorder.resume();
    segmentStart = Date.now();
    state.status = 'recording';
    startTicker();
    announce('Grabación reanudada.');
    emit();
  }

  function stop({ auto = false } = {}) {
    if (!recorder || (state.status !== 'recording' && state.status !== 'paused')) return;
    accumulated = elapsed();
    stopTicker();
    recorder.stop();
    recorder = null;
    if (auto) {
      announce('Se alcanzó el máximo de duración y la grabación se detuvo sola.');
      state.error = `Se alcanzó el máximo de ${Math.round(maxSeconds / 60)} minutos y la grabación se detuvo sola.`;
    }
  }

  /** Descarta lo grabado y libera el objeto de audio. */
  function discard({ keepStatus = false } = {}) {
    stopTicker();
    if (recorder && (state.status === 'recording' || state.status === 'paused')) {
      try {
        recorder.stop();
      } catch {
        /* ya estaba detenida */
      }
    }
    recorder = null;
    releaseStream();
    if (state.url) URL.revokeObjectURL(state.url);
    chunks = [];
    accumulated = 0;
    state.blob = null;
    state.url = null;
    state.seconds = 0;
    state.error = null;
    if (!keepStatus) {
      state.status = 'idle';
      announce('Grabación descartada.');
      emit();
    }
  }

  return {
    state,
    start,
    pause,
    resume,
    stop,
    discard,
    /** Libera todo. Se llama al salir de la pantalla. */
    dispose() {
      discard({ keepStatus: true });
    },
  };
}
