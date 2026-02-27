import copy

from .common import VtkLocalView
from trame_vtk.modules.vtk import get_helper


def _inline_arrays(state, server, cache, debug=False):
    """Inline array content into state for synchronous client rendering.

    Every array node gets content inlined (vtk.js synchronous path requires it).

    Args:
        state: The VTK state dict to modify in-place
        server: Trame server for RPC calls
        cache: Dict to cache fetched array content (hash -> content)
        debug: If True, print inlining statistics.
    """
    if not state or not server:
        return

    helper = get_helper(server)
    stats = {"inlined": 0, "missing": 0, "total": 0}

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
            if data_hash not in cache:
                content = (
                    helper.get_array_content(data_hash, binary=False)
                    if helper
                    else None
                )
                if content:
                    cache[data_hash] = content
            content = cache.get(data_hash)
            if content:
                node["content"] = content
                stats["inlined"] += 1
            else:
                stats["missing"] += 1

        for value in node.values():
            walk(value)

    walk(state)

    if debug and stats["total"] > 0:
        print(
            f"[ARRAYS] inlined={stats['inlined']} missing={stats['missing']} total={stats['total']}",
            flush=True,
        )


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
        self._debug_arrays = debug_arrays

        self._register_with_protocol()
        self.server.controller.on_server_ready.add(self._set_initial_view_state)

    def _register_with_protocol(self):
        """Register with protocol for RPC-based resync."""
        view_id = self._helper.id(self._VtkLocalView__view)
        self._view_id = view_id
        self._helper.register_shared_sync_view(view_id, self)

    def _set_initial_view_state(self, **_kwargs):
        """Set viewState so JS knows the render window ID at mount time."""
        full_state = self._helper.scene(
            self._VtkLocalView__view,
            new_state=True,
            widgets=self._widgets,
            orientation_axis=0,
        )
        self.server.state[self._VtkLocalView__scene_id] = full_state

    def get_resync_state(self, extra=None):
        """Build and return the full resync state without publishing."""
        if not self.server.protocol:
            return None

        view = self._VtkLocalView__view

        prop_state = self._helper.scene(
            view,
            new_state=True,
            widgets=self._widgets,
            orientation_axis=0,
        )
        self.server.state[self._VtkLocalView__scene_id] = prop_state

        full_state = self._helper.scene(
            view,
            new_state=True,
            widgets=self._widgets,
            orientation_axis=0,
        )
        _inline_arrays(
            full_state, self.server, self._inline_array_cache, debug=self._debug_arrays
        )
        if extra:
            full_state.setdefault("extra", {}).update(extra)
        return full_state

    def request_resync(self, extra=None):
        """Build full state and broadcast via trame.vtk.delta.

        Used for visibility-change recovery where all clients need resyncing.
        """
        full_state = self.get_resync_state(extra)
        if full_state:
            self.server.protocol.publish("trame.vtk.delta", copy.deepcopy(full_state))

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
                debug=self._debug_arrays,
            )
        if extra:
            delta_state.setdefault("extra", {}).update(extra)
        self.server.protocol.publish("trame.vtk.delta", copy.deepcopy(delta_state))

    def render_shared(self, options=None, **kwargs):
        """Render VTK in shared context mode (host render loop)."""
        self.server.js_call(self._VtkLocalView__ref, "renderShared", options or {})

    def initialize_for_shared_context(self, **kwargs):
        """Initialize the view for shared WebGL context."""
        self.server.js_call(self._VtkLocalView__ref, "initializeForSharedContext")

    def on_render_requested(self, callback_name, **kwargs):
        """Forward VTK render requests to the host."""
        self.server.js_call(self._VtkLocalView__ref, "onRenderRequested", callback_name)

    def set_size(self, width, height, **kwargs):
        """Set render size (useful for external context mode)."""
        self.server.js_call(self._VtkLocalView__ref, "setSize", width, height)
