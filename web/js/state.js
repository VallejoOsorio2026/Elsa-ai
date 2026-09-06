/**
 * Estado de la sesión en el navegador.
 *
 * Guarda lo que el backend ya dijo (contexto, identidad, permisos) para no
 * volver a preguntarlo en cada pantalla. **No decide nada**: los permisos
 * que hay aquí sirven para no ofrecer un botón que va a fallar, no para
 * autorizar. Quien autoriza es FastAPI, en cada petición.
 */

import { api, setToken } from './api.js';

export const state = {
  context: null,
  me: null,
  scope: null,
  asset: null,
  capability: null,
};

const listeners = new Set();

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function emit() {
  for (const listener of listeners) listener(state);
}

export async function loadContext() {
  state.context = await api.sessionContext();
  return state.context;
}

/** Carga identidad y alcance. Devuelve false si el token ya no sirve. */
export async function loadIdentity() {
  try {
    state.me = await api.me();
  } catch (error) {
    if (error.status === 401 || error.status === 403) {
      state.me = null;
      return false;
    }
    throw error;
  }
  state.scope = pickScope(state.me);
  return true;
}

/**
 * Alcance de trabajo del piloto.
 *
 * El piloto está limitado al equipo Tampella (CLAUDE.md §1), así que se
 * elige el primer alcance que lo cubra. Un alcance de dominio completo
 * (equipment nulo) también lo cubre.
 */
export function pickScope(me) {
  if (!me || !me.scopes || me.scopes.length === 0) return null;
  const preferred = me.scopes.find((scope) => scope.equipment === 'tampella');
  const domainWide = me.scopes.find((scope) => !scope.equipment);
  const chosen = preferred || domainWide || me.scopes[0];
  return {
    domain: chosen.domain,
    asset: chosen.equipment || 'tampella',
    domainWide: !chosen.equipment,
  };
}

/**
 * Carga el resumen del equipo del alcance. Alimenta el contexto técnico,
 * que se dibuja una vez en el armazón y no en cada pantalla.
 */
export async function loadAsset() {
  if (!state.scope) {
    state.asset = null;
    return null;
  }
  try {
    state.asset = await api.asset(state.scope.domain, state.scope.asset);
  } catch {
    // Un equipo inaccesible no debe impedir entrar: el contexto lo dirá.
    state.asset = null;
  }
  return state.asset;
}

/**
 * Capacidades de esta persona en el alcance: consultar, aportar, revisar.
 *
 * Se usa para no ofrecer lo que va a fallar. **No autoriza nada**: cada
 * endpoint vuelve a comprobarlo en el servidor.
 */
export async function loadCapability() {
  if (!state.scope) {
    state.capability = null;
    return null;
  }
  try {
    state.capability = await api.request(
      `/contributions/${state.scope.domain}/${state.scope.asset}/capability`,
    );
  } catch {
    state.capability = null;
  }
  return state.capability;
}

export function signOut() {
  setToken(null);
  state.me = null;
  state.scope = null;
  state.asset = null;
  state.capability = null;
}
