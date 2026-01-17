from .common import VtkLocalView


def _inline_arrays(state, server, cache, sent_hashes=None):
    """Inline array content into state for synchronous client rendering.

    Args:
        state: The VTK state dict to modify in-place
        server: Trame server for RPC calls
        cache: Dict to cache fetched array content (hash -> content)
        sent_hashes: Optional set of hashes already sent to client.
            If provided, only inlines arrays not in this set (bandwidth optimization).
            If None, inlines all arrays.
    """
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
            should_inline = sent_hashes is None or data_hash not in sent_hashes

            if should_inline:
                if data_hash not in cache:
                    try:
                        cache[data_hash] = server.protocol_call(
                            "viewport.geometry.array.get", data_hash, False
                        )
                    except Exception:
                        pass
                content = cache.get(data_hash)
                if content:
                    node["content"] = content
                    if sent_hashes is not None:
                        sent_hashes.add(data_hash)

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
        self._sent_hashes = set()

        self.server.controller.on_client_connected.add(self._on_client_connected)

    def _on_client_connected(self, **kwargs):
        """Clear sent hashes when client reconnects so full state is sent."""
        self._sent_hashes.clear()

    def request_resync(self):
        """Clear sent hashes to force full array inlining on next update.

        Call this when the client may have lost cached arrays (e.g., after
        browser sleep/wake, visibility change, or detected missing content).
        """
        self._sent_hashes.clear()

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

        Args:
            inline_arrays: If True, inline array content in the state.
                Uses hash tracking to skip arrays already sent to client.
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
            _inline_arrays(
                delta_state,
                self.server,
                self._inline_array_cache,
                self._sent_hashes,
            )
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
            # Full state must have ALL arrays for client refresh/reconnect
            _inline_arrays(full_state, self.server, self._inline_array_cache, None)
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
