from .common import VtkLocalView
from trame_vtk.modules.vtk import get_helper


def _inline_arrays(state, server, cache, sent_hashes=None, debug=False):
    """Inline array content into state for synchronous client rendering.

    Args:
        state: The VTK state dict to modify in-place
        server: Trame server for RPC calls
        cache: Dict to cache fetched array content (hash -> content)
        sent_hashes: Optional set of hashes already sent to client.
            If provided, only inlines arrays not in this set (bandwidth optimization).
            If None, inlines all arrays.
        debug: If True, print inlining statistics.
    """
    if not state or not server:
        return

    helper = get_helper(server)
    stats = {"inlined": 0, "skipped": 0, "total": 0}

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return

        data_hash = node.get("hash")
        if data_hash and node.get("dataType") and "content" not in node:
            stats["total"] += 1
            should_inline = sent_hashes is None or data_hash not in sent_hashes

            if should_inline:
                if data_hash not in cache:
                    # Use direct context access with binary=True (no base64 overhead)
                    content = helper.get_array_content(data_hash, binary=True) if helper else None
                    if content:
                        cache[data_hash] = content
                content = cache.get(data_hash)
                if content:
                    node["content"] = content
                    if sent_hashes is not None:
                        sent_hashes.add(data_hash)
                    stats["inlined"] += 1
            else:
                stats["skipped"] += 1

        for value in node.values():
            walk(value)

    walk(state)

    if debug and stats["total"] > 0:
        print(f"[ARRAYS] inlined={stats['inlined']} skipped={stats['skipped']} total={stats['total']}", flush=True)


class VtkSharedSyncView(VtkLocalView):
    """
    VtkSharedSyncView extends VtkLocalView for shared WebGL context rendering.

    Use this view when integrating VTK rendering with another WebGL library
    (like MapLibre, Three.js, etc.) that owns the WebGL context.
    """

    def __init__(self, view, ref=None, widgets=None, debug_arrays=False, **kwargs):
        super().__init__(view, ref=ref, widgets=widgets or [], **kwargs)
        self._elem_name = "vtk-shared-sync-view"
        self._inline_array_cache = {}
        self._sent_hashes = set()
        self._debug_arrays = debug_arrays

        self.server.controller.on_client_connected.add(self._on_client_connected)
        self._register_with_protocol()

    def _on_client_connected(self, **kwargs):
        """Send full state when client (re)connects."""
        self.request_resync()

    def _register_with_protocol(self):
        """Register with protocol for RPC-based resync."""
        view_id = self._helper.id(self._VtkLocalView__view)
        self._view_id = view_id
        self._helper.register_shared_sync_view(view_id, self)

    def request_resync(self, extra=None):
        """Request full state resync - clears tracking and publishes full state.

        Call this when the client needs full state (e.g., on mount, after
        browser sleep/wake, visibility change, or detected missing content).

        This publishes the full state with ALL arrays inlined via trame.vtk.delta.
        """
        self._sent_hashes.clear()

        if not self.server.protocol:
            return

        view = self._VtkLocalView__view

        # Get full state with ALL arrays inlined
        full_state = self._helper.scene(
            view,
            new_state=True,
            widgets=self._widgets,
            orientation_axis=0,
        )
        _inline_arrays(full_state, self.server, self._inline_array_cache, self._sent_hashes, debug=self._debug_arrays)
        if extra:
            full_state.setdefault("extra", {}).update(extra)

        # Publish via delta channel (client is subscribed to this)
        self.server.protocol.publish("trame.vtk.delta", full_state)

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
                debug=self._debug_arrays,
            )
        if extra:
            delta_state.setdefault("extra", {}).update(extra)
        self.server.protocol.publish("trame.vtk.delta", delta_state)

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
