/**
 * Demo vs live data source selection.
 *
 * The UI can run two ways:
 *
 * ``live``
 *   Every screen talks to the FastAPI backend. This is what production uses.
 *
 * ``demo``
 *   Screens read and write browser-local sample data. Useful for showing the
 *   product without infrastructure, and for frontend work when the backend is
 *   not running.
 *
 * Defaults are chosen so neither audience gets a surprise: a production build
 * defaults to ``live``, because shipping a build that silently serves fake data
 * would be far worse than one that shows connection errors. A dev build
 * defaults to ``demo`` so the UI is explorable without standing up Postgres,
 * Redis and MinIO first. ``VITE_API_MODE`` overrides both.
 *
 * Demo mode is always announced in the UI (see DemoModeBanner). Fake data that
 * looks real is a liability — someone will eventually screenshot it into a
 * status report.
 */

export type ApiMode = 'demo' | 'live'

function resolveMode(): ApiMode {
  const raw = (import.meta.env.VITE_API_MODE ?? '').trim().toLowerCase()

  if (raw === 'demo' || raw === 'live') return raw

  if (raw !== '') {
    // A typo like VITE_API_MODE=Live should not silently pick a default.
    console.warn(
      `[apiMode] Unrecognised VITE_API_MODE="${raw}"; expected 'demo' or 'live'.`,
    )
  }

  return import.meta.env.DEV ? 'demo' : 'live'
}

export const API_MODE: ApiMode = resolveMode()

export const isDemoMode = API_MODE === 'demo'
export const isLiveMode = API_MODE === 'live'

/** Human-readable explanation, surfaced in the banner and on the login screen. */
export const DEMO_MODE_NOTICE =
  'Demo mode: data is stored in this browser only. Nothing is saved to the ' +
  'server, and no credential reaches DigiLocker or a ledger.'
