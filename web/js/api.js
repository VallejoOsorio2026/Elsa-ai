/**
 * Cliente de la API de ELSA.
 *
 * Un solo lugar habla con el backend. Traduce el formato de error estándar
 * del proyecto ({error: {code, message, request_id}}) a una excepción con
 * esos mismos campos, para que las pantallas no tengan que interpretar
 * cuerpos crudos.
 *
 * El token vive en sessionStorage, no en localStorage: se pierde al cerrar
 * la pestaña, que es lo que se quiere en un equipo compartido de planta.
 */

const BASE = '/api/v1';
const TOKEN_KEY = 'elsa.token';

export class ApiError extends Error {
  constructor(status, code, message, requestId) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export function getToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token === null) sessionStorage.removeItem(TOKEN_KEY);
    else sessionStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* Almacenamiento bloqueado: la sesión durará lo que dure la página. */
  }
}

async function request(path, { method = 'GET', body, headers = {}, auth = true } = {}) {
  const finalHeaders = { ...headers };
  const token = getToken();
  if (auth && token) finalHeaders.Authorization = `Bearer ${token}`;

  let payload = body;
  if (body !== undefined && !(body instanceof FormData)) {
    finalHeaders['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(`${BASE}${path}`, { method, headers: finalHeaders, body: payload });
  } catch (cause) {
    throw new ApiError(0, 'network_error', 'No se pudo contactar con el servidor.', null);
  }

  if (response.status === 204) return null;

  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const error = data && data.error ? data.error : {};
    throw new ApiError(
      response.status,
      error.code || 'error',
      error.message || `El servidor respondió ${response.status}.`,
      error.request_id || null,
    );
  }
  return data;
}

/**
 * Descarga un recurso protegido como Blob.
 *
 * Un `<audio src="/api/...">` no sirve: el navegador pide esa URL sin la
 * cabecera Authorization y el backend la rechaza, con razón. La nota de voz
 * puede contener información interna de planta, así que se pide con el token
 * y se reproduce desde memoria.
 */
export async function fetchBlob(path) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(`${BASE}${path}`, { headers });
  } catch {
    throw new ApiError(0, 'network_error', 'No se pudo contactar con el servidor.', null);
  }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      'download_failed',
      'No se pudo descargar el audio.',
      null,
    );
  }
  return response.blob();
}

export const api = {
  sessionContext: () => request('/session/context', { auth: false }),
  me: () => request('/me'),
  asset: (domain, asset) => request(`/knowledge/${domain}/${asset}`),
  components: (domain, asset) => request(`/knowledge/${domain}/${asset}/components`),
  failureModes: (domain, asset) => request(`/knowledge/${domain}/${asset}/failure-modes`),
  request,
};
