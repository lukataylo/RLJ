from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import landscape
from reportlab.pdfgen import canvas


OUT_DIR = Path(__file__).resolve().parent
PAGE = landscape((960, 540))
W, H = PAGE


SLIDES = [
    {
        "kicker": "Hack for Impact London | NVIDIA",
        "title": "RLJ",
        "subtitle": "Time-critical medical logistics for London.",
        "bullets": [
            "Urgent samples, medicines, couriers and road disruption in one live dispatch loop.",
            "Built for a local DGX Spark: patient data stays on the box.",
        ],
        "metric": "8 min",
        "metric_label": "target re-plan story",
    },
    {
        "kicker": "The problem",
        "title": "Clinical windows do not wait for traffic.",
        "subtitle": "London medical couriers operate inside constraints that ordinary routing tools ignore.",
        "bullets": [
            "STAT samples have stability windows.",
            "Courier capacity changes minute by minute.",
            "Closures, congestion and disruptions break static plans.",
            "Phones still matter: clinics and couriers need clear ETAs.",
        ],
        "metric": "95%+",
        "metric_label": "STAT window target",
    },
    {
        "kicker": "The answer",
        "title": "A local command center for urgent healthcare delivery.",
        "subtitle": "RLJ turns calls and live city signals into dispatch decisions, then explains them.",
        "bullets": [
            "Voice intake creates structured delivery jobs.",
            "Orchestrator keeps jobs, couriers, plans and events in sync.",
            "Routing re-optimizes when the city changes.",
            "Frontend shows the decision, not just the map.",
        ],
        "metric": "1 loop",
        "metric_label": "intake -> route -> notify",
    },
    {
        "kicker": "London data layer",
        "title": "Live city context, normalized into safe local records.",
        "subtitle": "The demo is not a canned map. It can ingest London open data and turn it into operational signals.",
        "bullets": [
            "TfL road disruptions -> route risk and closures.",
            "TfL BikePoint -> staging-point metadata.",
            "TfL line status -> city mobility risk narration.",
            "LondonAir + London Datastore -> public context and dataset discovery.",
        ],
        "metric": "5",
        "metric_label": "public-data adapters",
    },
    {
        "kicker": "Local-first architecture",
        "title": "Reason locally. Route locally. Reveal only what is needed.",
        "subtitle": "DGX Spark is the story: low latency, privacy, resilience and repeatable routing.",
        "bullets": [
            "Local Nemotron/NemoClaw reasoning and policy control.",
            "GPU routing with a built-in greedy fallback for demo safety.",
            "Orchestrator exposes REST + WebSocket contracts.",
            "ElevenLabs and TfL are allowlisted edges, not the core dependency.",
        ],
        "metric": "0",
        "metric_label": "patient-data cloud hops",
    },
    {
        "kicker": "Demo plan",
        "title": "Show the city breaking the plan, then RLJ fixing it live.",
        "subtitle": "The winning moment is visual, audible and measurable.",
        "bullets": [
            "1. Clinic calls in an urgent sample.",
            "2. RLJ creates the job and computes the plan.",
            "3. A road disruption lands from demo control or TfL.",
            "4. RLJ re-routes, updates the map and sends a voice notification.",
        ],
        "metric": "4 beats",
        "metric_label": "clear judge narrative",
    },
    {
        "kicker": "Verification",
        "title": "No self-grading. Claims only count when tests pass.",
        "subtitle": "The project now has objective gates for the story it tells on stage.",
        "bullets": [
            "make quality-gate runs the Python verification ledger.",
            "Frontend TypeScript/Vite build is part of the gate.",
            "GitHub Actions repeats the gate for PRs.",
            "Current ledger: 14/14 must-pass checks green, 16/16 claims verified.",
        ],
        "metric": "16/16",
        "metric_label": "verified claims",
    },
    {
        "kicker": "Why it can win",
        "title": "It feels like a real operating system for London healthcare.",
        "subtitle": "Judges remember concrete pressure: a patient-critical delivery, a blocked road, a local AI decision, a live ETA call.",
        "bullets": [
            "High-impact problem with obvious urgency.",
            "NVIDIA/local-first angle is central, not decorative.",
            "Live data makes the demo feel connected to London.",
            "Quality gates make the pitch credible under questioning.",
        ],
        "metric": "win",
        "metric_label": "if demo lands cleanly",
    },
]


VARIANTS = {
    "01_apple_orange": {
        "name": "Apple Orange",
        "bg": "#f7f5f0",
        "fg": "#101010",
        "muted": "#5b5b5b",
        "soft": "#e8e2d8",
        "accent": "#ff6a00",
        "accent2": "#111111",
    },
    "02_midnight_ops": {
        "name": "Midnight Ops",
        "bg": "#080808",
        "fg": "#f7f5f0",
        "muted": "#b5b0a8",
        "soft": "#222222",
        "accent": "#ff7a00",
        "accent2": "#ffffff",
    },
    "03_judge_minimal": {
        "name": "Judge Minimal",
        "bg": "#ffffff",
        "fg": "#111111",
        "muted": "#666666",
        "soft": "#eeeeee",
        "accent": "#f05a00",
        "accent2": "#111111",
    },
}


def col(value):
    return HexColor(value)


def wrap(text, width, font_size):
    max_chars = max(22, int(width / (font_size * 0.48)))
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if len(test) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def text_block(c, text, x, y, width, size, color, leading=None, font="Helvetica"):
    c.setFillColor(col(color))
    c.setFont(font, size)
    leading = leading or size * 1.18
    for line in wrap(text, width, size):
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_marker(c, x, y, text, style):
    c.setFillColor(col(style["accent"]))
    c.roundRect(x, y, 92, 28, 14, fill=1, stroke=0)
    c.setFillColor(col(style["bg"]))
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x + 46, y + 9, text)


def draw_route(c, style, slide_no):
    c.setStrokeColor(col(style["soft"]))
    c.setLineWidth(8)
    c.line(610, 388, 852, 388)
    c.line(852, 388, 852, 222)
    c.line(852, 222, 642, 222)
    c.setStrokeColor(col(style["accent"]))
    c.setLineWidth(8)
    c.line(610, 388, 740 + slide_no * 6, 388)
    c.circle(610, 388, 9, stroke=0, fill=1)
    c.circle(852, 222, 9, stroke=0, fill=1)
    c.setFillColor(col(style["accent"]))
    c.setFont("Helvetica-Bold", 18)
    c.drawString(768, 377, "->")
    draw_marker(c, 604, 410, "CLINIC", style)
    draw_marker(c, 800, 184, "LAB", style)
    c.setStrokeColor(col(style["accent"]))
    c.setLineWidth(2)
    c.rect(690, 286, 126, 38, stroke=1, fill=0)
    c.setFillColor(col(style["accent"]))
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(753, 300, "ROAD CLOSED")


def draw_slide(c, slide, index, style):
    c.setFillColor(col(style["bg"]))
    c.rect(0, 0, W, H, fill=1, stroke=0)

    c.setFillColor(col(style["accent"]))
    c.rect(0, 0, 18, H, fill=1, stroke=0)
    c.setFillColor(col(style["fg"]))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(56, 500, f"{index:02d} / 08")
    c.setFillColor(col(style["muted"]))
    c.setFont("Helvetica", 10)
    c.drawRightString(904, 500, f"RLJ Pitch | {style['name']}")

    c.setFillColor(col(style["accent"]))
    c.setFont("Helvetica-Bold", 12)
    c.drawString(56, 455, slide["kicker"].upper())

    title_size = 60 if len(slide["title"]) < 30 else 48
    y = text_block(c, slide["title"], 56, 410, 520, title_size, style["fg"], title_size * 1.02, "Helvetica-Bold")
    y -= 16
    y = text_block(c, slide["subtitle"], 60, y, 500, 20, style["muted"], 26)

    bullet_y = 192
    for bullet in slide["bullets"]:
        c.setFillColor(col(style["accent"]))
        c.circle(70, bullet_y + 5, 4, fill=1, stroke=0)
        bullet_y = text_block(c, bullet, 88, bullet_y, 458, 16, style["fg"], 22)
        bullet_y -= 5

    c.setFillColor(col(style["accent"]))
    c.roundRect(620, 62, 258, 124, 28, fill=1, stroke=0)
    c.setFillColor(col(style["bg"]))
    metric_size = 50 if len(slide["metric"]) < 6 else 40
    c.setFont("Helvetica-Bold", metric_size)
    c.drawCentredString(749, 116, slide["metric"])
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(749, 88, slide["metric_label"].upper())

    draw_route(c, style, index)


def build_pdf(filename, style):
    c = canvas.Canvas(str(OUT_DIR / filename), pagesize=PAGE)
    c.setTitle("RLJ Hackathon Pitch")
    c.setAuthor("RLJ")
    c.setSubject("8-slide hackathon pitch deck")
    for i, slide in enumerate(SLIDES, start=1):
        draw_slide(c, slide, i, style)
        c.showPage()
    c.save()


def main():
    for slug, style in VARIANTS.items():
        build_pdf(f"rlj_pitch_{slug}.pdf", style)


if __name__ == "__main__":
    main()
