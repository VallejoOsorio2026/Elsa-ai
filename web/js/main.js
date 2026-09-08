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
  activeDemoIdentity,
  loadAsset,
  loadCapability,
  loadContext,
  loadIdentity,
  signOut,
  state,
  subscribe,
  switchDemoIdentity,
} from './state.js';
import { announce, brandLogo, clear, el, initials, notice } from './ui.js';
import { renderLogin } from './screens/login.js';
import { renderChat } from './screens/chat.js';
import { disposeContribute, renderContribute, resetContribute } from './screens/contribute.js';
import { renderMine, resetMine } from './screens/mine.js';
import { renderReview, resetReview } from './screens/review.js';

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
      'Escríbelo o grábalo, revisa lo que ELSA entendió y envíalo a revisión: nada se ' +
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
    // La regla de gobierno no va aquí suelta: vive pegada a las pestañas,
    // dentro de la pantalla, donde se toma la decisión.
    subtitle: 'Aportes de este equipo esperando validación.',
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
  // El foco acompaña al cajón: al abrirlo va al primer enlace, y al cerrarlo
  // vuelve al botón que lo abrió, no al principio de la página.
  const target = open
    ? document.querySelector('.sidebar .nav-link')
    : document.querySelector('.nav-toggle');
  if (target) target.focus();
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
    buildIdentityChip(),
  ]);
}

/**
 * Quién está usando ELSA ahora mismo.
 *
 * En el ambiente de demostración es además un selector: enseñar los límites
 * entre consultar, aportar y revisar exige cambiar de persona varias veces, y
 * hacerlo cerrando sesión cada vez rompe el hilo de la demostración.
 *
 * **El selector solo existe en modo demostración** —DEV con identidades
 * sintéticas— y no relaja nada: cambia el token que se envía, igual que
 * volver a entrar. El backend sigue verificando identidad y permisos en cada
 * petición.
 */
function buildIdentityChip() {
  const name = state.me?.display_name || '';
  const avatar = el('span', {
    class: 'avatar',
    'aria-hidden': 'true',
    text: initials(name),
  });

  const active = activeDemoIdentity();
  if (!active) {
    return el('div', { class: 'user-chip' }, [
      avatar,
      el('span', { class: 'identity-current' }, [
        el('span', { class: 'identity-name', text: name }),
      ]),
    ]);
  }

  const menu = el('details', { class: 'identity-menu' }, [
    el('summary', { class: 'user-chip is-switch', title: 'Cambiar de identidad de demostración' }, [
      avatar,
      el('span', { class: 'identity-current' }, [
        el('span', { class: 'identity-name', text: active.label }),
        el('span', { class: 'identity-role', text: roleLabel(active.role) }),
      ]),
      el('span', { class: 'identity-caret', 'aria-hidden': 'true', text: '▾' }),
    ]),
    el('div', { class: 'identity-panel' }, [
      el('p', {
        class: 'identity-hint',
        text: 'Identidades sintéticas de la demostración. Cambiar aquí equivale a volver a entrar: los permisos los sigue decidiendo el servidor.',
      }),
      el(
        'ul',
        { class: 'identity-options' },
        state.context.demo_identities.map((identity) => {
          const current = identity.token === active.token;
          return el('li', {}, [
            el(
              'button',
              {
                class: 'identity-option',
                type: 'button',
                'aria-current': current ? 'true' : null,
                onClick: () => chooseIdentity(identity, menu),
              },
              [
                el('span', { class: 'identity-name', text: identity.label }),
                el('span', { class: 'identity-role', text: roleLabel(identity.role) }),
                current ? el('span', { class: 'tag tag-approved', text: 'Activa' }) : null,
              ],
            ),
          ]);
        }),
      ),
    ]),
  ]);
  return menu;
}

const ROLE_LABEL = {
  engineer: 'Consulta y aporta',
  reviewer: 'Consulta, aporta y revisa',
  admin: 'Administración del dominio',
};

function roleLabel(role) {
  return ROLE_LABEL[role] || role;
}

async function chooseIdentity(identity, menu) {
  menu.open = false;
  if (identity.token === activeDemoIdentity()?.token) return;

  // Cada pantalla guarda su propio estado —un borrador a medias, un aporte
  // abierto—. Al cambiar de persona deja de ser suyo, así que se descarta.
  resetContribute();
  resetMine();
  resetReview();

  if (await switchDemoIdentity(identity.token)) {
    announce(`Ahora estás como ${identity.label}.`);
    navigate('/chat');
    render();
  }
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

// El menú de identidad se cierra al pulsar fuera de él.
document.addEventListener('click', (event) => {
  for (const menu of document.querySelectorAll('.identity-menu[open]')) {
    if (!menu.contains(event.target)) menu.open = false;
  }
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  for (const menu of document.querySelectorAll('.identity-menu[open]')) menu.open = false;
});

window.addEventListener('hashchange', () => {
  sidebarOpen = false;
  // El micrófono se libera al salir de la pantalla: dejarlo abierto
  // mantendría encendido el indicador de grabación del sistema.
  disposeContribute();
  render();
});
subscribe(() => render());

boot();
