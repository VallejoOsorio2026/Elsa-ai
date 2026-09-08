/**
 * Agregar conocimiento.
 *
 * La acción principal es la voz: en planta, con guantes y ruido, dictar es
 * más rápido y más fiel que escribir. El recorrido tiene tres pasos y ningún
 * atajo:
 *
 *  1. **Grabar** la nota de voz (y adjuntar apoyo, si lo hay).
 *  2. **Esto es lo que entendí**: revisar y corregir lo extraído, y
 *     responder la guía.
 *  3. **Enviar a revisión**, donde queda pendiente. No publicado.
 *
 * La transcripción va colapsada a propósito: lo que importa revisar son los
 * datos estructurados, no el párrafo. Y si es simulada, lo dice antes de que
 * nadie la lea.
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { createRecorderPanel } from '../recorder-panel.js';
import { announce, clear, el, formatBytes, notice } from '../ui.js';

let recorderPanel = null;
let draft = null;
let attachments = [];
let busy = false;
let lastError = null;

// El panel de la grabadora y el botón de continuar viven fuera del dibujado:
// el panel mantiene sus propios nodos y se repinta solo, así que recrearlo en
// cada `draw()` lo dejaría escribiendo en un nodo ya desprendido.
let submitBtn = null;

function base() {
  return `/contributions/${state.scope.domain}/${state.scope.asset}`;
}

function limits() {
  const capability = state.capability;
  return {
    maxAttachments: capability?.max_attachments ?? 5,
    maxBytes: capability?.max_attachment_bytes ?? 50 * 1024 * 1024,
    maxAudio: capability?.max_audio_seconds ?? 300,
  };
}

export function renderContribute(outlet) {
  const host = el('div', { class: 'contribute stack' });
  outlet.append(host);

  if (!state.capability?.can_contribute) {
    host.append(
      notice(
        'warn',
        'Tu cuenta puede consultar este equipo, pero no está habilitada para aportarle ' +
          'conocimiento. Consultar y aportar son capacidades distintas; un administrador ' +
          'de ELSA puede habilitarte.',
      ),
    );
    return;
  }

  const draw = () => paint(host, draw);
  draw();
}

function paint(host, draw) {
  clear(host);
  if (lastError) host.append(notice('error', lastError));

  if (draft && draft.state !== 'draft') {
    host.append(buildSubmitted(draw));
    return;
  }
  if (draft) {
    host.append(buildUnderstanding(draw));
    return;
  }
  host.append(buildCapture(draw));
}

// ---------------------------------------------------------------------
// Paso 1 · Grabar
// ---------------------------------------------------------------------

function buildCapture(draw) {
  const { maxAttachments, maxBytes, maxAudio } = limits();
  const section = el('div', { class: 'stack' });

  const title = el('input', {
    type: 'text',
    id: 'titulo',
    maxlength: 160,
    placeholder: 'Ej.: Ruido en el rodamiento de la prensa inferior',
  });

  if (!recorderPanel) {
    recorderPanel = createRecorderPanel({ maxSeconds: maxAudio, onChange: syncSubmit });
  }

  const files = el('div', { class: 'stack-sm' });
  const fileInput = el('input', {
    type: 'file',
    id: 'apoyo',
    multiple: true,
    class: 'visually-hidden',
    onChange: (event) => {
      const incoming = Array.from(event.target.files || []);
      event.target.value = '';
      for (const file of incoming) {
        if (attachments.length >= maxAttachments) {
          lastError = `No se pueden adjuntar más de ${maxAttachments} archivos.`;
          break;
        }
        const total = attachments.reduce((sum, item) => sum + item.size, 0);
        if (total + file.size > maxBytes) {
          lastError = `Los adjuntos no pueden sumar más de ${formatBytes(maxBytes)}.`;
          break;
        }
        attachments.push(file);
      }
      draw();
    },
  });
  files.append(
    el('label', { for: 'apoyo', class: 'btn btn-secondary' }, ['📎 Adjuntar apoyo']),
    fileInput,
    el(
      'ul',
      { class: 'chip-list' },
      attachments.map((file, index) =>
        el('li', { class: 'chip' }, [
          el('span', { text: `${file.name} · ${formatBytes(file.size)}` }),
          el('button', {
            class: 'chip-remove',
            type: 'button',
            'aria-label': `Quitar ${file.name}`,
            text: '✕',
            onClick: () => {
              attachments.splice(index, 1);
              draw();
            },
          }),
        ]),
      ),
    ),
    el('p', {
      class: 'muted',
      text: `Hasta ${maxAttachments} archivos y ${formatBytes(maxBytes)} en total. Fotos, mediciones, un plano marcado.`,
    }),
  );

  // No se puede continuar con una grabación a medias: el archivo todavía no
  // existe y el aporte saldría sin audio.
  submitBtn = el('button', {
    class: 'btn btn-primary',
    type: 'button',
    text: busy ? 'Guardando…' : 'Continuar',
    onClick: () => createDraft(title.value, draw),
  });
  syncSubmit();

  section.append(
    el('div', { class: 'card stack' }, [
      el('h2', { text: 'Cuéntalo con tu voz' }),
      el('p', {
        class: 'muted',
        text:
          'Habla como le explicarías a un compañero lo que viste. Después podrás revisar y ' +
          'corregir todo antes de enviarlo.',
      }),
      recorderPanel.element,
    ]),
    el('div', { class: 'card stack' }, [
      el('h2', { text: 'Ponle un título' }),
      el('label', { for: 'titulo', text: 'Título del aporte' }),
      title,
    ]),
    el('div', { class: 'card stack' }, [el('h2', { text: 'Evidencia de apoyo' }), files]),
    el('div', { class: 'actions' }, [submitBtn]),
  );
  return section;
}

/** Mantiene el botón de continuar acorde al estado de la grabadora. */
function syncSubmit() {
  if (!submitBtn) return;
  submitBtn.disabled = busy || Boolean(recorderPanel && recorderPanel.state.busy);
}

async function createDraft(title, draw) {
  const status = recorderPanel.state;
  if (!status.blob && attachments.length === 0 && !title.trim()) {
    lastError = 'Graba una nota de voz, o al menos ponle título, antes de continuar.';
    draw();
    return;
  }
  busy = true;
  lastError = null;
  draw();

  const form = new FormData();
  form.append('title', title.trim());
  form.append('audio_duration_seconds', String(Math.min(status.seconds, limits().maxAudio)));
  if (status.blob) {
    const extension = status.mimeType && status.mimeType.includes('ogg') ? 'ogg' : 'webm';
    form.append('audio', status.blob, `nota.${extension}`);
  }
  for (const file of attachments) form.append('attachments', file, file.name);

  try {
    draft = await api.request(base(), { method: 'POST', body: form });
    recorderPanel.dispose();
    recorderPanel = null;
    submitBtn = null;
    attachments = [];
    announce('Aporte creado. Revisa lo que entendí.');
  } catch (error) {
    lastError = error.message;
  } finally {
    busy = false;
    draw();
  }
}

// ---------------------------------------------------------------------
// Paso 2 · Esto es lo que entendí
// ---------------------------------------------------------------------

function buildUnderstanding(draw) {
  const section = el('div', { class: 'stack' });
  const edits = { normalizations: new Map(), checklist: new Map(), transcript: null };

  section.append(
    buildTranscript(edits),
    buildNormalizations(edits),
    buildChecklist(edits),
    buildSubmitBar(edits, draw),
  );
  return section;
}

function buildTranscript(edits) {
  const area = el('textarea', {
    id: 'transcripcion',
    rows: 8,
    'aria-label': 'Texto del aporte',
    onInput: (event) => {
      edits.transcript = event.target.value;
    },
  });
  area.value = draft.transcript_text;

  const simulated = draft.transcript_is_simulated;

  return el('details', { class: 'card transcript', open: simulated }, [
    el('summary', {}, [
      el('span', { text: 'Transcripción' }),
      simulated
        ? el('span', { class: 'tag tag-sim', text: 'Simulada' })
        : el('span', { class: 'tag tag-approved', text: 'Reconocida' }),
    ]),
    simulated
      ? notice(
          'warn',
          'Todavía no hay motor de voz a texto conectado, así que este texto NO proviene de ' +
            'tu audio. El audio sí se grabó y se guardó. Escribe aquí lo que dijiste: es lo ' +
            'que va a leer quien revise.',
          'Sin transcripción real',
        )
      : null,
    el('label', { for: 'transcripcion', text: 'Texto del aporte' }),
    area,
    el('p', {
      class: 'muted',
      text: 'Al guardar, ELSA vuelve a buscar en tu texto los componentes del BOM publicado.',
    }),
  ]);
}

function buildNormalizations(edits) {
  const list = el('div', { class: 'stack-sm' });

  for (const field of draft.normalizations) {
    const input = el('input', {
      type: 'text',
      id: `norm-${field.key}`,
      placeholder: field.detected ? '' : 'Sin detectar — escríbelo tú',
      onInput: (event) => edits.normalizations.set(field.key, event.target.value),
    });
    input.value = field.value || '';

    list.append(
      el('div', { class: 'norm-field' }, [
        el('div', { class: 'norm-head' }, [
          el('label', { for: `norm-${field.key}`, text: field.label }),
          field.matched_in_bom
            ? el('span', { class: 'tag tag-approved', text: 'Está en el BOM' })
            : null,
          field.edited ? el('span', { class: 'tag tag-draft', text: 'Corregido' }) : null,
        ]),
        input,
        field.detected && field.edited
          ? el('p', { class: 'muted', text: `ELSA había detectado: ${field.detected}` })
          : null,
      ]),
    );
  }

  return el('div', { class: 'card stack' }, [
    el('h2', { text: 'Esto es lo que entendí' }),
    el('p', {
      class: 'muted',
      text:
        'Coincidencias literales de tu texto con el BOM publicado. No hay interpretación: ' +
        'si un campo tiene valor, esa palabra está escrita arriba. Corrige lo que haga falta.',
    }),
    list,
  ]);
}

function buildChecklist(edits) {
  const list = el('div', { class: 'stack-sm' });
  const questions = state.capability?.checklist || [];
  const byKey = new Map(draft.checklist.map((item) => [item.key, item]));

  for (const question of questions) {
    const current = byKey.get(question.key);
    const area = el('textarea', {
      id: `check-${question.key}`,
      rows: 2,
      onInput: (event) => edits.checklist.set(question.key, event.target.value),
    });
    area.value = current?.answer || '';

    const pending = draft.missing_to_submit.includes(question.key);
    list.append(
      el('div', { class: `check-field${pending ? ' is-pending' : ''}` }, [
        el('label', { for: `check-${question.key}` }, [
          question.question,
          question.required ? el('span', { class: 'required', text: ' · obligatorio' }) : null,
        ]),
        el('p', { class: 'muted', text: question.hint }),
        area,
      ]),
    );
  }

  return el('div', { class: 'card stack' }, [
    el('h2', { text: 'Guía rápida' }),
    el('p', {
      class: 'muted',
      text: 'Lo que preguntaría un compañero con experiencia antes de dar por bueno el aporte.',
    }),
    list,
  ]);
}

function buildSubmitBar(edits, draw) {
  const messages = el('div', { class: 'stack-sm' });
  if (draft.missing_reasons.length > 0) {
    messages.append(
      notice('warn', draft.missing_reasons.join(' '), 'Falta para poder enviar'),
    );
  }

  return el('div', { class: 'card stack' }, [
    messages,
    el('div', { class: 'actions' }, [
      el('button', {
        class: 'btn btn-secondary',
        type: 'button',
        text: busy ? 'Guardando…' : 'Guardar cambios',
        disabled: busy,
        onClick: () => saveDraft(edits, draw),
      }),
      el('button', {
        class: 'btn btn-primary',
        type: 'button',
        text: 'Enviar a revisión',
        disabled: busy,
        onClick: () => saveDraft(edits, draw, { thenSubmit: true }),
      }),
    ]),
    el('p', {
      class: 'muted',
      text:
        'Al enviarlo queda pendiente de revisión. Un aporte pendiente no aparece en las ' +
        'consultas del equipo: nadie va a operar con él hasta que un revisor lo valide.',
    }),
  ]);
}

async function saveDraft(edits, draw, { thenSubmit = false } = {}) {
  busy = true;
  lastError = null;
  draw();

  const payload = {};
  if (edits.transcript !== null) payload.transcript_text = edits.transcript;
  if (edits.normalizations.size > 0) {
    payload.normalizations = Array.from(edits.normalizations, ([key, value]) => ({ key, value }));
  }
  if (edits.checklist.size > 0) {
    payload.checklist = Array.from(edits.checklist, ([key, answer]) => ({
      key,
      answer,
      checked: Boolean(answer && answer.trim()),
    }));
  }

  try {
    if (Object.keys(payload).length > 0) {
      draft = await api.request(`${base()}/${draft.id}`, { method: 'PATCH', body: payload });
    }
    if (thenSubmit) {
      draft = await api.request(`${base()}/${draft.id}/submit`, { method: 'POST' });
      announce('Aporte enviado a revisión.');
    } else {
      announce('Cambios guardados.');
    }
  } catch (error) {
    lastError = error.message;
  } finally {
    busy = false;
    draw();
  }
}

// ---------------------------------------------------------------------
// Paso 3 · Enviado
// ---------------------------------------------------------------------

function buildSubmitted(draw) {
  return el('div', { class: 'card stack' }, [
    notice(
      'success',
      'Tu aporte quedó pendiente de revisión. No forma parte del conocimiento del equipo ' +
        'hasta que un Revisor Técnico lo valide, y podrás seguirlo desde «Mis aportes».',
      'Enviado',
    ),
    el('h2', { text: draft.title }),
    el('p', { class: 'muted', text: `Estado: pendiente de revisión.` }),
    el('div', { class: 'actions' }, [
      el('button', {
        class: 'btn btn-primary',
        type: 'button',
        text: 'Hacer otro aporte',
        onClick: () => {
          draft = null;
          attachments = [];
          lastError = null;
          draw();
        },
      }),
      el('a', { class: 'btn btn-secondary', href: '#/mis-aportes', text: 'Ver mis aportes' }),
    ]),
  ]);
}

/**
 * Descarta el borrador en curso.
 *
 * Al cambiar de identidad, lo que había empezado a escribir otra persona deja
 * de ser suyo: seguir editándolo desde otra cuenta confundiría el rastro de
 * quién aportó qué.
 */
export function resetContribute() {
  disposeContribute();
  draft = null;
  attachments = [];
  busy = false;
  lastError = null;
}

/** Libera el micrófono al salir de la pantalla. */
export function disposeContribute() {
  if (recorderPanel) recorderPanel.dispose();
  recorderPanel = null;
  submitBtn = null;
}
