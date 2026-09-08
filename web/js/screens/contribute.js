/**
 * Agregar conocimiento.
 *
 * Una sola pantalla con bloques que aparecen cuando toca, no un asistente de
 * «Siguiente». El orden sigue el de la cabeza de quien aporta:
 *
 *   A Capturar → B Esencial → C Entender → D Contexto → E Revisar
 *
 * Tres decisiones de fondo:
 *
 * - **Escribir y grabar son equivalentes.** La pantalla abre en «Escribir»
 *   porque funciona en cualquier equipo y sin permisos; grabar está al lado,
 *   no debajo.
 * - **Lo derivado va después de lo que lo alimenta.** «Esto es lo que ELSA
 *   entendió» no aparece hasta que hay algo que entender, y solo enseña las
 *   fichas con contenido.
 * - **Escribir no se interrumpe.** Cada bloque tiene su propio contenedor y
 *   se rellena por separado. Al teclear se actualizan «lo que entendí» y el
 *   resumen; el campo donde está el cursor no se toca. Antes se redibujaba
 *   la pantalla entera y el foco caía al `body` a media frase.
 *
 * El orden del DOM es el orden de tabulación: A, B, C, D, E, y dentro de cada
 * bloque lo obligatorio antes que lo opcional. Ver
 * `docs/brand/ELSA_UI_BRAND_RULES.md`, «Navegación por teclado».
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { createRecorderPanel } from '../recorder-panel.js';
import {
  announce,
  clear,
  el,
  formatBytes,
  formatSeconds,
  mount,
  notice,
  renderInto,
} from '../ui.js';

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
let sections = null;
let actions = null;
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
// Montaje y actualización
// ---------------------------------------------------------------------

export function renderContribute(outlet) {
  const host = el('div', { class: 'contribute stack' });
  outlet.append(host);

  if (!state.capability?.can_contribute) {
    mount(
      host,
      notice(
        'warn',
        'Tu cuenta puede consultar este equipo, pero no está habilitada para aportarle ' +
          'conocimiento. Consultar y aportar son capacidades distintas; un administrador ' +
          'de ELSA puede habilitarte.',
      ),
    );
    return;
  }

  sections = null;
  redraw = () => paint(host);
  redraw();
}

function paint(host) {
  if (form.submitted) {
    sections = null;
    actions = null;
    clear(host);
    mount(host, buildSubmitted());
    return;
  }

  if (!sections || !host.contains(sections.capture)) {
    sections = {
      problem: el('div'),
      capture: el('section', { class: 'card stack block-capture' }),
      essential: el('section', { class: 'card stack block-essential' }),
      // El encabezado de «Esencial» tiene su propio nodo: el botón de
      // compactar aparece en cuanto se completan las dos preguntas, y eso
      // no puede obligar a rehacer los campos que se están escribiendo.
      essentialHead: el('div'),
      essentialBody: el('div', { class: 'stack' }),
      understanding: el('section', { class: 'card stack block-understanding' }),
      context: el('details', { class: 'card block-context' }),
      review: el('section', { class: 'card stack block-review' }),
    };
    clear(host);
    // El orden del DOM es el del flujo, y por tanto el de tabulación.
    mount(
      host,
      sections.problem,
      sections.capture,
      sections.essential,
      sections.understanding,
      sections.context,
      sections.review,
    );
  }

  renderProblem();
  renderCapture();
  renderEssential();
  renderUnderstanding();
  renderContext();
  renderReview();
}

/**
 * Lo que se actualiza al teclear.
 *
 * Nunca incluye el bloque donde está el cursor: ni «Capturar» ni «Esencial»
 * ni «Contexto» se vuelven a dibujar por escribir en ellos.
 */
function refreshDerived() {
  if (!sections) return;
  renderUnderstanding();
  renderSummary();
  syncActions();
}

function renderProblem() {
  renderInto(sections.problem, (node) =>
    mount(node, form.error ? notice('error', form.error) : null),
  );
}

// ---------------------------------------------------------------------
// A · Capturar
// ---------------------------------------------------------------------

function renderCapture() {
  renderInto(sections.capture, (node) => {
    const { maxAudio } = limits();
    const saved = Boolean(form.draft);

    // Botones de alternancia, no pestañas ARIA: son dos controles normales
    // que se alcanzan con Tab y se activan con Enter o Espacio, sin teclas
    // propias que nadie espera.
    const method = (value, label, hint) =>
      el(
        'button',
        {
          class: 'method-tab',
          type: 'button',
          'aria-pressed': form.method === value ? 'true' : 'false',
          disabled: saved,
          onClick: () => {
            form.method = value;
            redraw();
          },
        },
        [
          el('span', { class: 'method-label', text: label }),
          el('span', { class: 'muted', text: hint }),
        ],
      );

    const body = el('div', { class: 'method-body' });

    if (saved) {
      mount(
        body,
        notice(
          'info',
          'El borrador ya está guardado. El texto y las respuestas se siguen pudiendo ' +
            'corregir; la nota de voz y los archivos quedaron fijados al guardarlo.',
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
          schedulePreview();
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
        recorderPanel && recorderPanel.state.blob ? buildAudioChip() : null,
      );
    } else {
      if (!recorderPanel) {
        recorderPanel = createRecorderPanel({
          maxSeconds: maxAudio,
          onChange: (recorderState) => {
            syncActions();
            // Solo se redibuja al llegar a un estado terminal, nunca en cada
            // tic: mover los controles mientras alguien los pulsa es lo que
            // hacía perder los clics de ratón.
            if (recorderState.status === 'recorded' || recorderState.status === 'idle') redraw();
          },
        });
      }
      mount(
        body,
        recorderPanel.element,
        notice(
          'warn',
          'La nota de voz se guarda como evidencia, pero no se transcribe: todavía no hay ' +
            'motor de voz a texto conectado. Escribe también lo que dijiste, en «Escribir», ' +
            'para que quien revise pueda leerlo.',
          'El audio no se transcribe',
        ),
      );
    }

    mount(
      node,
      buildStepHead('A', 'Capturar', 'Escribe lo que observaste, grábalo, o las dos cosas.'),
      el('div', { class: 'method-tabs', role: 'group', 'aria-label': 'Cómo quieres aportarlo' }, [
        method('write', '✍ Escribir', 'Funciona en cualquier equipo'),
        method('record', '🎙 Grabar audio', 'Con guantes o con ruido'),
      ]),
      body,
    );
  });
}

function buildAudioChip() {
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
        redraw();
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

function renderEssential() {
  renderInto(sections.essential, (node) =>
    mount(node, sections.essentialHead, sections.essentialBody),
  );
  renderEssentialHead();
  renderEssentialBody();
}

function renderEssentialHead() {
  const done = essentialDone();
  const collapsed = done && !form.essentialOpen;
  sections.essential.classList.toggle('is-collapsed', collapsed);

  renderInto(sections.essentialHead, (node) =>
    mount(
      node,
      buildStepHead(
        'B',
        'Información esencial',
        'Sin esto, quien revise no puede decidir nada.',
        done
          ? el('button', {
              class: 'btn btn-secondary btn-small',
              type: 'button',
              // Un identificador estable permite devolverle el foco tras
              // redibujar, para quien navega con teclado.
              id: 'compactar-esencial',
              text: collapsed ? 'Editar' : 'Compactar',
              onClick: () => {
                form.essentialOpen = collapsed;
                renderEssentialHead();
                renderEssentialBody();
              },
            })
          : null,
      ),
    ),
  );
}

function renderEssentialBody() {
  const collapsed = essentialDone() && !form.essentialOpen;

  renderInto(sections.essentialBody, (node) => {
    if (collapsed) {
      mount(
        node,
        el('dl', { class: 'summary-list' }, [
          el('dt', { text: 'Qué observaste' }),
          el('dd', { text: answerOf('que_paso') }),
          el('dt', { text: 'En qué parte' }),
          el('dd', { text: answerOf('donde') }),
        ]),
      );
      return;
    }
    mount(
      node,
      ...questions()
        .filter((question) => ESSENTIAL_KEYS.includes(question.key))
        .map((question) => buildQuestion(question, { derived: true })),
    );
  });
}

/**
 * Una pregunta de la guía.
 *
 * `derived` marca las que alimentan «lo que entendí»: al escribir en ellas se
 * refrescan los bloques derivados, nunca el propio campo.
 */
function buildQuestion(question, { derived = false } = {}) {
  const area = el('textarea', {
    id: `q-${question.key}`,
    rows: 2,
    'aria-describedby': `hint-${question.key}`,
    onInput: (event) => {
      form.answers[question.key] = event.target.value;
      if (derived) schedulePreview();
      else {
        renderSummary();
        syncActions();
      }
    },
  });
  area.value = form.answers[question.key] || '';

  return el('div', { class: 'question' }, [
    el('label', { for: `q-${question.key}` }, [
      question.question,
      question.required ? el('span', { class: 'required', text: ' · obligatorio' }) : null,
    ]),
    el('p', { class: 'muted', id: `hint-${question.key}`, text: question.hint }),
    area,
  ]);
}

// ---------------------------------------------------------------------
// C · Esto es lo que ELSA entendió
// ---------------------------------------------------------------------

function schedulePreview() {
  syncActions();
  renderEssentialHead();
  renderSummary();
  clearTimeout(previewTimer);
  previewTimer = setTimeout(runPreview, PREVIEW_DELAY_MS);
}

async function runPreview() {
  const source = extractionSource();
  if (source.length < MIN_TEXT_FOR_PREVIEW) {
    form.understanding = null;
    refreshDerived();
    return;
  }
  form.previewing = true;
  refreshDerived();
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
    refreshDerived();
  }
}

function renderUnderstanding() {
  const enough = extractionSource().length >= MIN_TEXT_FOR_PREVIEW;
  sections.understanding.hidden = !enough;
  if (!enough) {
    clear(sections.understanding);
    return;
  }

  renderInto(sections.understanding, (node) => {
    const body = el('div', { class: 'stack-sm' });

    if (form.previewing && !form.understanding) {
      mount(
        body,
        el('p', { class: 'muted' }, [
          el('span', { class: 'spinner spinner-sm' }),
          ' Buscando en el conocimiento publicado…',
        ]),
      );
    } else if (!form.understanding) {
      mount(body, el('p', { class: 'muted', text: 'Todavía no he leído nada que reconocer.' }));
    } else {
      if (!form.understanding.has_findings) {
        mount(
          body,
          notice(
            'info',
            'No reconocí ningún componente ni código del BOM publicado en lo que llevas ' +
              'escrito. No es un problema: puede ser algo que todavía no está documentado. ' +
              'Quien revise lo leerá igual.',
            'Nada reconocido',
          ),
        );
      }
      // Solo fichas con contenido. Una caja vacía no informa de nada.
      const useful = FINDING_ORDER.map((key) =>
        form.understanding.normalizations.find((field) => field.key === key && valueOf(field)),
      ).filter(Boolean);
      for (const field of useful) mount(body, buildFinding(field));
    }

    mount(
      node,
      buildStepHead('C', 'Esto es lo que ELSA entendió', null),
      el('div', { class: 'answer-origin' }, [
        el('span', { class: 'tag tag-sim', text: 'Sin IA' }),
        el('span', {
          class: 'muted',
          text:
            'Coincidencias literales con el BOM publicado. Si aparece algo, esa palabra ' +
            'está escrita arriba.',
        }),
      ]),
      body,
    );
  });
}

function valueOf(field) {
  const edited = form.edits[field.key];
  return (edited !== undefined ? edited : field.value) || '';
}

function buildFinding(field) {
  const editing = form.edits[field.key] !== undefined;

  const value = editing
    ? el('input', {
        type: 'text',
        class: 'finding-input',
        id: `fix-${field.key}`,
        'aria-label': field.label,
        onInput: (event) => {
          form.edits[field.key] = event.target.value;
          renderSummary();
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
          renderUnderstanding();
          renderSummary();
        },
      }),
    ]),
    value,
  ]);
}

// ---------------------------------------------------------------------
// D · Añadir más contexto
// ---------------------------------------------------------------------

function renderContext() {
  renderInto(sections.context, (node) => {
    const optional = questions().filter((question) => !ESSENTIAL_KEYS.includes(question.key));
    const answered = optional.filter((question) => answerOf(question.key)).length;

    mount(
      node,
      el('summary', {}, [
        el('span', { class: 'step-badge', 'aria-hidden': 'true', text: 'D' }),
        el('span', { class: 'step-title', text: 'Añadir más contexto' }),
        answered > 0
          ? el('span', { class: 'tag tag-approved', text: `${answered} respondidas` })
          : el('span', { class: 'muted', text: 'Opcional' }),
      ]),
      el('div', { class: 'stack-sm' }, [
        el('p', {
          class: 'muted',
          text:
            'Nada de esto es obligatorio, pero es lo que un revisor pregunta cuando le falta ' +
            'contexto para decidir. Cuanto más completo, menos idas y venidas.',
        }),
        ...optional.map((question) => buildQuestion(question)),
        form.draft ? null : buildAttachments(),
      ]),
    );
  });
}

function buildAttachments() {
  const { maxAttachments, maxBytes } = limits();
  // El input queda oculto y **no** enfocable; quien abre el diálogo es un
  // botón de verdad, que se alcanza con Tab como cualquier otro.
  const input = el('input', {
    type: 'file',
    multiple: true,
    hidden: true,
    tabindex: '-1',
    'aria-hidden': 'true',
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
      renderProblem();
      renderContext();
      renderSummary();
    },
  });

  return el('div', { class: 'stack-sm' }, [
    el('button', {
      class: 'btn btn-secondary',
      type: 'button',
      id: 'adjuntar',
      text: '📎 Adjuntar evidencia',
      onClick: () => input.click(),
    }),
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
              renderContext();
              renderSummary();
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

function syncActions() {
  if (!actions) return;
  const ready = essentialDone() && hasCapture();
  const blocked = form.busy || Boolean(recorderPanel && recorderPanel.state.busy);
  actions.save.disabled = blocked || !hasCapture();
  actions.save.textContent = form.busy
    ? 'Guardando…'
    : form.draft
      ? 'Guardar cambios'
      : 'Guardar borrador';
  actions.send.disabled = blocked || !ready;
  renderMissing();
}

function renderReview() {
  renderInto(sections.review, (node) => {
    // Los botones se construyen una vez y solo se actualizan: rehacerlos en
    // cada tecleo repetiría el fallo del clic perdido de la grabadora.
    actions = {
      save: el('button', {
        class: 'btn btn-secondary',
        type: 'button',
        text: 'Guardar borrador',
        onClick: () => save({ submit: false }),
      }),
      send: el('button', {
        class: 'btn btn-primary',
        type: 'button',
        text: 'Enviar a revisión',
        onClick: () => save({ submit: true }),
      }),
      summary: el('div'),
      missing: el('div'),
    };

    mount(
      node,
      buildStepHead('E', 'Revisar y enviar', 'Esto es lo que verá quien revise.'),
      actions.summary,
      actions.missing,
      el('div', { class: 'actions' }, [actions.save, actions.send]),
      el('p', {
        class: 'muted',
        text:
          'Al enviarlo queda pendiente de revisión. Un aporte pendiente no aparece en las ' +
          'consultas del equipo: nadie va a operar con él hasta que un revisor lo valide.',
      }),
    );
    renderSummary();
    syncActions();
  });
}

function renderMissing() {
  if (!actions) return;
  const missing = [];
  if (!hasCapture()) missing.push('escribe o graba lo que observaste');
  for (const question of questions().filter((q) => ESSENTIAL_KEYS.includes(q.key))) {
    if (!answerOf(question.key)) missing.push(`responde «${question.question}»`);
  }
  renderInto(actions.missing, (node) => {
    mount(
      node,
      missing.length > 0 ? notice('warn', `Antes de enviar: ${missing.join('; ')}.`, 'Falta') : null,
    );
  });
}

function renderSummary() {
  if (!actions) return;
  renderInto(actions.summary, (node) => {
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
        if (key === 'equipo') continue;
        const field = form.understanding.normalizations.find((item) => item.key === key);
        if (field && valueOf(field)) push(field.label, valueOf(field));
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

    mount(
      node,
      rows.length === 0
        ? el('p', { class: 'muted', text: 'Todavía no hay nada que resumir.' })
        : el('dl', { class: 'summary-list' }, rows),
    );
  });
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

async function save({ submit }) {
  form.busy = true;
  form.error = null;
  renderProblem();
  syncActions();

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
    form.draft = await api.request(`${base()}/${form.draft.id}`, {
      method: 'PATCH',
      body: {
        transcript_text: form.text,
        checklist: checklistPayload(),
        ...(edits.length > 0 ? { normalizations: edits } : {}),
      },
    });

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
    redraw();
  }
}

function buildSubmitted() {
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
          const keep = redraw;
          resetContribute();
          redraw = keep;
          redraw();
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
  sections = null;
  actions = null;
}
