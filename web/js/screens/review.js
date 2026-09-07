/**
 * Centro de Revisión.
 *
 * Dos listas —lo pendiente y lo ya decidido— y el detalle completo del
 * aporte antes de decidir. Rechazar exige motivo: sin él, el autor no puede
 * corregir nada y el rechazo solo destruye trabajo.
 *
 * Lo que la interfaz no hace, a propósito: aprobar en lote. Cada aporte se
 * abre, se lee y se decide. Un botón de «aprobar todo» convierte la revisión
 * en un trámite, que es exactamente lo que esta pantalla existe para evitar.
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { announce, clear, el, formatDate, notice } from '../ui.js';
import { contributionCard, contributionDetail } from '../contribution-view.js';

let opened = null;
let tab = 'pending';
let busy = false;

function base() {
  return `/contributions/${state.scope.domain}/${state.scope.asset}`;
}

/** Olvida el aporte abierto y vuelve a la cola. */
export function resetReview() {
  opened = null;
  tab = 'pending';
}

export function renderReview(outlet) {
  opened = null;
  const host = el('div', { class: 'stack' });
  outlet.append(host);

  if (!state.capability?.can_review) {
    host.append(
      notice(
        'warn',
        'Tu cuenta no tiene capacidad de Revisor Técnico sobre este equipo. Consultar, ' +
          'aportar y revisar son capacidades distintas.',
      ),
    );
    return;
  }
  load(host);
}

async function load(host) {
  clear(host).append(el('div', { class: 'empty' }, [el('span', { class: 'spinner' })]));
  let pending = [];
  let decided = [];
  try {
    [pending, decided] = await Promise.all([
      api.request(`${base()}/pending`),
      api.request(`${base()}/decided`),
    ]);
  } catch (error) {
    clear(host).append(notice('error', error.message));
    return;
  }
  paint(host, { pending, decided });
}

function paint(host, lists) {
  clear(host);

  if (opened) {
    host.append(buildDetail(host, lists));
    return;
  }

  // Las pestañas y la regla que gobierna la decisión forman un bloque: el
  // límite entre validar y publicar se lee donde se decide, no en un
  // subtítulo suelto tres párrafos más arriba.
  host.append(
    el('div', { class: 'review-head' }, [
      el('div', { class: 'tabs', role: 'tablist' }, [
        buildTab('pending', `Pendientes (${lists.pending.length})`, host, lists),
        buildTab('decided', `Ya decididos (${lists.decided.length})`, host, lists),
      ]),
      el('p', { class: 'governance-note' }, [
        el('strong', { text: 'Aprobar no publica. ' }),
        'Marca el aporte como válido y lo deja listo; el conocimiento vigente del equipo ' +
          'solo cambia al publicar una versión.',
      ]),
    ]),
  );

  const items = tab === 'pending' ? lists.pending : lists.decided;
  if (items.length === 0) {
    host.append(
      el('div', { class: 'card empty' }, [
        el('p', {
          text:
            tab === 'pending'
              ? 'No hay aportes esperando revisión.'
              : 'Todavía no se ha decidido ningún aporte.',
        }),
      ]),
    );
    return;
  }

  host.append(
    el(
      'div',
      { class: 'card-list' },
      items.map((item) =>
        contributionCard(item, {
          onOpen: (contribution) => {
            opened = contribution;
            paint(host, lists);
          },
        }),
      ),
    ),
  );
}

function buildTab(key, label, host, lists) {
  return el('button', {
    class: 'tab',
    type: 'button',
    role: 'tab',
    'aria-selected': tab === key ? 'true' : 'false',
    text: label,
    onClick: () => {
      tab = key;
      paint(host, lists);
    },
  });
}

function buildDetail(host, lists) {
  const contribution = opened;
  const isOwn = contribution.author_id === state.me?.external_user_id;

  const feedback = el('div');
  const reason = el('textarea', {
    id: 'motivo',
    rows: 3,
    placeholder: 'Qué falta o por qué no procede. El autor lo va a leer para corregirlo.',
  });

  async function decide(approve) {
    if (!approve && !reason.value.trim()) {
      feedback.replaceChildren(
        notice('warn', 'Para rechazar hace falta un motivo: el autor tiene que poder corregir.'),
      );
      reason.focus();
      return;
    }
    busy = true;
    feedback.replaceChildren();
    try {
      await api.request(`${base()}/${contribution.id}/decision`, {
        method: 'POST',
        body: { approve, reason: reason.value.trim() || null },
      });
      announce(approve ? 'Aporte aprobado.' : 'Aporte rechazado.');
      opened = null;
      busy = false;
      await load(host);
      return;
    } catch (error) {
      feedback.replaceChildren(notice('error', error.message));
    } finally {
      busy = false;
    }
  }

  const isDecided = contribution.state !== 'pending';
  const decidedBy = contribution.decided_by_name || 'otra persona autorizada';
  const wasApproved = contribution.state === 'approved';

  const actions = isOwn
    ? notice(
        'info',
        'Este aporte es tuyo. La revisión existe para que lo mire otra persona, así que no ' +
          'puedes decidir sobre él.',
        'Sin decisión propia',
      )
    : el('div', { class: `card stack decision-block${isDecided ? ' is-revision' : ''}` }, [
        feedback,
        // Revisar lo ya decidido no es lo mismo que decidir por primera vez,
        // y la pantalla tiene que decirlo antes de que alguien pulse.
        el('div', { class: 'decision-head' }, [
          el('h3', { text: isDecided ? 'Revisar una decisión ya tomada' : 'Decidir' }),
          isDecided
            ? el('span', {
                class: `tag ${wasApproved ? 'tag-approved' : 'tag-rejected'}`,
                text: wasApproved ? 'Aprobado' : 'Rechazado',
              })
            : null,
        ]),
        isDecided
          ? notice(
              'warn',
              // La fecha localizada ya termina en punto («p. m.»), así que se
              // separa con un interpunto en vez de encadenar dos puntos.
              `Decidido por ${decidedBy}` +
                `${contribution.decided_at ? ` el ${formatDate(contribution.decided_at)}` : ''}` +
                ' · Revertir una decisión solo tiene sentido si aparece información nueva, y ' +
                'solo puede hacerlo alguien con capacidad de revisión sobre este mismo equipo ' +
                '—nunca quien escribió el aporte. Queda registrado quién la cambió y por qué.',
              'Decisión en firme',
            )
          : null,
        el('label', { for: 'motivo', text: 'Motivo (obligatorio para rechazar)' }),
        reason,
        el('div', { class: 'actions' }, [
          el('button', {
            class: 'btn btn-danger',
            type: 'button',
            text: isDecided && !wasApproved ? 'Ya rechazado' : 'Rechazar',
            disabled: busy || (isDecided && !wasApproved),
            onClick: () => decide(false),
          }),
          el('button', {
            class: 'btn btn-primary',
            type: 'button',
            text: isDecided && wasApproved ? 'Ya aprobado' : 'Aprobar',
            disabled: busy || (isDecided && wasApproved),
            onClick: () => decide(true),
          }),
        ]),
        el('p', {
          class: 'muted',
          text:
            'Aprobar marca el aporte como válido. No lo publica: el conocimiento vigente ' +
            'del equipo solo cambia al publicar una versión.',
        }),
      ]);

  return el('div', { class: 'stack' }, [
    el('button', {
      class: 'btn btn-secondary',
      type: 'button',
      text: '← Volver a la cola',
      onClick: () => {
        opened = null;
        paint(host, lists);
      },
    }),
    contributionDetail(contribution, { actions }),
  ]);
}
