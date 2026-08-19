/**
 * Public landing page.
 *
 * Accessibility notes, since this is the first thing a citizen or auditor sees:
 * sections are landmarks with labelled headings, the decorative gradients are
 * aria-hidden, every interactive element has a visible focus ring, and colour
 * is never the only carrier of meaning. Contrast is kept at brand-700+ on light
 * backgrounds and white on brand-800+ to stay above 4.5:1.
 */

import { Link } from 'react-router-dom'
import {
  ArrowRight,
  BadgeCheck,
  CheckCircle2,
  ChevronRight,
  FileText,
  Landmark,
  Menu,
  ShieldCheck,
  Sparkles,
  Terminal,
  X,
} from 'lucide-react'
import { useState } from 'react'

import {
  FEATURE_GROUPS,
  HERO_STATS,
  PIPELINE,
  ROLES,
} from '@/lib/landingContent'

const NAV_LINKS = [
  { href: '#issuance', label: 'Issue' },
  { href: '#verify', label: 'Verify' },
  { href: '#trust', label: 'Proof' },
  { href: '#privacy', label: 'Privacy' },
  { href: '#platform', label: 'Platform' },
  { href: '#developers', label: 'API' },
]

export default function LandingPage() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <div className="min-h-screen bg-white text-gray-900">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded-lg focus:bg-brand-700 focus:px-4 focus:py-2 focus:text-white"
      >
        Skip to main content
      </a>

      <SiteHeader menuOpen={menuOpen} onToggleMenu={() => setMenuOpen(v => !v)} />

      <main id="main">
        <Hero />
        <StatsBar />
        {FEATURE_GROUPS.map((group, index) => (
          <FeatureSection key={group.id} group={group} index={index} />
        ))}
        <PipelineSection />
        <RolesSection />
        <DeveloperSection />
        <ComplianceSection />
        <CtaSection />
      </main>

      <SiteFooter />
    </div>
  )
}


function SiteHeader({
  menuOpen,
  onToggleMenu,
}: {
  menuOpen: boolean
  onToggleMenu: () => void
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-gray-200/80 bg-white/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link
          to="/"
          className="flex items-center gap-2.5 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-600 focus:ring-offset-2"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-700">
            <Landmark size={20} className="text-white" aria-hidden="true" />
          </span>
          <span className="text-lg font-semibold tracking-tight">
            Credential<span className="text-brand-700">Repo</span>
          </span>
        </Link>

        <nav aria-label="Sections" className="hidden items-center gap-1 lg:flex">
          {NAV_LINKS.map(link => (
            <a
              key={link.href}
              href={link.href}
              className="rounded-lg px-3 py-2 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-900 focus:outline-none focus:ring-2 focus:ring-brand-600"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="hidden items-center gap-3 lg:flex">
          <Link
            to="/verify"
            className="rounded-lg px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-brand-600"
          >
            Verify a credential
          </Link>
          <Link
            to="/login"
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand-700 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-800 focus:outline-none focus:ring-2 focus:ring-brand-600 focus:ring-offset-2"
          >
            Sign in
            <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </div>

        <button
          type="button"
          onClick={onToggleMenu}
          aria-expanded={menuOpen}
          aria-controls="mobile-nav"
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          className="rounded-lg p-2 text-gray-700 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-brand-600 lg:hidden"
        >
          {menuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {menuOpen && (
        <nav
          id="mobile-nav"
          aria-label="Sections"
          className="border-t border-gray-200 bg-white px-4 py-3 lg:hidden"
        >
          <ul className="space-y-1">
            {NAV_LINKS.map(link => (
              <li key={link.href}>
                <a
                  href={link.href}
                  onClick={onToggleMenu}
                  className="block rounded-lg px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-brand-600"
                >
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex flex-col gap-2 border-t border-gray-100 pt-3">
            <Link
              to="/verify"
              className="rounded-lg border border-gray-300 px-4 py-2 text-center text-sm font-medium text-gray-700 focus:outline-none focus:ring-2 focus:ring-brand-600"
            >
              Verify a credential
            </Link>
            <Link
              to="/login"
              className="rounded-lg bg-brand-700 px-4 py-2 text-center text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-brand-600"
            >
              Sign in
            </Link>
          </div>
        </nav>
      )}
    </header>
  )
}


function Hero() {
  return (
    <section className="relative overflow-hidden bg-gradient-to-b from-brand-900 via-brand-800 to-brand-900">
      {/* Decorative only — hidden from assistive technology. */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0">
        <div className="absolute -top-24 -right-24 h-96 w-96 rounded-full bg-brand-500/25 blur-3xl" />
        <div className="absolute top-1/2 -left-32 h-96 w-96 rounded-full bg-brand-400/15 blur-3xl" />
        <div
          className="absolute inset-0 opacity-[0.15]"
          style={{
            backgroundImage:
              'linear-gradient(to right, rgba(255,255,255,.28) 1px, transparent 1px), linear-gradient(to bottom, rgba(255,255,255,.28) 1px, transparent 1px)',
            backgroundSize: '56px 56px',
            maskImage: 'radial-gradient(ellipse 70% 60% at 50% 40%, black, transparent)',
            WebkitMaskImage:
              'radial-gradient(ellipse 70% 60% at 50% 40%, black, transparent)',
          }}
        />
      </div>

      <div className="relative mx-auto max-w-7xl px-4 py-20 sm:px-6 sm:py-28 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <span className="inline-flex items-center gap-2 rounded-full border border-white/25 bg-white/10 px-3.5 py-1.5 text-sm font-medium text-brand-50">
            <Sparkles size={14} aria-hidden="true" />
            Multi-tenant credential infrastructure
          </span>

          <h1 className="mt-6 text-4xl font-bold leading-[1.1] tracking-tight text-white sm:text-5xl lg:text-6xl">
            Issue credentials citizens trust and verifiers can check
            <span className="text-brand-300"> without trusting you</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-brand-100">
            A document and credential repository for issuing authorities.
            Encrypted per tenant, anchored to a ledger for tamper evidence,
            published to DigiLocker, and built around the consent and erasure
            duties the DPDP Act places on you.
          </p>

          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              to="/login"
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-white px-6 py-3 text-base font-semibold text-brand-800 shadow-lg shadow-brand-900/25 transition-colors hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-brand-800 sm:w-auto"
            >
              Open the console
              <ArrowRight size={17} aria-hidden="true" />
            </Link>
            <Link
              to="/verify"
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/30 bg-white/10 px-6 py-3 text-base font-semibold text-white transition-colors hover:bg-white/20 focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-brand-800 sm:w-auto"
            >
              <ShieldCheck size={17} aria-hidden="true" />
              Verify a credential
            </Link>
          </div>

          <ul className="mt-9 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-brand-100">
            {[
              'No account needed to verify',
              'Selective disclosure by default',
              'Immutable audit trail',
            ].map(item => (
              <li key={item} className="inline-flex items-center gap-1.5">
                <CheckCircle2 size={15} className="text-brand-300" aria-hidden="true" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}

function StatsBar() {
  return (
    <section aria-label="Platform characteristics" className="border-b border-gray-200 bg-gray-50">
      <div className="mx-auto grid max-w-7xl grid-cols-2 gap-px divide-gray-200 px-4 py-10 sm:px-6 lg:grid-cols-4 lg:px-8">
        {HERO_STATS.map(stat => (
          <div key={stat.label} className="px-2 text-center lg:px-6">
            <p className="text-xl font-bold tracking-tight text-brand-800 sm:text-2xl">
              {stat.value}
            </p>
            <p className="mt-1 text-sm text-gray-600">{stat.label}</p>
          </div>
        ))}
      </div>
    </section>
  )
}


function FeatureSection({
  group,
  index,
}: {
  group: (typeof FEATURE_GROUPS)[number]
  index: number
}) {
  const tinted = index % 2 === 1
  const headingId = `${group.id}-heading`

  return (
    <section
      id={group.id}
      aria-labelledby={headingId}
      className={`scroll-mt-20 py-20 sm:py-24 ${tinted ? 'bg-gray-50' : 'bg-white'}`}
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-wider text-brand-700">
            {group.eyebrow}
          </p>
          <h2
            id={headingId}
            className="mt-3 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl"
          >
            {group.heading}
          </h2>
          <p className="mt-4 text-lg leading-relaxed text-gray-600">{group.intro}</p>
        </div>

        <ul className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {group.features.map(feature => {
            const Icon = feature.icon
            return (
              <li
                key={feature.title}
                className="group rounded-2xl border border-gray-200 bg-white p-6 transition-shadow hover:shadow-md"
              >
                <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 ring-1 ring-brand-100">
                  <Icon size={21} className="text-brand-700" aria-hidden="true" />
                </span>
                <h3 className="mt-4 text-base font-semibold text-gray-900">
                  {feature.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-gray-600">
                  {feature.body}
                </p>
                {feature.detail && (
                  <p className="mt-3 border-t border-gray-100 pt-3 text-sm leading-relaxed text-gray-500">
                    {feature.detail}
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      </div>
    </section>
  )
}

function PipelineSection() {
  return (
    <section
      id="pipeline"
      aria-labelledby="pipeline-heading"
      className="scroll-mt-20 bg-brand-900 py-20 sm:py-24"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-wider text-brand-300">
            Under the hood
          </p>
          <h2
            id="pipeline-heading"
            className="mt-3 text-3xl font-bold tracking-tight text-white sm:text-4xl"
          >
            What happens when a credential is issued
          </h2>
          <p className="mt-4 text-lg leading-relaxed text-brand-100">
            Steps one to three share a single transaction, so a credential never
            exists without its audit entry. Everything after it is asynchronous —
            a ledger or DigiLocker outage delays publication without ever failing
            an issuance.
          </p>
        </div>

        <ol className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-5">
          {PIPELINE.map(item => (
            <li
              key={item.step}
              className="rounded-2xl border border-white/15 bg-white/[0.07] p-5"
            >
              <span className="text-sm font-bold tabular-nums text-brand-300">
                {item.step}
              </span>
              <h3 className="mt-2 text-base font-semibold text-white">{item.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-brand-100">{item.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  )
}

function RolesSection() {
  return (
    <section
      id="roles"
      aria-labelledby="roles-heading"
      className="scroll-mt-20 bg-white py-20 sm:py-24"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-wider text-brand-700">
            Access control
          </p>
          <h2
            id="roles-heading"
            className="mt-3 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl"
          >
            Five roles, enforced on every route
          </h2>
          <p className="mt-4 text-lg leading-relaxed text-gray-600">
            Hiding a menu item is not access control. Permissions are checked
            server-side per request, so a typed URL gets the same answer as a
            hidden button.
          </p>
        </div>

        <div className="mt-10 overflow-hidden rounded-2xl border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <caption className="sr-only">
              Platform roles and their permissions
            </caption>
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-600">
                  Role
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-600">
                  Who it is
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-600">
                  What they can do
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {ROLES.map(role => (
                <tr key={role.role} className="hover:bg-gray-50">
                  <td className="whitespace-nowrap px-6 py-4">
                    <code className="rounded bg-brand-50 px-2 py-1 text-xs font-medium text-brand-800">
                      {role.role}
                    </code>
                  </td>
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-gray-900">
                    {role.label}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-600">{role.can}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}


const VERIFY_SNIPPET = `# Verify a credential's inclusion proof — no auth, no database needed
curl -X POST https://your-host/api/v1/anchors/verify \\
  -H 'Content-Type: application/json' \\
  -d '{
    "leaf_hash": "<credential digest from the proof bundle>",
    "root_hex":  "<anchored merkle root>",
    "proof": { "leaf_index": 2, "leaf_count": 5, "siblings": [...] }
  }'

# => { "proof_valid": true,
#      "ledger_agrees": true,
#      "message": "Proof is valid and the ledger confirms the anchored root." }`

function DeveloperSection() {
  return (
    <section
      id="developers"
      aria-labelledby="developers-heading"
      className="scroll-mt-20 bg-gray-50 py-20 sm:py-24"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid items-center gap-12 lg:grid-cols-2">
          <div>
            <p className="text-sm font-semibold uppercase tracking-wider text-brand-700">
              For developers
            </p>
            <h2
              id="developers-heading"
              className="mt-3 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl"
            >
              A versioned REST API, documented and explorable
            </h2>
            <p className="mt-4 text-lg leading-relaxed text-gray-600">
              Every capability on this page is an endpoint under{' '}
              <code className="rounded bg-white px-1.5 py-0.5 text-[0.9em] text-brand-800 ring-1 ring-gray-200">
                /api/v1
              </code>
              , described by an OpenAPI 3 document with interactive docs. Errors
              are structured, with a stable machine-readable code alongside the
              human-readable message.
            </p>

            <ul className="mt-8 space-y-3">
              {[
                'OpenAPI 3 schema with Swagger UI and ReDoc',
                'Structured errors with stable codes, never bare strings',
                'Rate-limit headers on every response, Retry-After on 429',
                'Idempotent bulk jobs with a status endpoint to poll',
                'Structured JSON logs that redact tokens and PII automatically',
              ].map(item => (
                <li key={item} className="flex items-start gap-3">
                  <CheckCircle2
                    size={19}
                    className="mt-0.5 shrink-0 text-brand-700"
                    aria-hidden="true"
                  />
                  <span className="text-sm leading-relaxed text-gray-700">{item}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="overflow-hidden rounded-2xl border border-gray-800 bg-gray-900 shadow-xl">
            <div className="flex items-center gap-2 border-b border-gray-800 bg-gray-950/60 px-4 py-3">
              <Terminal size={15} className="text-gray-400" aria-hidden="true" />
              <span className="text-xs font-medium text-gray-400">
                Offline proof verification
              </span>
            </div>
            <pre className="overflow-x-auto p-5 text-[13px] leading-relaxed">
              <code className="text-gray-100">{VERIFY_SNIPPET}</code>
            </pre>
          </div>
        </div>
      </div>
    </section>
  )
}

function ComplianceSection() {
  return (
    <section
      id="compliance"
      aria-labelledby="compliance-heading"
      className="scroll-mt-20 bg-white py-20 sm:py-24"
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid gap-10 lg:grid-cols-3">
          <div className="lg:col-span-1">
            <p className="text-sm font-semibold uppercase tracking-wider text-brand-700">
              Compliance posture
            </p>
            <h2
              id="compliance-heading"
              className="mt-3 text-3xl font-bold tracking-tight text-gray-900 sm:text-4xl"
            >
              What we provide, and what remains yours
            </h2>
            <p className="mt-4 text-base leading-relaxed text-gray-600">
              Being straight about this is more useful than a badge. The platform
              supplies technical controls. Compliance itself is an
              organisational outcome that depends on your policies, your staff,
              and an independent audit.
            </p>
          </div>

          <div className="grid gap-5 sm:grid-cols-2 lg:col-span-2">
            <div className="rounded-2xl border border-brand-200 bg-brand-50/60 p-6">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-brand-700">
                <BadgeCheck size={19} className="text-white" aria-hidden="true" />
              </span>
              <h3 className="mt-4 font-semibold text-gray-900">
                Provided by the platform
              </h3>
              <ul className="mt-3 space-y-2 text-sm leading-relaxed text-gray-700">
                <li>Consent capture with purpose, legal basis, and notice version</li>
                <li>Data-principal access, correction, and erasure endpoints</li>
                <li>Field-level encryption and per-tenant key separation</li>
                <li>Immutable audit trail and enforced retention windows</li>
                <li>Semantic HTML, keyboard navigation, and labelled controls</li>
              </ul>
            </div>

            <div className="rounded-2xl border border-amber-200 bg-amber-50/70 p-6">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-amber-600">
                <FileText size={19} className="text-white" aria-hidden="true" />
              </span>
              <h3 className="mt-4 font-semibold text-gray-900">
                Remains your responsibility
              </h3>
              <ul className="mt-3 space-y-2 text-sm leading-relaxed text-gray-700">
                <li>Publishing your privacy notice and naming a grievance officer</li>
                <li>Deciding lawful basis and retention periods per document type</li>
                <li>
                  Manual accessibility testing with assistive technology, which
                  GIGW conformance requires and no library can substitute for
                </li>
                <li>Breach assessment, reporting timelines, and staff training</li>
                <li>Independent security and compliance audit</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}


function CtaSection() {
  return (
    <section aria-labelledby="cta-heading" className="bg-gray-50 py-20 sm:py-24">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-brand-800 to-brand-900 px-6 py-14 text-center sm:px-16">
          <div aria-hidden="true" className="pointer-events-none absolute inset-0">
            <div className="absolute -top-20 right-0 h-72 w-72 rounded-full bg-brand-500/25 blur-3xl" />
            <div className="absolute -bottom-24 left-8 h-72 w-72 rounded-full bg-brand-400/15 blur-3xl" />
          </div>

          <div className="relative mx-auto max-w-2xl">
            <h2
              id="cta-heading"
              className="text-3xl font-bold tracking-tight text-white sm:text-4xl"
            >
              Try it with the demo console
            </h2>
            <p className="mt-4 text-lg leading-relaxed text-brand-100">
              Sign in as an administrator, an issuing officer, or a citizen to
              see the same credential from each side — issuance, selective
              sharing, and verification.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link
                to="/login"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-white px-6 py-3 text-base font-semibold text-brand-800 transition-colors hover:bg-brand-50 focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-brand-900 sm:w-auto"
              >
                Sign in
                <ChevronRight size={17} aria-hidden="true" />
              </Link>
              <Link
                to="/verify"
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/30 bg-white/10 px-6 py-3 text-base font-semibold text-white transition-colors hover:bg-white/20 focus:outline-none focus:ring-2 focus:ring-white focus:ring-offset-2 focus:ring-offset-brand-900 sm:w-auto"
              >
                Verify without signing in
              </Link>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function SiteFooter() {
  const year = new Date().getFullYear()

  return (
    <footer className="border-t border-gray-200 bg-white">
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="flex flex-col gap-8 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-sm">
            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-700">
                <Landmark size={19} className="text-white" aria-hidden="true" />
              </span>
              <span className="text-lg font-semibold tracking-tight text-gray-900">
                Credential<span className="text-brand-700">Repo</span>
              </span>
            </div>
            <p className="mt-3 text-sm leading-relaxed text-gray-600">
              Multi-tenant document and credential repository for issuing
              authorities, with ledger-anchored tamper evidence and
              consent-scoped verification.
            </p>
          </div>

          <nav aria-label="Footer" className="grid grid-cols-2 gap-8 sm:grid-cols-2">
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Product</h2>
              <ul className="mt-3 space-y-2 text-sm">
                {NAV_LINKS.map(link => (
                  <li key={link.href}>
                    <a
                      href={link.href}
                      className="rounded text-gray-600 hover:text-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-600"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Access</h2>
              <ul className="mt-3 space-y-2 text-sm">
                <li>
                  <Link
                    to="/login"
                    className="rounded text-gray-600 hover:text-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-600"
                  >
                    Sign in
                  </Link>
                </li>
                <li>
                  <Link
                    to="/verify"
                    className="rounded text-gray-600 hover:text-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-600"
                  >
                    Verify a credential
                  </Link>
                </li>
                <li>
                  <a
                    href="#compliance"
                    className="rounded text-gray-600 hover:text-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-600"
                  >
                    Compliance posture
                  </a>
                </li>
              </ul>
            </div>
          </nav>
        </div>

        <div className="mt-10 flex flex-col gap-2 border-t border-gray-100 pt-6 text-sm text-gray-500 sm:flex-row sm:items-center sm:justify-between">
          <p>&copy; {year} CredentialRepo. All rights reserved.</p>
          <p>
            Provides controls supporting GIGW and DPDP obligations. Not a
            certification of compliance.
          </p>
        </div>
      </div>
    </footer>
  )
}
