/**
 * Pantalla de acceso.
 *
 * Dos caminos según lo que diga el backend en /session/context:
 *
 * - **Demostración** (DEV con el proveedor de identidad fake): se ofrecen
 *   las personas del piloto. No es un atajo de seguridad; esos tokens son
 *   constantes del adaptador fake y la configuración lo prohíbe fuera de DEV.
 * - **Identidad real**: la sesión la emite el Supabase del Asistente de
 *   Materiales. ELSA no pide contraseña porque no es dueña de la identidad
 *   (CLAUDE.md §4). Mientras no exista el enlace de sesión, se admite pegar
 *   el token para poder probar contra un ambiente real.
 *
 * En ambos casos el token se comprueba contra /me antes de entrar: si el
 * backend lo rechaza, no se entra.
 */

import { api, setToken } from '../api.js';
import { state } from '../state.js';
import { brandLogo, el, notice } from '../ui.js';

export function renderLogin({ onSignedIn }) {
  const context = state.context;
  const panel = el('div', { class: 'login-panel stack' });
  const feedback = el('div');

  async function trySignIn(token, button) {
    if (!token) return;
    feedback.replaceChildren();
    if (button) button.disabled = true;
    setToken(token);
    try {
      await api.me();
      await onSignedIn();
      return;
    } catch (error) {
      setToken(null);
      const message =
        error.status === 403
          ? 'Esa identidad es válida, pero no tiene una cuenta activa en ELSA. ' +
            'Un administrador debe habilitarla.'
          : error.status === 401
            ? 'El token no es válido o ha caducado.'
            : error.message;
      feedback.replaceChildren(notice('error', message));
    } finally {
      if (button) button.disabled = false;
    }
  }

  panel.append(
    el('div', { class: 'card stack' }, [
      el('div', {}, [
        el('h1', { class: 'login-title' }, [
          'Entrar a ',
          el('span', { class: 'product-name', text: 'ELSA' }),
        ]),
        el('p', {
          class: 'muted',
          text: 'Asistente de mantenimiento de la Planta Molino Barbosa.',
        }),
      ]),
      feedback,
      buildIdentitySection(context, trySignIn),
    ]),
  );

  return el('div', { class: 'login' }, [
    el('header', { class: 'login-header' }, [brandLogo({ width: 132 })]),
    el('div', { class: 'login-main' }, [panel]),
  ]);
}

function buildIdentitySection(context, trySignIn) {
  const section = el('div', { class: 'stack' });

  if (context?.demo_mode && context.demo_identities.length > 0) {
    section.append(
      notice(
        'warn',
        'Ambiente de demostración: estas personas y sus datos son sintéticos. ' +
          'Elige con cuál quieres ver la aplicación.',
      ),
      el(
        'ul',
        { class: 'identity-list' },
        context.demo_identities.map((identity) =>
          el('li', {}, [
            el(
              'button',
              {
                class: 'identity-btn',
                type: 'button',
                onClick: (event) => trySignIn(identity.token, event.currentTarget),
              },
              [
                el('strong', { text: identity.label }),
                el('span', { class: 'muted', text: identity.description }),
              ],
            ),
          ]),
        ),
      ),
    );
    return section;
  }

  // Identidad real: la emite Materiales, no ELSA.
  const input = el('input', {
    type: 'password',
    id: 'token',
    autocomplete: 'off',
    placeholder: 'Token de sesión de Materiales',
  });
  const form = el(
    'form',
    {
      class: 'stack-sm',
      onSubmit: (event) => {
        event.preventDefault();
        trySignIn(input.value.trim(), form.querySelector('button'));
      },
    },
    [
      el('label', { for: 'token', text: 'Token de sesión' }),
      input,
      el('button', { class: 'btn btn-primary btn-block', type: 'submit', text: 'Entrar' }),
    ],
  );

  section.append(
    notice(
      'info',
      'La identidad la emite el Asistente de Materiales: ELSA verifica esa sesión y aplica ' +
        'sus propios permisos. Mientras el enlace de sesión no esté conectado, pega aquí el ' +
        'token para probar contra este ambiente.',
    ),
    form,
  );
  return section;
}
