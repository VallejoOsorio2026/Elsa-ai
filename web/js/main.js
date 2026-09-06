/**
 * Arranque y armazón de ELSA.
 *
 * Enrutado por hash: sin servidor de rutas, sin compilación, sin
 * dependencias. Abrir el archivo desde el backend basta.
 *
 * El armazón solo dibuja lo que el backend ya autorizó: la barra lateral
 * se construye a partir de lo que /me y las capacidades devuelven. Esconder
 * un enlace no es una medida de seguridad —quien fuerce la URL choca con
 * FastAPI igual— sino de honestidad: no se ofrece lo que va a fallar.
 */

import { getToken, setToken } from './api.js';
import {
  loadAsset,
  loadCapability,
  loadContext,
  loadIdentity,
  signOut,
  state,
  subscribe,
} from './state.js';
import { announce, brandLogo, clear, el, initials, notice } from './ui.js';
import { renderLogin } from './screens/login.js';
import { renderChat } from './screens/chat.js';
import { disposeContribute, renderContribute } from './screens/contribute.js';
import { renderMine } from './screens/mine.js';
import { renderReview } from './screens/review.js';

const root = document.getElementById('root');

/** Pantallas registradas. `visible` decide si aparece en la navegación. */
const ROUTES = [
  {
    path: '/chat',
    label: 'Consultar',
    icon: '💬',
    title: 'Consultar el equipo',
    subtitle: 'Pregunta sobre el conocimiento publicado y revisa la evidencia de cada respuesta.',
    render: renderChat,
    visible: () => true,
  },
  {
    path: '/aportar',
    label: 'Agregar conocimiento',
    icon: '🎙',
    title: 'Agregar conocimiento',
    subtitle:
      'Cuéntalo con tu voz. Revisas lo que ELSA entendió y lo envías a revisión: nada se ' +
      'publica solo.',
    render: renderContribute,
    visible: (current) => Boolean(current.capability?.can_contribute),
  },
  {
    path: '/mis-aportes',
    label: 'Mis aportes',
    icon: '📋',
    title: 'Mis aportes',
    subtitle: 'Lo que has enviado sobre este equipo y en qué quedó cada aporte.',
    render: renderMine,
    visible: (current) => Boolean(current.capability?.can_contribute),
  },
  {
    path: '/revision',
    label: 'Centro de Revisión',
    icon: '✅',
    title: 'Centro de Revisión',
    subtitle:
      'Aportes esperando validación. Lo que apruebes queda marcado como válido; publicar ' +
      'sigue siendo otra decisión.',
    render: renderReview,
    visible: (current) => Boolean(current.capability?.can_review),
    badge: (current) => current.capability?.pending_count || 0,
  },
];

function currentPath() {
  const hash = window.location.hash.replace(/^#/, '');
  return hash || '/chat';
}

function routeFor(path) {
  return ROUTES.find((route) => route.path === path) || ROUTES[0];
}

export function navigate(path) {
  if (currentPath() === path) render();
  else window.location.hash = path;
}

// ---------------------------------------------------------------------
// Armazón
// ---------------------------------------------------------------------

let sidebarOpen = false;

function setSidebar(open) {
  sidebarOpen = open;
  render();
  if (open) {
    const first = document.querySelector('.sidebar .nav-link');
    if (first) first.focus();
  }
}

function buildSidebar(route) {
  const nav = el('ul', { class: 'nav' });
  for (const item of ROUTES) {
    if (!item.visible(state)) continue;
    const isCurrent = item.path === route.path;
    nav.append(
      el('li', {}, [
        el(
          'button',
          {
            class: 'nav-link',
            type: 'button',
            'aria-current': isCurrent ? 'page' : null,
            onClick: () => {
              setSidebar(false);
              navigate(item.path);
            },
          },
          [
            el('span', { class: 'nav-icon', 'aria-hidden': 'true', text: item.icon }),
            el('span', { text: item.label }),
            item.badge && item.badge(state)
              ? el('span', { class: 'nav-badge', text: String(item.badge(state)) })
              : null,
          ],
        ),
      ]),
    );
  }

  return el('aside', { class: `sidebar on-dark${sidebarOpen ? ' is-open' : ''}` }, [
    // El logotipo va en su propio contenedor: dentro de su área de
    // seguridad no entra ningún otro elemento (manual, p. 11).
    el('div', { class: 'sidebar-brand' }, [brandLogo({ width: 132, dark: true })]),
    // PAPELSA y ELSA permanecen separadas: no se funden en una pieza.
    el('div', { class: 'sidebar-product' }, [
      el('div', { class: 'product-name', text: 'ELSA' }),
      el('p', { text: 'Asistente de mantenimiento · Planta Molino Barbosa' }),
    ]),
    nav,
    el('div', { class: 'sidebar-footer' }, [
      el('div', { text: state.me?.display_name || 'Sesión activa' }),
      el(
        'button',
        {
          class: 'nav-link',
          type: 'button',
          onClick: () => {
            signOut();
            navigate('/chat');
            render();
          },
        },
        [el('span', { class: 'nav-icon', 'aria-hidden': 'true', text: '⏻' }), 'Cerrar sesión'],
      ),
    ]),
  ]);
}

function buildTopbar(route) {
  return el('header', { class: 'topbar' }, [
    el(
      'button',
      {
        class: 'icon-btn nav-toggle',
        type: 'button',
        'aria-label': sidebarOpen ? 'Cerrar el menú' : 'Abrir el menú',
        'aria-expanded': sidebarOpen ? 'true' : 'false',
        onClick: () => setSidebar(!sidebarOpen),
      },
      [el('span', { 'aria-hidden': 'true', text: sidebarOpen ? '✕' : '☰' })],
    ),
    el('h1', { class: 'topbar-title', text: route.title }),
    el('div', { class: 'topbar-spacer' }),
    el('div', { class: 'user-chip' }, [
      el('span', { class: 'avatar', 'aria-hidden': 'true', text: initials(state.me?.display_name) }),
      el('span', { text: state.me?.display_name || '' }),
    ]),
  ]);
}

/**
 * Contexto técnico. Siempre a la vista: quien consulta tiene que saber de
 * qué equipo se habla y con qué versión, sin preguntarlo.
 */
export function buildContextBar() {
  const scope = state.scope;
  const asset = state.asset;
  const item = (term, value) =>
    el('div', { class: 'context-item' }, [
      el('dt', { text: term }),
      el('dd', { text: value }),
    ]);

  // La API devuelve su etiqueta de fuente en inglés; la interfaz habla
  // español, así que el rótulo se compone aquí con los datos, no con texto
  // ajeno.
  let published = 'Sin BOM publicado';
  if (asset && asset.published) {
    published = `BOM publicado · ${asset.components} componentes en ${asset.subsystems} subsistemas`;
  }

  return el('dl', { class: 'context-bar' }, [
    item('Equipo', asset ? asset.name : scope?.asset || '—'),
    item('Dominio', scope?.domain || '—'),
    item('Conocimiento vigente', published),
  ]);
}

function buildDemoBanner() {
  if (!state.context?.demo_mode) return null;
  return el('div', { class: 'demo-banner' }, [
    el('span', { 'aria-hidden': 'true', text: '⚠' }),
    el('span', {
      text:
        'Ambiente de demostración. Las identidades y todos los datos técnicos son sintéticos: ' +
        'no proceden de la planta.',
    }),
  ]);
}

// ---------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------

export function render() {
  clear(root);

  if (!state.me) {
    root.append(renderLogin({ onSignedIn: boot }));
    return;
  }

  const route = routeFor(currentPath());
  const outlet = el('div', { class: 'content', id: 'contenido' });

  const shell = el('div', { class: 'shell' }, [
    buildSidebar(route),
    buildTopbar(route),
    el('main', { class: 'main' }, [outlet]),
  ]);

  const page = el('div', {}, [buildDemoBanner(), shell]);
  if (sidebarOpen) {
    page.append(el('div', { class: 'scrim', onClick: () => setSidebar(false) }));
  }
  root.append(page);

  if (!state.scope) {
    outlet.append(
      notice(
        'warn',
        'Tu cuenta está activa pero todavía no tiene ningún equipo asignado. ' +
          'Un administrador de ELSA debe concederte alcance antes de que puedas consultar nada.',
      ),
    );
    return;
  }

  outlet.append(
    el('div', { class: 'page-head' }, [el('p', { class: 'muted', text: route.subtitle })]),
    buildContextBar(),
  );
  route.render(outlet);
}

// ---------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------

async function boot() {
  try {
    if (!state.context) await loadContext();
  } catch {
    clear(root).append(
      el('div', { class: 'login-main' }, [
        el('div', { class: 'login-panel card' }, [
          notice('error', 'No se pudo contactar con el servidor de ELSA. Reintenta en un momento.'),
        ]),
      ]),
    );
    return;
  }

  if (getToken()) {
    let valid = false;
    try {
      valid = await loadIdentity();
    } catch {
      valid = false;
    }
    if (!valid) setToken(null);
    else {
      await loadAsset();
      await loadCapability();
    }
  }

  render();
  if (state.me) announce(`Sesión iniciada como ${state.me.display_name || 'usuario'}.`);
}

window.addEventListener('hashchange', () => {
  sidebarOpen = false;
  // El micrófono se libera al salir de la pantalla: dejarlo abierto
  // mantendría encendido el indicador de grabación del sistema.
  disposeContribute();
  render();
});
subscribe(() => render());

boot();
