from .common import VtkLocalView


def _inline_arrays_in_state(state, server, cache):
    if not state or not server:
        return

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return

        data_hash = node.get("hash")
        if data_hash and node.get("dataType") and "content" not in node:
            if data_hash not in cache:
                cache[data_hash] = server.protocol_call(
                    "viewport.geometry.array.get", data_hash, False
                )
            node["content"] = cache[data_hash]

        for value in node.values():
            walk(value)

    walk(state)


class VtkSharedSyncView(VtkLocalView):
    """
    VtkSharedSyncView extends VtkLocalView for shared WebGL context rendering.

    Use this view when integrating VTK rendering with another WebGL library
    (like MapLibre, Three.js, etc.) that owns the WebGL context.
    """

    def __init__(self, view, ref=None, widgets=None, **kwargs):
        super().__init__(view, ref=ref, widgets=widgets or [], **kwargs)
        self._elem_name = "vtk-shared-sync-view"
        self._inline_array_cache = {}

    def update(
        self,
        widgets=None,
        orientation_axis=0,
        inline_arrays=False,
        extra=None,
        **kwargs,
    ):
        """
        Force geometry to be pushed (with optional inline arrays + extra).
        """
        if widgets is None:
            widgets = self._widgets

        if not self.server.protocol:
            return

        view = self._VtkLocalView__view

        delta_state = self._helper.scene(
            view,
            new_state=False,
            widgets=widgets,
            orientation_axis=orientation_axis,
        )
        if inline_arrays:
            _inline_arrays_in_state(delta_state, self.server, self._inline_array_cache)
        if extra:
            delta_state.setdefault("extra", {}).update(extra)
        self.server.protocol.publish("trame.vtk.delta", delta_state)

        full_state = self._helper.scene(
            view,
            new_state=True,
            widgets=widgets,
            orientation_axis=orientation_axis,
        )
        if inline_arrays:
            _inline_arrays_in_state(full_state, self.server, self._inline_array_cache)
        if extra:
            full_state.setdefault("extra", {}).update(extra)
        self.server.state[self._VtkLocalView__scene_id] = full_state

    def render_shared(self, options=None, **kwargs):
        """Render VTK in shared context mode (host render loop)."""
        self.server.js_call(self._VtkLocalView__ref, "renderShared", options or {})

    def initialize_for_shared_context(self, **kwargs):
        """Initialize the view for shared WebGL context."""
        self.server.js_call(self._VtkLocalView__ref, "initializeForSharedContext")

    def on_render_requested(self, callback_name, **kwargs):
        """Forward VTK render requests to the host."""
        self.server.js_call(self._VtkLocalView__ref, "onRenderRequested", callback_name)

    def trigger_render(self, **kwargs):
        """Trigger a render (useful for external context mode)."""
        self.server.js_call(self._VtkLocalView__ref, "triggerRender")

    def set_size(self, width, height, **kwargs):
        """Set render size (useful for external context mode)."""
        self.server.js_call(self._VtkLocalView__ref, "setSize", width, height)
