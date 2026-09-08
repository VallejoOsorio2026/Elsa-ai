/**
 * Agregar conocimiento.
 *
 * Una sola pantalla con bloques que aparecen cuando toca, no un asistente de
 * «Siguiente». El orden sigue el de la cabeza de quien aporta:
 *
 *   Capturar → Esencial → Entender → Completar → Revisar
 *
 * Dos decisiones de fondo:
 *
 * - **Escribir y grabar son equivalentes.** La pantalla abre en «Escribir»
 *   porque es lo que funciona en cualquier equipo y sin permisos; grabar está
 *   al lado, no debajo. Presentar el aporte como algo que solo se hace
 *   hablando dejaba fuera a quien está en una oficina o sin micrófono.
 * - **Lo derivado va después de lo que lo alimenta.** «Esto es lo que ELSA
 *   entendió» no aparece hasta que hay algo que entender, y solo enseña las
 *   fichas que tienen contenido. Abrir con siete cajas vacías convierte una
 *   respuesta en otro formulario.
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { createRecorderPanel } from '../recorder-panel.js';
import { announce, clear, el, formatBytes, formatSeconds, mount, notice } from '../ui.js';

const ESSENTIAL_KEYS = ['que_paso', 'donde'];
const PREVIEW_DELAY_MS = 500;
const MIN_TEXT_FOR_PREVIEW = 8;

/** Fichas de «lo que entendí», en el orden en que se leen. */
const FINDING_ORDER = [
  'equipo',
  'subsistemas',
  'componentes',
  'codigos_sap',
  'modos_falla',
  'codigos_desconocidos',
];

let form = newForm();
let recorderPanel = null;
let previewTimer = null;
let redraw = () => {};

function newForm() {
  return {
    method: 'write',
    text: '',
    answers: {},
    attachments: [],
    edits: {},
    understanding: null,
    previewing: false,
    essentialOpen: true,
    draft: null,
    submitted: null,
    busy: false,
    error: null,
  };
}

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

function questions() {
  return state.capability?.checklist || [];
}

function answerOf(key) {
  return (form.answers[key] || '').trim();
}

function essentialDone() {
  return ESSENTIAL_KEYS.every((key) => answerOf(key).length > 0);
}

function hasCapture() {
  return form.text.trim().length > 0 || Boolean(recorderPanel && recorderPanel.state.blob);
}

/** Material suficiente para que ELSA intente reconocer algo. */
function extractionSource() {
  return [form.text, answerOf('que_paso'), answerOf('donde')].join(' ').trim();
}

// ---------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------

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
  redraw = draw;
  draw();
}

function paint(host, draw) {
  clear(host);
  if (form.submitted) {
    host.append(buildSubmitted(draw));
    return;
  }
  mount(host, form.error ? notice('error', form.error) : null);

  mount(
    host,
    buildCapture(draw),
    buildEssential(draw),
    // Devuelve null mientras no haya nada que entender.
    buildUnderstanding(draw),
    buildMoreContext(draw),
    buildReview(draw),
  );
}

// ---------------------------------------------------------------------
// A · Capturar
// ---------------------------------------------------------------------

function buildCapture(draw) {
  const { maxAudio } = limits();
  const saved = Boolean(form.draft);

  const tab = (method, label, hint) =>
    el(
      'button',
      {
        class: 'method-tab',
        type: 'button',
        role: 'tab',
        'aria-selected': form.method === method ? 'true' : 'false',
        disabled: saved,
        onClick: () => {
          form.method = method;
          draw();
        },
      },
      [el('span', { class: 'method-label', text: label }), el('span', { class: 'muted', text: hint })],
    );

  const body = el('div', { class: 'method-body' });

  if (saved) {
    body.append(
      notice(
        'info',
        'El borrador ya está guardado. El texto y las respuestas se siguen pudiendo corregir; ' +
          'la nota de voz y los archivos quedaron fijados al guardarlo.',
        'Guardado',
      ),
      buildCaptureSummary(),
    );
  } else if (form.method === 'write') {
    const area = el('textarea', {
      id: 'relato',
      rows: 5,
      placeholder:
        'Ej.: El rodamiento del rodillo de la prensa inferior hace un ruido metálico al arrancar.',
      onInput: (event) => {
        form.text = event.target.value;
        schedulePreview(draw);
      },
    });
    area.value = form.text;
    mount(
      body,
      el('label', { for: 'relato', text: 'Cuéntalo con tus palabras' }),
      area,
      el('p', {
        class: 'muted',
        text: 'Como se lo explicarías a un compañero. Podrás corregirlo todo antes de enviar.',
      }),
      recorderPanel && recorderPanel.state.blob ? buildAudioChip(draw) : null,
    );
  } else {
    if (!recorderPanel) {
      recorderPanel = createRecorderPanel({
        maxSeconds: maxAudio,
        onChange: (recorderState) => {
          syncActions();
          // Solo se redibuja la pantalla cuando la grabadora llega a un
          // estado terminal, nunca en cada tic del cronómetro: mover los
          // controles mientras alguien los está pulsando es justo lo que
          // hacía perder los clics de ratón.
          if (recorderState.status === 'recorded' || recorderState.status === 'idle') redraw();
        },
      });
    }
    body.append(
      recorderPanel.element,
      notice(
        'warn',
        'La nota de voz se guarda como evidencia, pero no se transcribe: todavía no hay ' +
          'motor de voz a texto conectado. Escribe también lo que dijiste, en la pestaña ' +
          '«Escribir», para que quien revise pueda leerlo.',
        'El audio no se transcribe',
      ),
    );
  }

  return el('section', { class: 'card stack block-capture' }, [
    buildStepHead('A', 'Capturar', 'Escribe lo que observaste, grábalo, o las dos cosas.'),
    el('div', { class: 'method-tabs', role: 'tablist' }, [
      tab('write', '✍ Escribir', 'Funciona en cualquier equipo'),
      tab('record', '🎙 Grabar audio', 'Con guantes o con ruido'),
    ]),
    body,
  ]);
}

function buildAudioChip(draw) {
  return el('div', { class: 'audio-chip' }, [
    el('span', { 'aria-hidden': 'true', text: '🎙' }),
    el('span', {
      text: `Nota de voz de ${formatSeconds(recorderPanel.state.seconds)} adjunta como evidencia.`,
    }),
    el('button', {
      class: 'btn btn-secondary btn-small',
      type: 'button',
      text: 'Ver grabadora',
      onClick: () => {
        form.method = 'record';
        draw();
      },
    }),
  ]);
}

function buildCaptureSummary() {
  const items = [];
  if (form.text.trim()) items.push(el('p', { class: 'summary-text', text: form.text.trim() }));
  if (form.draft?.audio) {
    items.push(
      el('p', {
        class: 'muted',
        text: `Nota de voz de ${formatSeconds(form.draft.audio.duration_seconds)} · sin transcribir.`,
      }),
    );
  }
  if (form.draft?.attachments?.length) {
    items.push(
      el(
        'ul',
        { class: 'chip-list' },
        form.draft.attachments.map((file) =>
          el('li', { class: 'chip', text: `${file.filename} · ${formatBytes(file.byte_size)}` }),
        ),
      ),
    );
  }
  return el('div', { class: 'stack-sm' }, items);
}

// ---------------------------------------------------------------------
// B · Información esencial
// ---------------------------------------------------------------------

function buildEssential(draw) {
  const done = essentialDone();
  const collapsed = done && !form.essentialOpen;

  const head = buildStepHead(
    'B',
    'Información esencial',
    'Sin esto, quien revise no puede decidir nada.',
    done
      ? el('button', {
          class: 'btn btn-secondary btn-small',
          type: 'button',
          text: collapsed ? 'Editar' : 'Compactar',
          onClick: () => {
            form.essentialOpen = collapsed;
            draw();
          },
        })
      : null,
  );

  if (collapsed) {
    return el('section', { class: 'card stack block-essential is-collapsed' }, [
      head,
      el('dl', { class: 'summary-list' }, [
        el('dt', { text: 'Qué observaste' }),
        el('dd', { text: answerOf('que_paso') }),
        el('dt', { text: 'En qué parte' }),
        el('dd', { text: answerOf('donde') }),
      ]),
    ]);
  }

  const fields = questions()
    .filter((question) => ESSENTIAL_KEYS.includes(question.key))
    .map((question) => buildQuestion(question, draw, { onInput: () => schedulePreview(draw) }));

  return el('section', { class: 'card stack block-essential' }, [head, ...fields]);
}

function buildQuestion(question, draw, { onInput } = {}) {
  const area = el('textarea', {
    id: `q-${question.key}`,
    rows: 2,
    onInput: (event) => {
      form.answers[question.key] = event.target.value;
      syncActions();
      if (onInput) onInput();
    },
  });
  area.value = form.answers[question.key] || '';

  return el('div', { class: 'question' }, [
    el('label', { for: `q-${question.key}` }, [
      question.question,
      question.required ? el('span', { class: 'required', text: ' · obligatorio' }) : null,
    ]),
    el('p', { class: 'muted', text: question.hint }),
    area,
  ]);
}

// ---------------------------------------------------------------------
// C · Esto es lo que ELSA entendió
// ---------------------------------------------------------------------

function schedulePreview(draw) {
  syncActions();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => runPreview(draw), PREVIEW_DELAY_MS);
}

async function runPreview(draw) {
  const source = extractionSource();
  if (source.length < MIN_TEXT_FOR_PREVIEW) {
    form.understanding = null;
    draw();
    return;
  }
  form.previewing = true;
  draw();
  try {
    form.understanding = await api.request(`${base()}/understanding`, {
      method: 'POST',
      body: {
        text: form.text,
        checklist: Object.entries(form.answers).map(([key, answer]) => ({ key, answer })),
      },
    });
  } catch {
    // Que falle el reconocimiento no puede bloquear el aporte: se sigue
    // pudiendo escribir y enviar sin él.
    form.understanding = null;
  } finally {
    form.previewing = false;
    draw();
  }
}

function buildUnderstanding(draw) {
  if (extractionSource().length < MIN_TEXT_FOR_PREVIEW) return null;

  const body = el('div', { class: 'stack-sm' });

  if (form.previewing && !form.understanding) {
    body.append(
      el('p', { class: 'muted' }, [
        el('span', { class: 'spinner spinner-sm' }),
        ' Buscando en el conocimiento publicado…',
      ]),
    );
  } else if (!form.understanding) {
    body.append(el('p', { class: 'muted', text: 'Todavía no he leído nada que reconocer.' }));
  } else {
    const found = form.understanding.normalizations.filter(
      (field) => valueOf(field) && field.key !== 'resumen',
    );
    const useful = FINDING_ORDER.map((key) => found.find((field) => field.key === key)).filter(
      Boolean,
    );

    if (!form.understanding.has_findings) {
      body.append(
        notice(
          'info',
          'No reconocí ningún componente ni código del BOM publicado en lo que llevas escrito. ' +
            'No es un problema: puede ser algo que todavía no está documentado. Quien revise ' +
            'lo leerá igual.',
          'Nada reconocido',
        ),
      );
    }
    // Solo fichas con contenido. Una caja vacía no informa de nada.
    for (const field of useful) body.append(buildFinding(field, draw));
  }

  return el('section', { class: 'card stack block-understanding' }, [
    buildStepHead('C', 'Esto es lo que ELSA entendió', null),
    el('div', { class: 'answer-origin' }, [
      el('span', { class: 'tag tag-sim', text: 'Sin IA' }),
      el('span', {
        class: 'muted',
        text: 'Coincidencias literales con el BOM publicado. Si aparece algo, esa palabra está escrita arriba.',
      }),
    ]),
    body,
  ]);
}

function valueOf(field) {
  const edited = form.edits[field.key];
  return (edited !== undefined ? edited : field.value) || '';
}

function buildFinding(field, draw) {
  const editing = form.edits[field.key] !== undefined;

  const value = editing
    ? el('input', {
        type: 'text',
        class: 'finding-input',
        id: `fix-${field.key}`,
        'aria-label': field.label,
        onInput: (event) => {
          form.edits[field.key] = event.target.value;
        },
      })
    : el('span', { class: 'finding-value', text: valueOf(field) });
  if (editing) value.value = form.edits[field.key];

  return el('div', { class: `finding${field.matched_in_bom ? ' is-known' : ''}` }, [
    el('div', { class: 'finding-head' }, [
      el('span', { class: 'finding-label', text: field.label }),
      field.matched_in_bom
        ? el('span', { class: 'tag tag-approved', text: 'Está en el BOM' })
        : el('span', { class: 'tag tag-pending', text: 'No está en el BOM' }),
      el('button', {
        class: 'btn btn-secondary btn-small',
        type: 'button',
        text: editing ? 'Listo' : 'Corregir',
        onClick: () => {
          if (editing) delete form.edits[field.key];
          else form.edits[field.key] = field.value || '';
          draw();
        },
      }),
    ]),
    value,
  ]);
}

// ---------------------------------------------------------------------
// D · Añadir más contexto
// ---------------------------------------------------------------------

function buildMoreContext(draw) {
  const optional = questions().filter((question) => !ESSENTIAL_KEYS.includes(question.key));
  const answered = optional.filter((question) => answerOf(question.key)).length;

  const inner = el('div', { class: 'stack-sm' }, [
    el('p', {
      class: 'muted',
      text:
        'Nada de esto es obligatorio, pero es lo que un revisor pregunta cuando le falta ' +
        'contexto para decidir. Cuanto más completo, menos idas y venidas.',
    }),
    ...optional.map((question) => buildQuestion(question, draw)),
    form.draft ? null : buildAttachments(draw),
  ]);

  return el('details', { class: 'card block-context' }, [
    el('summary', {}, [
      el('span', { class: 'step-badge', 'aria-hidden': 'true', text: 'D' }),
      el('span', { class: 'step-title', text: 'Añadir más contexto' }),
      answered > 0
        ? el('span', { class: 'tag tag-approved', text: `${answered} respondidas` })
        : el('span', { class: 'muted', text: 'Opcional' }),
    ]),
    inner,
  ]);
}

function buildAttachments(draw) {
  const { maxAttachments, maxBytes } = limits();
  const input = el('input', {
    type: 'file',
    id: 'apoyo',
    multiple: true,
    class: 'visually-hidden',
    onChange: (event) => {
      const incoming = Array.from(event.target.files || []);
      event.target.value = '';
      for (const file of incoming) {
        if (form.attachments.length >= maxAttachments) {
          form.error = `No se pueden adjuntar más de ${maxAttachments} archivos.`;
          break;
        }
        const total = form.attachments.reduce((sum, item) => sum + item.size, 0);
        if (total + file.size > maxBytes) {
          form.error = `Los adjuntos no pueden sumar más de ${formatBytes(maxBytes)}.`;
          break;
        }
        form.attachments.push(file);
      }
      draw();
    },
  });

  return el('div', { class: 'stack-sm' }, [
    el('label', { for: 'apoyo', class: 'btn btn-secondary' }, ['📎 Adjuntar evidencia']),
    input,
    el(
      'ul',
      { class: 'chip-list' },
      form.attachments.map((file, index) =>
        el('li', { class: 'chip' }, [
          el('span', { text: `${file.name} · ${formatBytes(file.size)}` }),
          el('button', {
            class: 'chip-remove',
            type: 'button',
            'aria-label': `Quitar ${file.name}`,
            text: '✕',
            onClick: () => {
              form.attachments.splice(index, 1);
              draw();
            },
          }),
        ]),
      ),
    ),
    el('p', {
      class: 'muted',
      text: `Fotos, una medición, un plano marcado. Hasta ${maxAttachments} archivos y ${formatBytes(maxBytes)}.`,
    }),
  ]);
}

// ---------------------------------------------------------------------
// E · Revisar y enviar
// ---------------------------------------------------------------------

let saveBtn = null;
let sendBtn = null;

function syncActions() {
  const ready = essentialDone() && hasCapture();
  const blocked = form.busy || Boolean(recorderPanel && recorderPanel.state.busy);
  if (saveBtn) saveBtn.disabled = blocked || !hasCapture();
  if (sendBtn) sendBtn.disabled = blocked || !ready;
}

function buildReview(draw) {
  const missing = [];
  if (!hasCapture()) missing.push('escribe o graba lo que observaste');
  for (const question of questions().filter((q) => ESSENTIAL_KEYS.includes(q.key))) {
    if (!answerOf(question.key)) missing.push(`responde «${question.question}»`);
  }

  saveBtn = el('button', {
    class: 'btn btn-secondary',
    type: 'button',
    text: form.busy ? 'Guardando…' : form.draft ? 'Guardar cambios' : 'Guardar borrador',
    onClick: () => save(draw, { submit: false }),
  });
  sendBtn = el('button', {
    class: 'btn btn-primary',
    type: 'button',
    text: 'Enviar a revisión',
    onClick: () => save(draw, { submit: true }),
  });
  syncActions();

  return el('section', { class: 'card stack block-review' }, [
    buildStepHead('E', 'Revisar y enviar', 'Esto es lo que verá quien revise.'),
    buildSummary(),
    missing.length > 0
      ? notice('warn', `Antes de enviar: ${missing.join('; ')}.`, 'Falta')
      : null,
    el('div', { class: 'actions' }, [saveBtn, sendBtn]),
    el('p', {
      class: 'muted',
      text:
        'Al enviarlo queda pendiente de revisión. Un aporte pendiente no aparece en las ' +
        'consultas del equipo: nadie va a operar con él hasta que un revisor lo valide.',
    }),
  ]);
}

function buildSummary() {
  const rows = [];
  const push = (term, value) => {
    if (value) rows.push(el('dt', { text: term }), el('dd', { text: value }));
  };

  push('Equipo', state.asset?.name || state.scope?.asset);
  push('Qué observaste', answerOf('que_paso'));
  push('En qué parte', answerOf('donde'));
  if (form.text.trim()) push('Relato', form.text.trim());

  if (form.understanding) {
    for (const key of FINDING_ORDER) {
      const field = form.understanding.normalizations.find((item) => item.key === key);
      if (field && valueOf(field) && key !== 'equipo') push(field.label, valueOf(field));
    }
  }
  for (const question of questions().filter((q) => !ESSENTIAL_KEYS.includes(q.key))) {
    push(question.question, answerOf(question.key));
  }
  if (recorderPanel && recorderPanel.state.blob) {
    push('Nota de voz', `${formatSeconds(recorderPanel.state.seconds)} · sin transcribir`);
  }
  if (form.attachments.length > 0) {
    push('Adjuntos', form.attachments.map((file) => file.name).join(', '));
  }

  if (rows.length === 0) {
    return el('p', { class: 'muted', text: 'Todavía no hay nada que resumir.' });
  }
  return el('dl', { class: 'summary-list' }, rows);
}

// ---------------------------------------------------------------------
// Guardar y enviar
// ---------------------------------------------------------------------

function checklistPayload() {
  return questions().map((question) => ({
    key: question.key,
    answer: form.answers[question.key] || null,
    checked: Boolean(answerOf(question.key)),
  }));
}

async function save(draw, { submit }) {
  form.busy = true;
  form.error = null;
  draw();

  try {
    if (!form.draft) {
      const body = new FormData();
      body.append('title', '');
      body.append('text', form.text);
      body.append('checklist', JSON.stringify(checklistPayload()));
      const audio = recorderPanel && recorderPanel.state.blob;
      if (audio) {
        const extension = recorderPanel.state.mimeType.includes('ogg') ? 'ogg' : 'webm';
        body.append('audio', audio, `nota.${extension}`);
        body.append(
          'audio_duration_seconds',
          String(Math.min(recorderPanel.state.seconds, limits().maxAudio)),
        );
      }
      for (const file of form.attachments) body.append('attachments', file, file.name);
      form.draft = await api.request(base(), { method: 'POST', body });
    }

    const edits = Object.entries(form.edits).map(([key, value]) => ({ key, value }));
    if (edits.length > 0 || form.draft) {
      form.draft = await api.request(`${base()}/${form.draft.id}`, {
        method: 'PATCH',
        body: {
          transcript_text: form.text,
          checklist: checklistPayload(),
          ...(edits.length > 0 ? { normalizations: edits } : {}),
        },
      });
    }

    if (submit) {
      form.submitted = await api.request(`${base()}/${form.draft.id}/submit`, { method: 'POST' });
      announce('Aporte enviado a revisión.');
    } else {
      announce('Borrador guardado.');
    }
  } catch (error) {
    form.error = error.message;
  } finally {
    form.busy = false;
    draw();
  }
}

function buildSubmitted(draw) {
  return el('div', { class: 'card stack' }, [
    notice(
      'success',
      'Tu aporte quedó pendiente de revisión. No forma parte del conocimiento del equipo ' +
        'hasta que un Revisor Técnico lo valide, y podrás seguirlo desde «Mis aportes».',
      'Enviado',
    ),
    el('h2', { text: form.submitted.title }),
    el('div', { class: 'actions' }, [
      el('button', {
        class: 'btn btn-primary',
        type: 'button',
        text: 'Hacer otro aporte',
        onClick: () => {
          resetContribute();
          draw();
        },
      }),
      el('a', { class: 'btn btn-secondary', href: '#/mis-aportes', text: 'Ver mis aportes' }),
    ]),
  ]);
}

// ---------------------------------------------------------------------
// Ayudas y ciclo de vida
// ---------------------------------------------------------------------

function buildStepHead(badge, title, hint, action = null) {
  return el('div', { class: 'step-head' }, [
    el('span', { class: 'step-badge', 'aria-hidden': 'true', text: badge }),
    el('div', { class: 'step-body' }, [
      el('h2', { class: 'step-title', text: title }),
      hint ? el('p', { class: 'muted', text: hint }) : null,
    ]),
    action,
  ]);
}

/** Descarta el aporte en curso. */
export function resetContribute() {
  disposeContribute();
  form = newForm();
}

/** Libera el micrófono al salir de la pantalla. */
export function disposeContribute() {
  redraw = () => {};
  clearTimeout(previewTimer);
  previewTimer = null;
  if (recorderPanel) recorderPanel.dispose();
  recorderPanel = null;
  saveBtn = null;
  sendBtn = null;
}
