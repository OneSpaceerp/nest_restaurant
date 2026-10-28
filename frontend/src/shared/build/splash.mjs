// Launch splash, inlined into each built PWA page by postbuild.mjs so it paints before any script loads.
// Its background is the surface's manifest background_color, so Android's native launch screen hands
// over to it without a flash. The logo is a data URI (no request). surface.ts dismissSplash() removes
// it once the app has mounted; a 10 s fail-safe removes it even if the bundle never runs.

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

export function splashHtml({ logoDataUri, name, tagline, background, publisher = 'nsdLabs' }) {
  const dark = luminance(background) < 0.4
  const ink = dark ? '#ffffff' : '#1e1d1d'
  const muted = dark ? 'rgb(255 255 255 / .72)' : 'rgb(30 29 29 / .66)'
  const track = dark ? 'rgb(255 255 255 / .16)' : 'rgb(30 29 29 / .12)'
  // a light surface follows the device's dark mode; brand-coloured surfaces keep their colour
  const followsScheme = !dark && luminance(background) > 0.85
  // The www page is a Jinja template: everything is raw except the translated tagline.
  const tag = `{% endraw %}{{ _("${tagline.replace(/"/g, '')}") }}{% raw %}`
  return `{% raw %}<div id="nest-splash" role="status" aria-label="${esc(name)}">
<style>
#nest-splash{position:fixed;inset:0;z-index:2147483000;display:grid;place-items:center;background:${background};color:${ink};font-family:"IBM Plex Sans","IBM Plex Sans Arabic",system-ui,-apple-system,"Segoe UI",sans-serif;transition:opacity .32s ease,visibility .32s;--ns-muted:${muted};--ns-track:${track}}
${followsScheme ? '@media (prefers-color-scheme:dark){#nest-splash{background:#141313;color:#fff;--ns-muted:rgb(255 255 255 / .7);--ns-track:rgb(255 255 255 / .16)}}' : ''}
#nest-splash .ns-stack{display:grid;justify-items:center;gap:20px;padding:24px;text-align:center}
#nest-splash .ns-tile{position:relative;width:112px;height:112px;border-radius:28px;overflow:hidden;box-shadow:0 18px 40px -12px rgb(0 0 0 / .35),0 2px 6px rgb(0 0 0 / .12);animation:ns-rise .62s cubic-bezier(.2,.9,.25,1.25) both}
#nest-splash .ns-tile img{display:block;width:100%;height:100%}
#nest-splash .ns-tile::after{content:"";position:absolute;inset:-40% 0;background:linear-gradient(180deg,transparent 0,rgb(255 255 255 / 0) 38%,rgb(255 255 255 / .5) 50%,rgb(255 255 255 / 0) 62%,transparent 100%);transform:translateY(-70%);animation:ns-sweep 1.1s .45s cubic-bezier(.45,0,.2,1) both}
#nest-splash .ns-halo{position:absolute;width:112px;height:112px;border-radius:28px;border:1.5px solid currentColor;opacity:0;animation:ns-halo 1.8s .6s ease-out infinite}
#nest-splash .ns-mark{position:relative;display:grid;place-items:center}
#nest-splash .ns-name{margin:0;font-size:26px;font-weight:700;letter-spacing:-.01em;animation:ns-up .5s .22s ease-out both}
#nest-splash .ns-tag{margin:-12px 0 0;font-size:15px;color:var(--ns-muted);animation:ns-up .5s .32s ease-out both}
#nest-splash .ns-bar{width:132px;height:3px;border-radius:3px;background:var(--ns-track);overflow:hidden;animation:ns-up .5s .42s ease-out both}
#nest-splash .ns-bar::before{content:"";display:block;width:40%;height:100%;border-radius:inherit;background:currentColor;animation:ns-load 1.15s .6s ease-in-out infinite}
#nest-splash .ns-by{position:absolute;inset-block-end:calc(24px + env(safe-area-inset-bottom));font-size:12px;letter-spacing:.06em;color:var(--ns-muted);animation:ns-up .5s .5s ease-out both}
#nest-splash.is-done{opacity:0;visibility:hidden}
#nest-splash.is-done .ns-tile{transform:scale(1.06);transition:transform .32s ease}
@keyframes ns-rise{from{opacity:0;transform:translateY(18px) scale(.82)}to{opacity:1;transform:none}}
@keyframes ns-sweep{to{transform:translateY(70%)}}
@keyframes ns-halo{0%{opacity:.22;transform:scale(1)}100%{opacity:0;transform:scale(1.28)}}
@keyframes ns-up{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes ns-load{0%{transform:translateX(-100%)}100%{transform:translateX(250%)}}
@media (prefers-reduced-motion:reduce){#nest-splash *,#nest-splash *::before,#nest-splash *::after{animation:ns-fade .3s ease-out both!important}#nest-splash .ns-tile::after,#nest-splash .ns-halo{display:none}#nest-splash .ns-bar::before{width:100%;opacity:.5}@keyframes ns-fade{from{opacity:0}to{opacity:1}}}
</style>
<div class="ns-stack">
<div class="ns-mark"><span class="ns-halo" aria-hidden="true"></span><div class="ns-tile"><img src="${logoDataUri}" alt="" width="112" height="112"></div></div>
<p class="ns-name">${esc(name)}</p>
<p class="ns-tag">${tag}</p>
<div class="ns-bar" aria-hidden="true"></div>
</div>
<p class="ns-by">${esc(publisher)}</p>
<script>setTimeout(function(){var s=document.getElementById('nest-splash');if(s){s.classList.add('is-done');setTimeout(function(){s.remove()},400)}},10000)</script>
</div>{% endraw %}`
}
