/**
 * Compositor de texto y adjuntos.
 *
 * Los límites (número de archivos y tamaño total) los publica el backend en
 * /session/context y aquí solo se **avisan**: quien los aplica es FastAPI en
 * cada petición. Comprobarlos en el navegador evita que alguien grabe cinco
 * minutos y pierda el trabajo al enviar; no es una medida de seguridad.
 */

import { state } from './state.js';
import { announce, el, formatBytes, notice } from './ui.js';

function limits() {
  return (
    state.context?.limits || {
      max_attachments: 5,
      max_attachment_bytes: 50 * 1024 * 1024,
      max_audio_seconds: 300,
    }
  );
}

export function createComposer({
  placeholder = 'Escribe aquí…',
  submitLabel = 'Enviar',
  requireText = true,
  onSubmit,
} = {}) {
  const files = [];
  const feedback = el('div');
  const chips = el('ul', { class: 'chip-list' });

  const input = el('input', {
    type: 'file',
    multiple: true,
    class: 'visually-hidden',
    id: `files-${Math.random().toString(36).slice(2)}`,
    onChange: (event) => {
      addFiles(Array.from(event.target.files || []));
      event.target.value = '';
    },
  });

  const textarea = el('textarea', {
    placeholder,
    rows: 2,
    'aria-label': placeholder,
    onKeydown: (event) => {
      // Enter envía; Mayús+Enter hace salto de línea. En móvil no se
      // intercepta: el teclado virtual necesita su propio Enter.
      if (event.key === 'Enter' && !event.shiftKey && window.matchMedia('(min-width: 768px)').matches) {
        event.preventDefault();
        submit();
      }
    },
  });

  const submitBtn = el('button', {
    class: 'btn btn-primary',
    type: 'button',
    text: submitLabel,
    onClick: () => submit(),
  });

  function total() {
    return files.reduce((sum, file) => sum + file.size, 0);
  }

  function addFiles(incoming) {
    feedback.replaceChildren();
    const max = limits();
    for (const file of incoming) {
      if (files.length >= max.max_attachments) {
        feedback.replaceChildren(
          notice('warn', `No se pueden adjuntar más de ${max.max_attachments} archivos.`),
        );
        break;
      }
      if (total() + file.size > max.max_attachment_bytes) {
        feedback.replaceChildren(
          notice(
            'warn',
            `Los adjuntos no pueden sumar más de ${formatBytes(max.max_attachment_bytes)}. ` +
              `«${file.name}» no cabe.`,
          ),
        );
        break;
      }
      files.push(file);
    }
    renderChips();
  }

  function removeFile(index) {
    files.splice(index, 1);
    feedback.replaceChildren();
    renderChips();
  }

  function renderChips() {
    chips.replaceChildren();
    files.forEach((file, index) => {
      chips.append(
        el('li', { class: 'chip' }, [
          el('span', { text: `${file.name} · ${formatBytes(file.size)}` }),
          el('button', {
            class: 'chip-remove',
            type: 'button',
            'aria-label': `Quitar ${file.name}`,
            text: '✕',
            onClick: () => removeFile(index),
          }),
        ]),
      );
    });
    const max = limits();
    if (files.length > 0) {
      chips.append(
        el('li', {
          class: 'muted',
          text: `${files.length}/${max.max_attachments} · ${formatBytes(total())} de ${formatBytes(max.max_attachment_bytes)}`,
        }),
      );
    }
  }

  async function submit() {
    const text = textarea.value.trim();
    if (requireText && !text) {
      textarea.focus();
      return;
    }
    submitBtn.disabled = true;
    try {
      await onSubmit({ text, attachments: files.slice() });
      textarea.value = '';
      files.length = 0;
      renderChips();
      feedback.replaceChildren();
    } finally {
      submitBtn.disabled = false;
    }
  }

  const element = el('div', { class: 'composer' }, [
    feedback,
    chips,
    el('div', { class: 'composer-row' }, [
      el('label', { class: 'icon-btn', for: input.id, title: 'Adjuntar archivos' }, [
        el('span', { 'aria-hidden': 'true', text: '📎' }),
        el('span', { class: 'visually-hidden', text: 'Adjuntar archivos' }),
      ]),
      input,
      textarea,
      submitBtn,
    ]),
  ]);

  return {
    element,
    get files() {
      return files.slice();
    },
    get text() {
      return textarea.value.trim();
    },
    reset() {
      textarea.value = '';
      files.length = 0;
      renderChips();
    },
    focus() {
      textarea.focus();
      announce('Listo para escribir.');
    },
  };
}
