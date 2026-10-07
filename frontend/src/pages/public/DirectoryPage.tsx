import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Award, Users, Share2, Linkedin, ChevronDown, ShieldCheck } from 'lucide-react'
import type { DirectoryClass, PublicEarner } from '@/lib/directory'

/**
 * Public badge directory (U3 — S14). Unauthenticated.
 *
 * Lists a tenant's directory-visible badge classes and, on expand, the masked
 * public earners of each. Includes share affordances (LinkedIn / copy) that use
 * the public share endpoint. Reads an optional ?tenant= id; falls back to demo
 * content so the page renders standalone.
 */

const DEMO_CLASSES: DirectoryClass[] = [
  {
    badge_class_id: 'bc-1', name: 'Python Expert',
    description: 'Awarded for demonstrated mastery of Python.', criteria_narrative: 'Pass the proctored assessment.', image_s3_key: null,
  },
  {
    badge_class_id: 'bc-2', name: 'Data Steward',
    description: 'Recognises responsible data handling and governance.', criteria_narrative: null, image_s3_key: null,
  },
]

const DEMO_EARNERS: Record<string, PublicEarner[]> = {
  'bc-1': [
    { display_name: 'a***e@e***.com', assertion_id: 'as-1001', issued_at: '2026-02-12' },
    { display_name: 'r***v@e***.com', assertion_id: 'as-1101', issued_at: '2026-02-20' },
  ],
  'bc-2': [
    { display_name: 'm***a@a***.org', assertion_id: 'as-1002', issued_at: '2026-03-05' },
  ],
}

export default function DirectoryPage() {
  const [params] = useSearchParams()
  const tenant = params.get('tenant')
  const [classes] = useState<DirectoryClass[]>(DEMO_CLASSES)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  const share = (assertionId: string) => {
    const url = `${window.location.origin}/api/v1/public/badges/assertions/${assertionId}?channel=link`
    navigator.clipboard?.writeText(url).then(
      () => { setCopied(assertionId); setTimeout(() => setCopied(null), 2000) },
      () => undefined,
    )
  }

  const linkedin = (assertionId: string) => {
    const url = `${window.location.origin}/api/v1/public/badges/assertions/${assertionId}?channel=linkedin`
    return `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-gray-900 text-white">
        <div className="max-w-5xl mx-auto px-6 py-5 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 font-bold text-brand-400">
            <ShieldCheck size={20} /> Repo SaaS
          </Link>
          <span className="text-sm text-gray-300">Public Badge Directory</span>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">
        <h1 className="text-2xl font-bold text-gray-900">Badge Directory</h1>
        <p className="text-gray-500 mt-1">
          Publicly listed badges{tenant ? ` for issuer ${tenant}` : ''}. Expand a badge to see its earners.
        </p>

        <div className="mt-8 space-y-4" data-testid="directory-list">
          {classes.map(c => (
            <div key={c.badge_class_id} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <button
                data-testid={`directory-class-${c.badge_class_id}`}
                onClick={() => setExpanded(expanded === c.badge_class_id ? null : c.badge_class_id)}
                className="w-full flex items-center justify-between p-6 text-left hover:bg-gray-50"
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-amber-100 rounded-lg flex items-center justify-center">
                    <Award size={18} className="text-amber-600" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-900">{c.name}</h3>
                    {c.description && <p className="text-sm text-gray-500">{c.description}</p>}
                  </div>
                </div>
                <ChevronDown
                  size={18}
                  className={`text-gray-400 transition-transform ${expanded === c.badge_class_id ? 'rotate-180' : ''}`}
                />
              </button>

              {expanded === c.badge_class_id && (
                <div className="border-t border-gray-100 p-6 bg-gray-50" data-testid={`directory-earners-${c.badge_class_id}`}>
                  <div className="flex items-center gap-2 text-sm text-gray-600 mb-3">
                    <Users size={15} /> Public earners
                  </div>
                  <ul className="space-y-2">
                    {(DEMO_EARNERS[c.badge_class_id] ?? []).map(e => (
                      <li
                        key={e.assertion_id}
                        className="flex items-center justify-between bg-white rounded-lg border border-gray-200 px-4 py-2.5"
                      >
                        <div>
                          <span className="text-sm font-medium text-gray-800">{e.display_name}</span>
                          {e.issued_at && <span className="text-xs text-gray-400 ml-2">{e.issued_at}</span>}
                        </div>
                        <div className="flex items-center gap-1">
                          <a
                            href={linkedin(e.assertion_id)}
                            target="_blank"
                            rel="noopener noreferrer"
                            data-testid={`directory-linkedin-${e.assertion_id}`}
                            className="p-1.5 text-gray-400 hover:text-brand-600 rounded"
                            title="Share on LinkedIn"
                          >
                            <Linkedin size={15} />
                          </a>
                          <button
                            data-testid={`directory-share-${e.assertion_id}`}
                            onClick={() => share(e.assertion_id)}
                            className="p-1.5 text-gray-400 hover:text-brand-600 rounded"
                            title="Copy public link"
                          >
                            <Share2 size={15} />
                          </button>
                          {copied === e.assertion_id && (
                            <span className="text-xs text-green-600">copied</span>
                          )}
                        </div>
                      </li>
                    ))}
                    {(DEMO_EARNERS[c.badge_class_id] ?? []).length === 0 && (
                      <li className="text-sm text-gray-400">No public earners yet.</li>
                    )}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      </main>
    </div>
  )
}
