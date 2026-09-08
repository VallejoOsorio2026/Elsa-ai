/**
 * Presentación compartida de un aporte.
 *
 * «Mis aportes» y el Centro de Revisión enseñan lo mismo desde dos lados, así
 * que la vista vive en un solo sitio: si mañana se añade un dato al aporte,
 * las dos pantallas lo muestran o ninguna lo hace.
 *
 * Una regla recorre todo el archivo: **el estado se dice con palabras**, no
 * solo con color. Confundir «pendiente» con «aprobado» en una planta no es
 * un detalle estético.
 */

import { fetchBlob } from './api.js';
import { state } from './state.js';
import { el, formatBytes, formatDate, formatSeconds, notice } from './ui.js';

/**
 * El principio que gobierna todo el Centro de Revisión.
 *
 * Se declara una sola vez y se repite literalmente allí donde alguien está a
 * punto de aprobar algo. Que un aporte quede validado y que el equipo tenga
 * ese conocimiento publicado son dos hechos distintos, y confundirlos es lo
 * que haría que alguien operara un equipo con algo que nadie ha publicado.
 */
export const PUBLISH_RULE =
  'Aprobar valida el aporte, pero no indica que sea publicado. La publicación es una ' +
  'decisión posterior e independiente.';

export const STATE_LABEL = {
  draft: 'Borrador',
  pending: 'Pendiente de revisión',
  approved: 'Aprobado',
  rejected: 'Rechazado',
};

const STATE_CLASS = {
  draft: 'tag-draft',
  pending: 'tag-pending',
  approved: 'tag-approved',
  rejected: 'tag-rejected',
};

export function stateTag(contribution) {
  return el('span', {
    class: `tag ${STATE_CLASS[contribution.state] || 'tag-draft'}`,
    text: STATE_LABEL[contribution.state] || contribution.state,
  });
}

/**
 * El camino de un aporte hasta ser conocimiento del equipo, en tres pasos.
 *
 * Dibujarlo evita la lectura de que aprobar «ya está»: el tercer paso queda
 * a la vista, sin alcanzar, con su nombre propio.
 */
export function knowledgeJourney(contribution) {
  const state = contribution.state;
  const validated = state === 'approved';
  const rejected = state === 'rejected';
  const received = state !== 'draft';

  const steps = [
    {
      label: 'Aporte recibido',
      detail: received ? 'Enviado a revisión' : 'Todavía en preparación',
      status: received ? 'done' : 'pending',
    },
    {
      label: 'Aporte validado',
      detail: rejected
        ? 'Rechazado por revisión'
        : validated
          ? 'Un revisor lo dio por válido'
          : 'Esperando a un revisor',
      status: rejected ? 'rejected' : validated ? 'done' : received ? 'current' : 'pending',
    },
    {
      label: 'Conocimiento publicado',
      detail: 'Decisión posterior e independiente. No ocurre al aprobar.',
      status: 'pending',
    },
  ];

  return el('div', { class: 'journey' }, [
    el('h3', { class: 'journey-title', text: 'Del aporte al conocimiento' }),
    el(
      'ol',
      { class: 'journey-steps' },
      steps.map((step, index) =>
        el('li', { class: `journey-step is-${step.status}` }, [
          el('span', { class: 'journey-index', 'aria-hidden': 'true', text: String(index + 1) }),
          el('span', { class: 'journey-body' }, [
            el('span', { class: 'journey-label', text: step.label }),
            el('span', { class: 'journey-detail', text: step.detail }),
          ]),
        ]),
      ),
    ),
    el('p', { class: 'journey-rule', text: PUBLISH_RULE }),
  ]);
}

/**
 * Reproductor de la nota de voz.
 *
 * El audio se pide con el token y se reproduce desde memoria: el endpoint
 * está protegido igual que el resto, así que un `src` directo devolvería 401.
 */
function buildAudio(contribution) {
  const scope = state.scope;
  const player = el('div', { class: 'stack-sm' }, [
    el('span', { class: 'spinner', role: 'status', 'aria-label': 'Cargando audio' }),
  ]);

  fetchBlob(
    `/contributions/${scope.domain}/${scope.asset}/${contribution.id}/audio`,
  )
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      const audio = el('audio', { controls: true, src: url, class: 'recorder-audio' });
      // El objeto se libera cuando el elemento deja de estar en el documento.
      audio.addEventListener('emptied', () => URL.revokeObjectURL(url), { once: true });
      player.replaceChildren(audio);
    })
    .catch((error) => {
      player.replaceChildren(
        notice('error', `No se pudo cargar la nota de voz: ${error.message}`),
      );
    });

  return el('div', { class: 'card stack-sm' }, [
    el('h3', { text: 'Nota de voz' }),
    el('p', {
      class: 'muted',
      text:
        `Duración ${formatSeconds(contribution.audio.duration_seconds)} · ` +
        `${formatBytes(contribution.audio.byte_size)}. Grabación real.`,
    }),
    contribution.audio_was_not_transcribed
      ? notice(
          'warn',
          'Nadie ha transcrito este audio: no hay motor de voz a texto conectado. El texto ' +
            'del aporte lo escribió una persona, así que no des por hecho que dice lo mismo ' +
            'que se oye aquí. Escúchalo antes de decidir.',
          'Sin transcribir',
        )
      : null,
    player,
  ]);
}


/** Tarjeta de listado. `onOpen` la hace pulsable. */
export function contributionCard(contribution, { onOpen } = {}) {
  const meta = [
    contribution.author_name ? `Por ${contribution.author_name}` : null,
    `Creado el ${formatDate(contribution.created_at)}`,
    contribution.audio ? `Voz ${formatSeconds(contribution.audio.duration_seconds)}` : null,
    contribution.attachments.length > 0
      ? `${contribution.attachments.length} adjunto(s)`
      : null,
  ]
    .filter(Boolean)
    .join(' · ');

  const body = [
    el('div', { class: 'card-head' }, [
      el('strong', { text: contribution.title }),
      stateTag(contribution),
    ]),
    el('p', { class: 'muted', text: meta }),
    contribution.transcript_is_simulated
      ? el('span', { class: 'tag tag-sim', text: 'Transcripción simulada' })
      : null,
    contribution.state === 'rejected' && contribution.decision_reason
      ? el('p', {}, [el('strong', { text: 'Motivo: ' }), contribution.decision_reason])
      : null,
  ];

  if (!onOpen) return el('div', { class: 'contribution-card' }, body);
  return el(
    'button',
    {
      class: 'contribution-card is-clickable',
      type: 'button',
      onClick: () => onOpen(contribution),
    },
    body,
  );
}

/**
 * Detalle completo. `actions` es el pie que aporta cada pantalla: en
 * revisión, los botones de decisión; en «Mis aportes», nada.
 */
export function contributionDetail(contribution, { actions = null } = {}) {

  return el('div', { class: 'stack' }, [
    el('div', { class: 'card stack' }, [
      el('div', { class: 'card-head' }, [
        el('h2', { text: contribution.title }),
        stateTag(contribution),
      ]),
      el('p', {
        class: 'muted',
        text: [
          contribution.author_name ? `Por ${contribution.author_name}` : null,
          `Creado el ${formatDate(contribution.created_at)}`,
          contribution.submitted_at ? `Enviado el ${formatDate(contribution.submitted_at)}` : null,
          contribution.decided_at ? `Decidido el ${formatDate(contribution.decided_at)}` : null,
        ]
          .filter(Boolean)
          .join(' · '),
      }),
      contribution.state === 'pending'
        ? notice(
            'info',
            'Recibido y esperando revisión. No forma parte del conocimiento publicado del ' +
              'equipo y no aparece en las consultas.',
            'Pendiente',
          )
        : null,
      contribution.state === 'approved'
        ? notice('success', `Validado por revisión. ${PUBLISH_RULE}`, 'Aprobado')
        : null,
      contribution.state === 'rejected'
        ? notice(
            'error',
            contribution.decision_reason || 'Sin motivo registrado.',
            'Rechazado',
          )
        : null,
    ]),

    el('div', { class: 'card' }, [knowledgeJourney(contribution)]),

    contribution.audio ? buildAudio(contribution) : null,

    el('details', { class: 'card transcript' }, [
      el('summary', {}, [
        el('span', { text: 'Transcripción' }),
        contribution.transcript_is_simulated
          ? el('span', { class: 'tag tag-sim', text: 'Simulada' })
          : el('span', { class: 'tag tag-approved', text: 'Reconocida' }),
      ]),
      contribution.transcript_is_simulated
        ? notice(
            'warn',
            'Este texto no se obtuvo reconociendo el audio: no hay motor de voz a texto ' +
              'conectado. Lo que leas aquí lo escribió una persona, no la máquina.',
            'Sin transcripción real',
          )
        : null,
      el('p', { class: 'transcript-text', text: contribution.transcript_text || '—' }),
    ]),

    el('div', { class: 'card stack-sm' }, [
      el('h3', { text: 'Esto es lo que entendí' }),
      el(
        'dl',
        { class: 'detail-list' },
        contribution.normalizations.flatMap((field) => [
          el('dt', {}, [
            field.label,
            field.edited ? el('span', { class: 'tag tag-draft', text: 'Corregido' }) : null,
          ]),
          el('dd', { text: field.value || '—' }),
        ]),
      ),
    ]),

    el('div', { class: 'card stack-sm' }, [
      el('h3', { text: 'Guía' }),
      el(
        'dl',
        { class: 'detail-list' },
        contribution.checklist.flatMap((item) => [
          el('dt', { text: item.question }),
          el('dd', { text: item.answer || 'Sin responder' }),
        ]),
      ),
    ]),

    contribution.attachments.length > 0
      ? el('div', { class: 'card stack-sm' }, [
          el('h3', { text: 'Evidencia adjunta' }),
          el(
            'ul',
            { class: 'chip-list' },
            contribution.attachments.map((file) =>
              el('li', {
                class: 'chip',
                text: `${file.filename} · ${formatBytes(file.byte_size)}`,
              }),
            ),
          ),
        ])
      : null,

    actions,
  ]);
}
