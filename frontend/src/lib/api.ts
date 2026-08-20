/**
 * HTTP client for the FastAPI backend.
 *
 * Three deliberate behaviours:
 *
 * *Errors are normalised.* The backend returns
 * ``{"detail": {"code": "...", "message": "..."}}`` for handled failures but
 * FastAPI's own validation errors are shaped ``{"detail": [{loc, msg, type}]}``,
 * and a proxy timeout has no body at all. Callers should not have to know which
 * of those they got, so everything becomes an ``ApiError`` with a stable
 * ``code`` and a human-readable ``message``.
 *
 * *401 does not redirect from here.* The previous version set
 * ``window.location.href = '/login'``, which does a full page load, discards
 * React state, and races any other in-flight request that also 401s. Instead an
 * ``onUnauthorized`` hook lets AuthContext clear the session and let the router
 * navigate.
 *
 * *There is a timeout.* Without one a hung upload leaves a spinner running
 * forever, which users read as a frozen application rather than a failure.
 */

import axios, {
  AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'

export const TOKEN_STORAGE_KEY = 'access_token'

/** Long enough for a bulk upload, short enough to surface a dead backend. */
const DEFAULT_TIMEOUT_MS = 60_000

export class ApiError extends Error {
  readonly status: number | null
  readonly code: string
  readonly details: unknown

  constructor(args: {
    message: string
    code: string
    status: number | null
    details?: unknown
  }) {
    super(args.message)
    this.name = 'ApiError'
    this.status = args.status
    this.code = args.code
    this.details = args.details
  }

  /** True when retrying the same request could plausibly succeed. */
  get isRetryable(): boolean {
    if (this.status === null) return true // network/timeout
    return this.status === 429 || this.status >= 500
  }
}

type UnauthorizedHandler = () => void

let onUnauthorized: UnauthorizedHandler | null = null

/** Register a callback invoked once per 401 so the app can clear its session. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler
}

export const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '/api/v1',
  timeout: DEFAULT_TIMEOUT_MS,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})


/** Pull a usable message and code out of any error shape the API can produce. */
function normalise(error: AxiosError): ApiError {
  // No response: network failure, DNS, CORS, or the timeout above.
  if (!error.response) {
    const timedOut = error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT'
    return new ApiError({
      code: timedOut ? 'TIMEOUT' : 'NETWORK_ERROR',
      status: null,
      message: timedOut
        ? 'The server took too long to respond. It may still be processing.'
        : 'Could not reach the server. Check that the API is running.',
      details: error.message,
    })
  }

  const { status, data } = error.response
  const detail = (data as { detail?: unknown } | undefined)?.detail

  // Handled backend errors: {"detail": {"code", "message"}}
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const d = detail as { code?: string; message?: string }
    return new ApiError({
      code: d.code ?? `HTTP_${status}`,
      status,
      message: d.message ?? defaultMessageFor(status),
      details: detail,
    })
  }

  // FastAPI request validation: {"detail": [{loc, msg, type}, ...]}
  if (Array.isArray(detail)) {
    const first = detail[0] as { loc?: unknown[]; msg?: string } | undefined
    // Drop the leading "body"/"query" segment; the field name is what helps.
    const field = Array.isArray(first?.loc) ? first!.loc!.slice(1).join('.') : ''
    return new ApiError({
      code: 'VALIDATION_ERROR',
      status,
      message: field
        ? `${field}: ${first?.msg ?? 'is invalid'}`
        : (first?.msg ?? 'The request was rejected as invalid.'),
      details: detail,
    })
  }

  return new ApiError({
    code: `HTTP_${status}`,
    status,
    message: typeof detail === 'string' ? detail : defaultMessageFor(status),
    details: data,
  })
}

function defaultMessageFor(status: number): string {
  switch (status) {
    case 400:
      return 'The request was rejected.'
    case 401:
      return 'Your session has expired. Please sign in again.'
    case 403:
      return 'You do not have permission to do this.'
    case 404:
      return 'Not found.'
    case 409:
      return 'This conflicts with the current state.'
    case 422:
      return 'The request was rejected as invalid.'
    case 429:
      return 'Rate limit exceeded. Please wait and try again.'
    case 503:
      return 'A required service is unavailable. Nothing was changed.'
    case 507:
      return 'Storage quota exceeded.'
    default:
      return status >= 500
        ? 'The server encountered an error.'
        : 'The request failed.'
  }
}

api.interceptors.response.use(
  response => response,
  (error: AxiosError) => {
    const apiError = normalise(error)

    if (apiError.status === 401) {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      // Let the app decide how to navigate; a hard redirect here would discard
      // React state and race concurrent 401s.
      onUnauthorized?.()
    }

    return Promise.reject(apiError)
  },
)

export default api
