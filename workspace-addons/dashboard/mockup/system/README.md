# mockup/system moved

The shared design system is no longer kept here. The one master is
`workspace/src/orch_ui/static/` (tokens, components, widgets, motion, previews, the living style guide
`gallery.html` and the rules in `DESIGN.md`). Mockup pages link those files by relative path, for example
`../../../../workspace/src/orch_ui/static/components.css`. Do not add stylesheets or scripts to the mockup folder:
add the component to the master with a gallery entry, then use it here.
