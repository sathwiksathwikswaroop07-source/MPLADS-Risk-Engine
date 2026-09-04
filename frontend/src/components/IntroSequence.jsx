import { useEffect, useRef } from "react";
import coinImage from "../assets/designer/ashoka-coin-clean.png";
import "../intro.css";

const MARKUP = `
  <div class="intro-root">
    <div class="grid"></div>
    <div class="glow"></div>
    <div id="particles"></div>

    <section class="screen active" data-screen="0">
      <div class="gov">
        <div class="gov-small">भारत सरकार</div>
        <h1>GOVERNMENT OF INDIA</h1>
        <div class="line"></div>
        <div class="sub">FOR A TRANSPARENT AND DEVELOPED INDIA</div>
      </div>
    </section>

    <section class="screen" data-screen="1">
      <div class="flagBackdrop"></div>
      <div class="emblemStage">
        <div class="flagGlow"></div>
        <div class="scan"></div>
        <img class="emblem" data-coin src="" alt="Ashoka emblem coin" />
        <div class="motto">
          <div class="hi">सत्यमेव जयते</div>
          <div class="en">TRUTH ALONE TRIUMPHS</div>
        </div>
      </div>
    </section>

    <section class="screen" data-screen="2">
      <div class="data orbit-scene">
        <div class="orbit orbit-main"></div>
        <div class="orbit orbit-inner"></div>
        <div class="coin-halo"></div>
        <div class="orbit-items">
          <div class="orbit-item oi1"><div class="orbit-card"><small>PROGRAMME</small><b>MPLADS</b></div></div>
          <div class="orbit-item oi2"><div class="orbit-card"><small>MONITORING</small><b>PROJECT DATA</b></div></div>
          <div class="orbit-item oi3"><div class="orbit-card"><small>ANALYSIS</small><b>COST & UTILISATION</b></div></div>
          <div class="orbit-item oi4"><div class="orbit-card"><small>EARLY WARNING</small><b>PROGRESS & DELAY</b></div></div>
          <div class="orbit-item oi5"><div class="orbit-card"><small>DETECTION</small><b>DUPLICATE / OVERLAP</b></div></div>
          <div class="orbit-item oi6"><div class="orbit-card"><small>ASSURANCE</small><b>HUMAN VERIFICATION</b></div></div>
        </div>
        <img class="orbit-logo" data-coin src="" alt="Ashoka emblem coin" />
        <div class="orbit-center-label">MPLADS RISK ENGINE<br><span>EXPLAINABLE · EVIDENCE-FIRST</span></div>
        <div class="caption">PROJECT DATA → ANALYSE → FLAG → VERIFY</div>
      </div>
    </section>

    <section class="screen" data-screen="3">
      <div class="title">
        <img data-coin src="" alt="Ashoka emblem coin" />
        <div class="mplads">MPLADS</div>
        <div class="name">MEMBERS OF PARLIAMENT LOCAL AREA DEVELOPMENT SCHEME</div>
        <div class="audit">AI-ASSISTED ANOMALY DETECTION</div>
      </div>
    </section>

    <section class="screen" data-screen="4">
      <div class="project">
        <div class="head">
          <span>WORK #DEMO-01 · ILLUSTRATIVE</span>
          <span class="scantext">● SCANNING PROJECT DATA</span>
        </div>
        <div class="box">
          <div class="pg">
            <div>
              <div class="work">Community infrastructure project</div>
              <div class="infos">
                <div class="info"><small>LOCATION</small><b>District / State</b></div>
                <div class="info"><small>ESTIMATED COST</small><b>Illustrative</b></div>
                <div class="info"><small>PROGRESS</small><b>46%</b></div>
                <div class="info"><small>STATUS</small><b>In Progress</b></div>
              </div>
            </div>
            <div class="checks">
              <div class="ct">AUTOMATED CHECKS</div>
              <div class="check good">✓ &nbsp; COST</div>
              <div class="check good">✓ &nbsp; PROGRESS</div>
              <div class="check bad">! &nbsp; DELAY</div>
              <div class="check bad">! &nbsp; DUPLICATE</div>
              <div class="check good">✓ &nbsp; COMPLIANCE</div>
              <div class="check good">✓ &nbsp; CITIZEN REPORT</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="screen" data-screen="5">
      <div class="risk">
        <div class="engine"><div class="core"><div class="ai">AI</div><small>ASSISTED<br>RISK ENGINE</small></div></div>
        <div class="riskcard"><div class="rl">ILLUSTRATIVE RISK SCORE</div><div class="score">45</div><div class="high">HIGH</div><div class="verify">Needs human verification</div></div>
      </div>
    </section>

    <section class="screen" data-screen="6">
      <div class="final">
        <img data-coin src="" alt="Ashoka emblem coin" />
        <h2>FIND THE WORKS<br>THAT NEED A <span>SECOND LOOK.</span></h2>
        <div class="sub">Explainable checks. Evidence attached. Human decision.</div>
        <div id="ctaWrap"><button type="button">Continue to sign in →</button></div>
      </div>
    </section>

    <button class="skip" type="button">SKIP INTRO</button>
    <div class="progress"><div class="bar"></div></div>
    <div class="pt">01 / 07</div>
  </div>
`;

export default function IntroSequence({ onContinue }) {
  const hostRef = useRef(null);

  useEffect(() => {
    const root = hostRef.current;
    if (!root) return undefined;

    const $ = (selector) => root.querySelector(selector);
    const $$ = (selector) => Array.from(root.querySelectorAll(selector));
    const screens = $$(".screen");
    const bar = $(".bar");
    const pt = $(".pt");
    const skip = $(".skip");
    const cta = $("#ctaWrap button");
    const coins = $$('[data-coin]');

    const img = coinImage;
    coins.forEach((el) => { el.src = img; });

    const particleHost = $("#particles");
    for (let i = 0; i < 70; i += 1) {
      const dot = document.createElement("div");
      dot.className = "particle-dot";
      dot.style.left = `${Math.random() * 100}%`;
      dot.style.top = `${Math.random() * 100}%`;
      dot.style.animationDuration = `${6 + Math.random() * 8}s`;
      dot.style.animationDelay = `${-Math.random() * 10}s`;
      particleHost.appendChild(dot);
    }

    let current = 0;
    let timer = 0;
    let locked = false;
    const durations = [3200, 4200, 6200, 4000, 5000, 4200, 999999];

    function show(index) {
      const next = Math.max(0, Math.min(index, screens.length - 1));
      current = next;
      screens.forEach((screen, i) => screen.classList.toggle("active", i === next));
      bar.style.width = `${((next + 1) / screens.length) * 100}%`;
      pt.textContent = `${String(next + 1).padStart(2, "0")} / ${String(screens.length).padStart(2, "0")}`;
      clearTimeout(timer);
      if (next < screens.length - 1) timer = window.setTimeout(() => show(next + 1), durations[next]);
    }

    function advance() {
      if (locked) return;
      if (current < screens.length - 1) show(current + 1);
    }

    function handleKey(event) {
      if (event.code === "Space" || event.code === "ArrowRight") {
        event.preventDefault();
        advance();
      } else if (event.code === "ArrowLeft") {
        event.preventDefault();
        show(current - 1);
      } else if (event.code === "Escape") {
        event.preventDefault();
        show(screens.length - 1);
      }
    }

    function handleWheel(event) {
      if (Math.abs(event.deltaY) < 24) return;
      if (event.deltaY > 0) advance();
      else show(current - 1);
    }

    function handleContinue(event) {
      event.preventDefault();
      locked = true;
      clearTimeout(timer);
      onContinue?.();
    }

    function handleClick(event) {
      if (event.target.closest("button")) return;
      if (event.target.closest(".screen")) advance();
    }

    window.addEventListener("keydown", handleKey);
    root.addEventListener("wheel", handleWheel, { passive: true });
    root.addEventListener("click", handleClick);
    cta?.addEventListener("click", handleContinue);
    skip?.addEventListener("click", () => show(screens.length - 1));

    show(0);

    return () => {
      clearTimeout(timer);
      window.removeEventListener("keydown", handleKey);
      root.removeEventListener("wheel", handleWheel);
      root.removeEventListener("click", handleClick);
      cta?.removeEventListener("click", handleContinue);
      particleHost.replaceChildren();
    };
  }, [onContinue]);

  return (
    <section
      ref={hostRef}
      className="intro-sequence"
      aria-label="MPLADS Risk Engine introduction"
      dangerouslySetInnerHTML={{ __html: MARKUP }}
    />
  );
}
