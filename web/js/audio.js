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

/**
 * Estados de la grabadora, en el orden en que ocurren.
 *
 * `starting`, `stopping` y `processing` existen porque el navegador tarda:
 * pedir el micrófono puede abrir un diálogo de permiso, y entre pedir la
 * parada y recibir el último trozo de audio pasa un tiempo que no controla
 * la aplicación. Sin un estado propio, esos huecos se ven como un botón que
 * no hace nada.
 */
export const STATUS_LABEL = {
  idle: 'Listo para grabar',
  starting: 'Iniciando grabación…',
  recording: 'Grabando',
  paused: 'En pausa',
  stopping: 'Finalizando…',
  processing: 'Procesando audio…',
  recorded: 'Grabación lista',
};

/** Estados en los que la grabadora está cambiando y no acepta órdenes. */
export const BUSY_STATUSES = new Set(['starting', 'stopping', 'processing']);

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
    status: 'idle',
    seconds: 0,
    maxSeconds,
    blob: null,
    url: null,
    mimeType: null,
    error: null,
    get label() {
      return STATUS_LABEL[this.status] || '';
    },
    get busy() {
      return BUSY_STATUSES.has(this.status);
    },
  };

  function emit() {
    if (onChange) onChange(state);
  }

  /** Cambia de estado y repinta en el acto: el usuario no espera al navegador. */
  function transition(status) {
    state.status = status;
    emit();
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
    // Una segunda pulsación mientras arranca no debe abrir un segundo
    // micrófono ni reiniciar el contador.
    if (state.busy || state.status === 'recording' || state.status === 'paused') return false;

    const reason = unsupportedReason();
    if (reason) {
      state.error = reason;
      emit();
      return false;
    }
    discard({ keepStatus: true });
    state.error = null;
    state.seconds = 0;
    // Se pinta ANTES de pedir el micrófono: `getUserMedia` puede abrir un
    // diálogo de permiso y tardar segundos.
    transition('starting');
    announce('Iniciando grabación.');
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      state.error =
        error && error.name === 'NotAllowedError'
          ? 'No diste permiso para usar el micrófono. Concédelo en el candado de la barra ' +
            'de direcciones y vuelve a intentarlo.'
          : 'No se pudo abrir el micrófono. Comprueba que hay uno conectado y disponible.';
      transition('idle');
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
      // El navegador ya entregó el último trozo: queda armar el archivo.
      transition('processing');
      releaseStream();

      // Se cede un fotograma antes de armar el Blob. No es un retardo
      // artificial: el trabajo se hace de verdad en este estado, pero si se
      // hiciera en la misma tarea que el cambio de estado el navegador no
      // llegaría a pintarlo y «Procesando audio…» no lo vería nadie. Con
      // cinco minutos de audio ese trabajo se nota.
      const finish = () => {
        const blob = new Blob(chunks, { type: state.mimeType });
        state.blob = blob.size > 0 ? blob : null;
        if (state.url) URL.revokeObjectURL(state.url);
        state.url = state.blob ? URL.createObjectURL(state.blob) : null;
        state.seconds = Math.min(elapsed(), maxSeconds);
        transition(state.blob ? 'recorded' : 'idle');
      };
      requestAnimationFrame(() => setTimeout(finish, 0));
    });

    accumulated = 0;
    segmentStart = Date.now();
    pending = new Set(WARNING_SECONDS);
    recorder.start();
    state.seconds = 0;
    startTicker();
    transition('recording');
    announce('Grabando.');
    return true;
  }

  function pause() {
    if (!recorder || state.status !== 'recording') return;
    recorder.pause();
    accumulated = elapsed();
    stopTicker();
    transition('paused');
    announce('Grabación en pausa.');
  }

  function resume() {
    if (!recorder || state.status !== 'paused') return;
    recorder.resume();
    segmentStart = Date.now();
    startTicker();
    transition('recording');
    announce('Grabación reanudada.');
  }

  function stop({ auto = false } = {}) {
    if (!recorder || (state.status !== 'recording' && state.status !== 'paused')) return;
    accumulated = elapsed();
    state.seconds = Math.min(accumulated, maxSeconds);
    stopTicker();
    // Se pinta antes de pedir la parada: entre `stop()` y el último trozo de
    // audio pasa un tiempo que depende del navegador.
    transition('stopping');
    announce('Finalizando grabación.');
    recorder.stop();
    recorder = null;
    if (auto) {
      announce('Se alcanzó el máximo de duración y la grabación se detuvo sola.');
      state.error = `Se alcanzó el máximo de ${Math.round(maxSeconds / 60)} minutos y la grabación se detuvo sola.`;
    }
  }

  /** Descarta lo grabado y libera el objeto de audio. */
  function discard({ keepStatus = false } = {}) {
    if (!keepStatus && state.busy) return;
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
      announce('Grabación descartada.');
      transition('idle');
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
