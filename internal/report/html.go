package report

import (
	"fmt"
	"html"
	"strings"

	"github.com/aidun/wowcoach/internal/domain"
)

func RenderHTML(result domain.AnalysisResult) string {
	var b strings.Builder
	b.WriteString(`<!doctype html><html lang="en"><head><meta charset="utf-8">`)
	b.WriteString(`<meta name="viewport" content="width=device-width, initial-scale=1">`)
	b.WriteString(`<title>WoW Coach Report</title>`)
	b.WriteString(`<style>
body{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;background:#0a0f17;color:#eff4fb;margin:0;padding:40px}
.wrap{max-width:1100px;margin:0 auto}
.hero{display:grid;grid-template-columns:2fr 1fr;gap:24px;margin-bottom:32px}
.pane{background:#111826;border:1px solid #273248;border-radius:20px;padding:24px}
.scores{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:16px}
.score{padding:16px;border-radius:16px;background:#0c1320;border:1px solid #273248}
.findings,.timeline,.sections{display:grid;gap:16px}
.finding{padding:18px;border-left:4px solid #d6ae52;background:#111826;border-radius:14px}
.severity-major{border-color:#ff6a3d}.severity-moderate{border-color:#d6ae52}.severity-minor{border-color:#6ad0ff}
h1,h2,h3,p{margin:0 0 10px} ul{margin:0;padding-left:18px} li{margin:0 0 8px}
</style></head><body><div class="wrap">`)
	b.WriteString(`<section class="hero">`)
	b.WriteString(`<div class="pane">`)
	b.WriteString(fmt.Sprintf(`<h1>%s</h1>`, html.EscapeString(result.Summary.FightName)))
	b.WriteString(fmt.Sprintf(`<p>%s · %s · %s</p>`, html.EscapeString(result.Summary.ActorName), html.EscapeString(result.Summary.SpecName), html.EscapeString(result.Summary.ContentSource)))
	b.WriteString(fmt.Sprintf(`<p>Duration %.0fs · %d casts</p>`, result.Summary.Duration, result.Summary.TotalCasts))
	b.WriteString(`</div><div class="pane"><div class="scores">`)
	for _, score := range result.Scores {
		b.WriteString(fmt.Sprintf(`<div class="score"><strong>%s</strong><div>%.0f / %.0f</div><small>%s</small></div>`,
			html.EscapeString(score.Label), score.Value, score.Max, html.EscapeString(score.Detail)))
	}
	b.WriteString(`</div></div></section>`)

	b.WriteString(`<section class="pane findings"><h2>Major Findings</h2>`)
	if len(result.Findings) == 0 {
		b.WriteString(`<p>No major findings were generated for this fight.</p>`)
	}
	for _, finding := range result.Findings {
		b.WriteString(fmt.Sprintf(`<article class="finding severity-%s"><h3>%s</h3><p>%s</p><p><strong>Recommendation:</strong> %s</p></article>`,
			html.EscapeString(finding.Severity), html.EscapeString(finding.Title), html.EscapeString(finding.Explanation), html.EscapeString(finding.Recommendation)))
	}
	b.WriteString(`</section>`)

	b.WriteString(`<section class="sections" style="margin-top:24px">`)
	for _, section := range result.Sections {
		b.WriteString(`<article class="pane">`)
		b.WriteString(fmt.Sprintf(`<h2>%s</h2><p>%s</p><ul>`, html.EscapeString(section.Title), html.EscapeString(section.Summary)))
		for _, line := range section.Lines {
			b.WriteString(fmt.Sprintf(`<li>%s</li>`, html.EscapeString(line)))
		}
		b.WriteString(`</ul></article>`)
	}
	b.WriteString(`</section>`)

	b.WriteString(`<section class="pane timeline" style="margin-top:24px"><h2>Timeline</h2><ul>`)
	for _, item := range result.Timeline {
		b.WriteString(fmt.Sprintf(`<li><strong>%s</strong> · %s</li>`, html.EscapeString(item.Timestamp), html.EscapeString(item.Label)))
	}
	b.WriteString(`</ul></section>`)

	b.WriteString(`</div></body></html>`)
	return b.String()
}
