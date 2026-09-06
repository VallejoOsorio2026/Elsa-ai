/**
 * Mis aportes.
 *
 * Lo que esta persona ha enviado y en qué quedó. Deliberadamente simple: una
 * lista con el estado escrito y, al abrir uno, el detalle completo con el
 * motivo si fue rechazado. Sin filtros ni paginación mientras no haya
 * volumen que los justifique.
 */

import { api } from '../api.js';
import { state } from '../state.js';
import { clear, el, notice } from '../ui.js';
import { contributionCard, contributionDetail } from '../contribution-view.js';

let opened = null;

export function renderMine(outlet) {
  const host = el('div', { class: 'stack' });
  outlet.append(host);
  load(host);
}

async function load(host) {
  clear(host).append(el('div', { class: 'empty' }, [el('span', { class: 'spinner' })]));
  let items = [];
  try {
    items = await api.request(
      `/contributions/${state.scope.domain}/${state.scope.asset}/mine`,
    );
  } catch (error) {
    clear(host).append(notice('error', error.message));
    return;
  }
  paint(host, items);
}

function paint(host, items) {
  clear(host);

  if (opened) {
    host.append(
      el('button', {
        class: 'btn btn-secondary',
        type: 'button',
        text: '← Volver a la lista',
        onClick: () => {
          opened = null;
          paint(host, items);
        },
      }),
      contributionDetail(opened),
    );
    return;
  }

  if (items.length === 0) {
    host.append(
      el('div', { class: 'card empty stack-sm' }, [
        el('p', { text: 'Todavía no has enviado ningún aporte sobre este equipo.' }),
        el('a', {
          class: 'btn btn-primary',
          href: '#/aportar',
          text: 'Agregar conocimiento',
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
            paint(host, items);
          },
        }),
      ),
    ),
  );
}
