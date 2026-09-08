/**
 * Estado de la sesión en el navegador.
 *
 * Guarda lo que el backend ya dijo (contexto, identidad, permisos) para no
 * volver a preguntarlo en cada pantalla. **No decide nada**: los permisos
 * que hay aquí sirven para no ofrecer un botón que va a fallar, no para
 * autorizar. Quien autoriza es FastAPI, en cada petición.
 */

import { api, getToken, setToken } from './api.js';

export const state = {
  context: null,
  me: null,
  /** Equipos que el backend autoriza a esta persona. */
  assets: [],
  scope: null,
  asset: null,
  capability: null,
};

/** Dónde se recuerda el último equipo elegido, por persona. */
const SCOPE_KEY = 'elsa.scope';

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
  return true;
}

/**
 * Equipos autorizados, según el backend.
 *
 * El alcance **no se supone**: se pregunta. La interfaz no sabe qué equipos
 * existen ni cuáles puede ver esta persona hasta que el servidor se lo dice,
 * y ese cruce lo hace el modelo de permisos, no un valor escrito en el
 * cliente.
 */
export async function loadAssets() {
  try {
    state.assets = await api.request('/assets');
  } catch {
    state.assets = [];
  }
  return state.assets;
}

function rememberedCode() {
  if (!state.me) return null;
  try {
    return sessionStorage.getItem(`${SCOPE_KEY}.${state.me.external_user_id}`);
  } catch {
    return null;
  }
}

function remember(code) {
  if (!state.me) return;
  try {
    sessionStorage.setItem(`${SCOPE_KEY}.${state.me.external_user_id}`, code);
  } catch {
    /* Almacenamiento bloqueado: la elección dura lo que dure la página. */
  }
}

/**
 * Fija el alcance de trabajo a partir de lo que el backend autorizó.
 *
 * - Ningún equipo: no hay alcance, y la interfaz lo dice.
 * - Uno solo: se elige solo, porque no hay nada que preguntar.
 * - Varios: se recupera el último elegido si sigue autorizado; si no, hay
 *   que escoger. Recordar una elección **no** la autoriza: siempre se valida
 *   contra la lista que acaba de dar el servidor.
 */
export function resolveScope() {
  const assets = state.assets;
  if (assets.length === 0) {
    state.scope = null;
    return null;
  }
  if (assets.length === 1) return applyScope(assets[0]);

  const remembered = assets.find((asset) => asset.code === rememberedCode());
  if (remembered) return applyScope(remembered);

  state.scope = null;
  return null;
}

function applyScope(asset) {
  state.scope = { domain: asset.domain, asset: asset.code, name: asset.name };
  return state.scope;
}

/** Cambia de equipo entre los autorizados y recarga su contexto. */
export async function selectAsset(code) {
  const asset = state.assets.find((item) => item.code === code);
  if (!asset) return false;
  applyScope(asset);
  remember(asset.code);
  await loadAsset();
  await loadCapability();
  return true;
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

/**
 * Identidad de demostración activa, o `null` fuera del modo demostración.
 *
 * Se resuelve comparando el token guardado con los que publica el backend:
 * es una correspondencia exacta, no una suposición a partir del nombre.
 */
export function activeDemoIdentity() {
  if (!state.context?.demo_mode) return null;
  const token = getToken();
  return state.context.demo_identities.find((identity) => identity.token === token) || null;
}

/**
 * Cambia la identidad de demostración.
 *
 * Es exactamente lo mismo que cerrar sesión y volver a entrar como otra
 * persona: se guarda otro token y se vuelve a preguntar al backend quién es
 * y qué puede. **No hay atajo de permisos**: cada petición posterior recorre
 * la misma cadena de confianza, y el servidor sigue decidiendo.
 */
export async function switchDemoIdentity(token) {
  if (!state.context?.demo_mode) return false;
  const known = state.context.demo_identities.some((identity) => identity.token === token);
  if (!known) return false;

  setToken(token);
  state.me = null;
  state.assets = [];
  state.scope = null;
  state.asset = null;
  state.capability = null;

  if (!(await loadIdentity())) {
    setToken(null);
    return false;
  }
  // Otra persona, otros permisos: los equipos se vuelven a preguntar.
  await loadAssets();
  resolveScope();
  if (state.scope) {
    await loadAsset();
    await loadCapability();
  }
  return true;
}

export function signOut() {
  setToken(null);
  state.me = null;
  state.assets = [];
  state.scope = null;
  state.asset = null;
  state.capability = null;
}
