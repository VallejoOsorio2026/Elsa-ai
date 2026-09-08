/**
 * Ayudas mínimas de DOM. No es un framework: es lo justo para no repetir
 * `document.createElement` en cada pantalla.
 */

/** Crea un elemento. `props` admite class, text, html, attrs y on*. */
export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'dataset') {
      Object.assign(node.dataset, value);
    } else if (value === true) {
      node.setAttribute(key, '');
    } else {
      node.setAttribute(key, String(value));
    }
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/**
 * Añade hijos a un nodo descartando los que no existen.
 *
 * `Node.append(null)` no ignora el valor: inserta el texto «null». Los
 * bloques que solo aparecen a veces devuelven `null` a propósito, así que
 * pasan por aquí en vez de por `append` directamente.
 */
export function mount(node, ...children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child);
  }
  return node;
}

/**
 * Rellena un contenedor conservando el foco y el cursor de quien escribe.
 *
 * Volver a dibujar un bloque destruye sus nodos, y si dentro estaba el campo
 * enfocado el foco cae al `body`: la persona pierde el sitio a media frase y
 * tiene que volver a hacer clic. Aquí se anota qué elemento tenía el foco y
 * por dónde iba el cursor, y se restituyen sobre el nodo equivalente.
 *
 * Es la red de seguridad, no la primera línea: lo que de verdad evita el
 * problema es no redibujar el bloque donde se está escribiendo. Esta función
 * cubre los casos en que el redibujado es inevitable —una ficha que cambia
 * mientras se corrige, por ejemplo—.
 */
export function renderInto(node, build) {
  const active = document.activeElement;
  const keep =
    active && active !== node && node.contains(active) && active.id
      ? {
          id: active.id,
          start: active.selectionStart ?? null,
          end: active.selectionEnd ?? null,
        }
      : null;

  clear(node);
  build(node);

  if (keep) {
    const again = node.querySelector(`#${CSS.escape(keep.id)}`);
    if (again) {
      // `preventScroll` evita que restituir el foco dé un salto de página.
      again.focus({ preventScroll: true });
      if (keep.start !== null && typeof again.setSelectionRange === 'function') {
        try {
          again.setSelectionRange(keep.start, keep.end);
        } catch {
          /* El control no admite selección; basta con el foco. */
        }
      }
    }
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/**
 * Aviso con etiqueta de texto. El color nunca es el único portador del
 * significado (ELSA_UI_BRAND_RULES.md §5.2).
 */
export function notice(kind, message, label) {
  const labels = { info: 'Información', warn: 'Atención', error: 'Error', success: 'Listo' };
  return el('div', { class: `notice notice-${kind}` }, [
    el('span', { class: 'notice-label', text: label || labels[kind] || 'Aviso' }),
    el('span', { text: message }),
  ]);
}

/** Logotipo PAPELSA. `variant` elige el archivo, nunca un filtro CSS. */
export function brandLogo({ width = 120, dark = false, decorative = false } = {}) {
  const src = dark ? '/brand/papelsa-logotipo-blanco.svg' : '/brand/papelsa-logotipo-color.svg';
  const height = Math.round(width / 5.12);
  const wrapper = el('span', { class: 'brand-logo' });
  wrapper.style.setProperty('--logo-ancho', `${width}px`);
  wrapper.style.setProperty('--logo-alto', `${height}px`);
  wrapper.append(
    el('img', {
      src,
      width,
      height,
      alt: decorative ? '' : 'PAPELSA',
      'aria-hidden': decorative ? 'true' : null,
    }),
  );
  return wrapper;
}

/** Símbolo aislado. Solo para contextos compactos (§2.4 de las reglas). */
export function brandSymbol({ size = 32, decorative = true } = {}) {
  return el('img', {
    src: '/brand/papelsa-simbolo-color.svg',
    width: size,
    height: size,
    alt: decorative ? '' : 'PAPELSA',
    'aria-hidden': decorative ? 'true' : null,
  });
}

let liveTimer = null;

/** Anuncia un mensaje a lectores de pantalla sin robar el foco. */
export function announce(message) {
  const region = document.getElementById('live');
  if (!region) return;
  clearTimeout(liveTimer);
  region.textContent = '';
  liveTimer = setTimeout(() => {
    region.textContent = message;
  }, 60);
}

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} kB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatSeconds(total) {
  const seconds = Math.max(0, Math.round(total));
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
}

export function formatDate(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('es-CO', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function initials(name) {
  if (!name) return '··';
  return name
    .split(/\s+/)
    // Las preposiciones y artículos no identifican a nadie: «Ingeniero de
    // mantenimiento» debe dar IM, no ID.
    .filter((part) => part.length > 2 && /[a-zñáéíóú]/i.test(part[0]))
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('');
}
