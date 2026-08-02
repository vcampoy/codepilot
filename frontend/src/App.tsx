const DEFAULT_API_BASE_URL = 'http://localhost:8000'

const configuredApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()
const apiBaseUrl = configuredApiBaseUrl || DEFAULT_API_BASE_URL
const apiDocsUrl = `${apiBaseUrl.replace(/\/+$/, '')}/docs`

function Mark() {
  return (
    <svg
      aria-hidden="true"
      className="brand-mark"
      viewBox="0 0 32 32"
      fill="none"
    >
      <path d="M8 6.5h16M8 16h10M8 25.5h16" />
      <circle cx="24" cy="16" r="2.5" />
    </svg>
  )
}

function Arrow() {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
      <path d="M4 10h11M11 6l4 4-4 4" />
    </svg>
  )
}

function App() {
  return (
    <div className="site-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="CodePilot home">
          <Mark />
          <span>CodePilot</span>
        </a>
        <span className="status">
          <span className="status-dot" aria-hidden="true" />
          Foundation online
        </span>
      </header>

      <main id="top" className="hero">
        <div className="hero-copy">
          <p className="eyebrow">Evidence-first code intelligence</p>
          <h1>
            Understand the code.
            <span>Trust the evidence.</span>
          </h1>
          <p className="summary">
            CodePilot turns repository signals into grounded architectural
            insight, helping engineering teams reason about risk, structure,
            and change with confidence.
          </p>
          <a className="docs-link" href={apiDocsUrl}>
            Explore API documentation
            <Arrow />
          </a>
        </div>

        <aside className="evidence-panel" aria-label="CodePilot principles">
          <div className="panel-header">
            <span>Analysis contract</span>
            <span className="panel-id">CP / 001</span>
          </div>
          <dl>
            <div>
              <dt>01</dt>
              <dd>
                <strong>Observe</strong>
                <span>Start with repository facts.</span>
              </dd>
            </div>
            <div>
              <dt>02</dt>
              <dd>
                <strong>Connect</strong>
                <span>Trace evidence across the system.</span>
              </dd>
            </div>
            <div>
              <dt>03</dt>
              <dd>
                <strong>Explain</strong>
                <span>Make every insight accountable.</span>
              </dd>
            </div>
          </dl>
          <div className="signal" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
        </aside>
      </main>

      <footer className="site-footer">
        <span>Repository intelligence, grounded in evidence.</span>
        <span>© {new Date().getFullYear()} CodePilot</span>
      </footer>
    </div>
  )
}

export default App
