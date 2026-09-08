/**
 * Panel de la grabadora, con nodos estables.
 *
 * **Por qué existe este archivo.** El cronómetro obliga a repintar cuatro
 * veces por segundo. Cuando ese repintado destruía y recreaba los botones, un
 * clic de ratón se perdía: el navegador solo emite `click` si `mousedown` y
 * `mouseup` caen sobre el **mismo** elemento, y una pulsación humana dura una
 * o dos décimas de segundo —tiempo de sobra para que el nodo desapareciera
 * debajo del cursor—. En pantalla táctil apenas se notaba porque el toque es
 * más corto. En un PC fallaba casi siempre, y se traducía en «hay que pulsar
 * dos veces».
 *
 * La regla que lo evita: **lo que cambia en cada tic es texto, no
 * estructura.** Los botones solo se reconstruyen cuando cambia el estado de
 * la grabadora, que es justo cuando dejan de ser los mismos botones.
 */

import { createRecorder, isSupported, unsupportedReason } from './audio.js';
import { clear, el, formatSeconds, notice } from './ui.js';

export function createRecorderPanel({ maxSeconds = 300, onChange } = {}) {
  const status = el('span', { class: 'recorder-status' });
  const time = el('span', { class: 'recorder-time' });
  const remaining = el('span', { class: 'recorder-remaining' });
  const dial = el('div', { class: 'recorder-dial' }, [status, time, remaining]);
  const actions = el('div', { class: 'recorder-actions' });
  const player = el('div', { class: 'recorder-player' });
  const problem = el('div');

  const element = el('div', { class: 'recorder' }, [problem, dial, actions, player]);

  let lastStatus = null;
  let lastError = null;
  let lastUrl = null;

  const recorder = createRecorder({
    maxSeconds,
    onChange: (state) => {
      paint(state);
      if (onChange) onChange(state);
    },
  });

  function paint(state) {
    // --- Lo que cambia en cada tic: solo texto ---
    time.textContent = formatSeconds(state.seconds);
    time.setAttribute('aria-label', `Duración ${formatSeconds(state.seconds)}`);

    const live = state.status === 'recording' || state.status === 'paused';
    const left = Math.max(0, maxSeconds - state.seconds);
    remaining.textContent = live
      ? `Quedan ${formatSeconds(left)}`
      : `Máximo ${formatSeconds(maxSeconds)}`;
    remaining.classList.toggle('is-warning', live && left <= 60);
    dial.classList.toggle('is-live', state.status === 'recording');

    // --- Lo que solo cambia al cambiar de estado: estructura ---
    if (state.status !== lastStatus) {
      lastStatus = state.status;
      paintStatusLabel(state);
      paintActions(state);
    }

    if (state.error !== lastError) {
      lastError = state.error;
      clear(problem);
      if (state.error) problem.append(notice('warn', state.error));
    }

    if (state.url !== lastUrl) {
      lastUrl = state.url;
      clear(player);
      if (state.url) {
        player.append(
          el('p', { class: 'muted', text: 'Escúchala antes de continuar:' }),
          el('audio', { controls: true, src: state.url, class: 'recorder-audio' }),
        );
      }
    }
  }

  function paintStatusLabel(state) {
    clear(status);
    if (state.busy) status.append(el('span', { class: 'spinner spinner-sm' }));
    status.append(el('span', { text: state.label }));
  }

  function paintActions(state) {
    clear(actions);
    // Mientras la grabadora cambia de estado no acepta órdenes: una segunda
    // pulsación no puede abrir otro micrófono ni duplicar la parada.
    const button = (props) =>
      el('button', { type: 'button', ...props, disabled: state.busy || props.disabled });

    if (state.status === 'idle' || state.status === 'starting') {
      actions.append(
        button({
          class: 'btn btn-primary btn-record',
          disabled: !isSupported(),
          text: state.status === 'starting' ? 'Iniciando…' : '⏺ Grabar',
          onClick: () => recorder.start(),
        }),
      );
    } else if (state.status === 'recording') {
      actions.append(
        button({ class: 'btn btn-secondary', text: '⏸ Pausar', onClick: () => recorder.pause() }),
        button({ class: 'btn btn-primary', text: '⏹ Terminar', onClick: () => recorder.stop() }),
      );
    } else if (state.status === 'paused') {
      actions.append(
        button({ class: 'btn btn-primary', text: '⏵ Reanudar', onClick: () => recorder.resume() }),
        button({ class: 'btn btn-secondary', text: '⏹ Terminar', onClick: () => recorder.stop() }),
      );
    } else if (state.status === 'stopping' || state.status === 'processing') {
      actions.append(button({ class: 'btn btn-secondary', text: state.label, disabled: true }));
    } else if (state.status === 'recorded') {
      actions.append(
        button({
          class: 'btn btn-secondary',
          text: '⏺ Grabar de nuevo',
          onClick: () => recorder.start(),
        }),
        button({ class: 'btn btn-danger', text: '🗑 Descartar', onClick: () => recorder.discard() }),
      );
    }
  }

  if (!isSupported()) {
    problem.append(notice('error', unsupportedReason() || 'No se puede grabar en este navegador.'));
    lastError = recorder.state.error;
  }
  paint(recorder.state);

  return {
    element,
    recorder,
    get state() {
      return recorder.state;
    },
    dispose() {
      recorder.dispose();
    },
  };
}
