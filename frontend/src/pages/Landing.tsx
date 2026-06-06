// PulseGo marketing landing page (route "/"). On-brand per the PulseGo brand
// guideline — Cream surface, Pulse Red CTAs, Poppins display + Inter body,
// rounded friendly cards and the mascot mark. Primary CTA routes to /login, or
// straight to /app when the visitor already holds a token.

import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useStore } from "../store";

const FEATURES = [
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
           strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" />
      </svg>
    ),
    title: "Lightning fast",
    body: "Routing and re-planning run locally on a DGX Spark GB10 — the whole fleet re-optimises in under a second, with zero data egress.",
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
           strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M12 3 4 6v6c0 5 3.5 7.5 8 9 4.5-1.5 8-4 8-9V6l-8-3z" />
        <path d="m9 12 2 2 4-4" />
      </svg>
    ),
    title: "Reliable & safe",
    body: "Cold-chain aware dispatch never mis-assigns a temperature-critical sample. Every STAT job is tracked and accounted for, end to end.",
  },
  {
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
           strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M12 21s-7-5.5-7-11a7 7 0 0 1 14 0c0 5.5-7 11-7 11z" />
        <circle cx="12" cy="10" r="2.5" />
      </svg>
    ),
    title: "Real-time tracking",
    body: "Live London traffic, TfL CCTV and signal recommendations keep every blood sample and transplant box on the fastest path across the city.",
  },
];

function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`pg-logo ${className}`}>
      <img src="/pulsego.svg" alt="" className="pg-mark" aria-hidden />
      <span className="pg-word">PulseGo</span>
    </span>
  );
}

export default function Landing() {
  const token = useStore((s) => s.token);
  const ctaHref = token ? "/app" : "/login";

  // Lightweight SEO / OG without a helmet dependency.
  useEffect(() => {
    const prevTitle = document.title;
    document.title = "PulseGo — fast, friendly medical delivery for London";
    const metas: HTMLMetaElement[] = [];
    const set = (attr: "name" | "property", key: string, content: string) => {
      let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
      if (!el) {
        el = document.createElement("meta");
        el.setAttribute(attr, key);
        document.head.appendChild(el);
        metas.push(el);
      }
      el.setAttribute("content", content);
    };
    const desc = "PulseGo — fast, friendly medical delivery for London. Local-first AI on DGX Spark, anticipatory routing and live London data + CCTV. pulsego.org";
    set("name", "description", desc);
    set("property", "og:title", "PulseGo — fast, friendly medical delivery for London");
    set("property", "og:description", desc);
    set("property", "og:type", "website");
    set("property", "og:site_name", "PulseGo");
    set("name", "twitter:card", "summary_large_image");
    return () => {
      document.title = prevTitle;
      for (const el of metas) el.remove();
    };
  }, []);

  return (
    <div className="site" data-testid="landing">
      <header className="site-nav">
        <Logo />
        <nav className="site-nav-links">
          <a href="#how">How it works</a>
          <a href="#features">Features</a>
          <a href="#about">About</a>
        </nav>
        <Link className="site-btn primary sm" to={ctaHref} data-testid="landing-nav-cta">
          {token ? "Open console" : "Get started"}
        </Link>
      </header>

      <main className="site-main">
        <section className="hero">
          <div className="hero-copy">
            <div className="hero-eyebrow">London · Medical Logistics · DGX Spark</div>
            <h1 className="hero-title">
              Fast, friendly<br />medical delivery.<br />
              <span className="hero-accent">Every time.</span>
            </h1>
            <p className="hero-sub">
              PulseGo moves time-critical medical samples across London — reliable,
              local-first AI routing so clinicians can focus on what matters most.
            </p>
            <div className="hero-cta-row">
              <Link className="site-btn primary" to={ctaHref} data-testid="landing-cta">
                {token ? "Open the console →" : "Launch console →"}
              </Link>
              <a className="site-btn ghost" href="#how">
                <span className="play-dot" aria-hidden>▶</span> How it works
              </a>
            </div>
          </div>

          {/* Brand hero art: PulseGo courier illustration. */}
          <div className="hero-art" aria-hidden>
            <img src="/hero-courier.png" alt="PulseGo courier on the move" className="hero-illus" />
          </div>
        </section>

        <section className="features" id="features">
          {FEATURES.map((f) => (
            <article className="feature-card" key={f.title}>
              <span className="feature-icon">{f.icon}</span>
              <h3 className="feature-title">{f.title}</h3>
              <p className="feature-body">{f.body}</p>
            </article>
          ))}
        </section>

        <section className="how-band" id="how">
          <div className="how-steps">
            <div className="how-step">
              <span className="how-num">1</span>
              <div>
                <h4>Job comes in</h4>
                <p>A STAT sample, transplant box or routine collection is logged by an operator or partner system.</p>
              </div>
            </div>
            <div className="how-step">
              <span className="how-num">2</span>
              <div>
                <h4>PulseGo plans</h4>
                <p>Local-first AI assigns the right courier and the fastest live path — cold-chain and capacity aware.</p>
              </div>
            </div>
            <div className="how-step">
              <span className="how-num">3</span>
              <div>
                <h4>It moves with purpose</h4>
                <p>The fleet re-plans around closures and delays in real time, every sample tracked to the door.</p>
              </div>
            </div>
          </div>
        </section>

        <section className="cta-band" id="about">
          <div>
            <h2 className="cta-band-title">Ready to move with purpose?</h2>
            <p className="cta-band-sub">
              Step into the live operations console and watch the fleet move.
            </p>
          </div>
          <Link className="site-btn primary" to={ctaHref}>
            {token ? "Open console →" : "Get started →"}
          </Link>
        </section>
      </main>

      <footer className="site-footer">
        <Logo className="small" />
        <span className="site-footer-tag">Move with purpose · live medical logistics for London · pulsego.org</span>
        <nav className="site-footer-links">
          <a href="#privacy">Privacy</a>
          <a href="#terms">Terms</a>
        </nav>
      </footer>
    </div>
  );
}
