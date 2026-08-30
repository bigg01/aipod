"""Shared branding assets (kept tiny and inline so the scratch image needs no files)."""

# GTK / Adwaita-flavoured mark: an Adwaita-blue rounded tile with a white "pod"
# capsule holding two linked nodes - the agent and the server it talks to.
LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="40" height="40" '
    'role="img" aria-label="aipod">'
    '<defs><linearGradient id="aipod-g" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="#62a0ea"/><stop offset="1" stop-color="#3584e4"/>'
    "</linearGradient></defs>"
    '<rect x="2" y="2" width="60" height="60" rx="16" fill="url(#aipod-g)"/>'
    '<rect x="13" y="23" width="38" height="18" rx="9" fill="#ffffff" opacity="0.96"/>'
    '<circle cx="23" cy="32" r="4.5" fill="#3584e4"/>'
    '<circle cx="41" cy="32" r="4.5" fill="#1a5fb4"/>'
    '<path d="M23 32h18" stroke="#3584e4" stroke-width="2.5" stroke-linecap="round"/>'
    "</svg>"
)
