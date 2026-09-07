/**
 * Chat piloto.
 *
 * La conversación vive en el navegador; el backend no guarda historial en
 * este bloque. Cada respuesta llega marcada con el motor que la produjo, y
 * la interfaz lo enseña: mientras no haya modelo de lenguaje, decir que lo
 * hay sería mentir sobre una herramienta de la que depende un mantenimiento.
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { announce, el, formatBytes, notice } from '../ui.js';
import { createComposer } from '../composer.js';

const messages = [];

export function renderChat(outlet) {
  const log = el('div', { class: 'chat-log', role: 'log', 'aria-live': 'polite' });
  const wrapper = el('div', { class: 'chat' }, [log]);

  const composer = createComposer({
    placeholder: 'Pregunta por un componente, un subsistema o un código de material…',
    submitLabel: 'Preguntar',
    onSubmit: async ({ text, attachments }) => {
      pushUser(text, attachments);
      renderLog(log);
      const pending = { role: 'pending' };
      messages.push(pending);
      renderLog(log);
      try {
        const answer = await api.request(
          `/assistant/${state.scope.domain}/${state.scope.asset}/ask`,
          {
            method: 'POST',
            body: {
              question: text,
              attachments: attachments.map((file) => ({
                filename: file.name,
                byte_size: file.size,
                content_type: file.type || null,
              })),
            },
          },
        );
        messages[messages.indexOf(pending)] = { role: 'assistant', answer };
        announce('Respuesta recibida.');
      } catch (error) {
        messages[messages.indexOf(pending)] = { role: 'error', error };
      }
      renderLog(log);
    },
  });

  wrapper.append(composer.element);
  outlet.append(wrapper);
  renderLog(log);
}

function pushUser(text, attachments) {
  messages.push({
    role: 'user',
    text,
    attachments: attachments.map((file) => ({ name: file.name, size: file.size })),
  });
}

function renderLog(log) {
  log.replaceChildren();
  if (messages.length === 0) {
    log.append(buildIntro());
    return;
  }
  for (const message of messages) log.append(buildMessage(message));
  log.scrollTop = log.scrollHeight;
}

function buildIntro() {
  const name = state.asset?.name || state.scope?.asset || 'el equipo';
  return el('div', { class: 'empty stack-sm' }, [
    el('p', { text: `Pregunta sobre ${name}.` }),
    el('p', {
      class: 'muted',
      text:
        'Este piloto busca literalmente los términos de tu pregunta en el conocimiento ' +
        'publicado. No interpreta, no resume y no completa lo que falte.',
    }),
  ]);
}

function buildMessage(message) {
  if (message.role === 'user') return buildUserMessage(message);
  if (message.role === 'pending') {
    return el('div', { class: 'msg msg-assistant' }, [
      el('span', { class: 'spinner', role: 'status', 'aria-label': 'Buscando' }),
    ]);
  }
  if (message.role === 'error') {
    return el('div', { class: 'msg msg-assistant' }, [
      notice('error', message.error.message),
    ]);
  }
  return buildAnswer(message.answer);
}

function buildUserMessage(message) {
  return el('div', { class: 'msg msg-user' }, [
    el('p', { text: message.text }),
    message.attachments.length > 0
      ? el(
          'ul',
          { class: 'chip-list' },
          message.attachments.map((file) =>
            el('li', { class: 'chip', text: `${file.name} · ${formatBytes(file.size)}` }),
          ),
        )
      : null,
  ]);
}

function buildAnswer(answer) {
  const body = el('div', { class: 'msg msg-assistant stack-sm' });

  // La procedencia va arriba, no en una nota al pie: es lo primero que
  // necesita saber quien va a actuar sobre un equipo.
  body.append(
    el('div', { class: 'answer-origin' }, [
      el('span', { class: 'tag tag-sim', text: 'Sin IA' }),
      el('span', { class: 'muted', text: answer.engine_label }),
    ]),
  );

  body.append(el('p', { text: answer.message }));

  if (answer.source) {
    body.append(el('p', { class: 'muted', text: `Fuente: ${answer.source}.` }));
  }

  if (answer.components.length > 0) {
    body.append(buildComponents(answer.components));
  }
  if (answer.failure_modes.length > 0) {
    body.append(buildFailureModes(answer.failure_modes));
  }
  if (answer.attachment_note) {
    body.append(notice('info', answer.attachment_note, 'Adjuntos'));
  }
  return body;
}

function matchLabel(row) {
  if (row.matched_code) return `código ${row.matched_code}`;
  return row.matched_terms.join(', ');
}

function buildComponents(rows) {
  return el('div', { class: 'evidence' }, [
    el('h3', { text: `Componentes del BOM publicado (${rows.length})` }),
    el('div', { class: 'table-scroll' }, [
      el('table', {}, [
        el('thead', {}, [
          el('tr', {}, [
            el('th', { text: 'Componente' }),
            el('th', { text: 'Subsistema' }),
            el('th', { text: 'Código' }),
            el('th', { text: 'Cant.' }),
            el('th', { text: 'Plano' }),
            el('th', { text: 'Coincidió por' }),
          ]),
        ]),
        el(
          'tbody',
          {},
          rows.map((row) =>
            el('tr', {}, [
              el('td', {}, [
                el('strong', { text: row.component || '—' }),
                row.description ? el('div', { class: 'muted', text: row.description }) : null,
              ]),
              el('td', { text: row.subsystem || '—' }),
              el('td', { class: 'mono', text: row.sap_code || '—' }),
              el('td', { text: row.quantity ? `${row.quantity} ${row.unit || ''}`.trim() : '—' }),
              el('td', { class: 'mono', text: row.drawing || '—' }),
              el('td', { class: 'muted', text: matchLabel(row) }),
            ]),
          ),
        ),
      ]),
    ]),
    el('p', {
      class: 'table-hint',
      text: 'La tabla se desplaza a los lados para ver el resto de columnas.',
    }),
  ]);
}

function buildFailureModes(rows) {
  return el('div', { class: 'evidence stack-sm' }, [
    el('h3', { text: `Modos de falla del AMEF publicado (${rows.length})` }),
    ...rows.map((row) =>
      el('div', { class: 'fmea-card' }, [
        el('div', { class: 'fmea-head' }, [
          el('strong', { text: row.failure_mode || '—' }),
          row.rpn !== null && row.rpn !== undefined
            ? el('span', { class: 'tag tag-draft', text: `NPR ${row.rpn}` })
            : null,
        ]),
        el('p', { class: 'muted', text: `${row.component || '—'} · ${row.subsystem || '—'}` }),
        row.effect ? el('p', {}, [el('strong', { text: 'Efecto: ' }), row.effect]) : null,
        row.cause ? el('p', {}, [el('strong', { text: 'Causa: ' }), row.cause]) : null,
        row.action ? el('p', {}, [el('strong', { text: 'Acción: ' }), row.action]) : null,
        el('p', { class: 'muted', text: `Coincidió por: ${matchLabel(row)}` }),
      ]),
    ),
  ]);
}
