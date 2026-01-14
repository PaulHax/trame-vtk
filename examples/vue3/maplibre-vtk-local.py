"""
MapLibre + VTK Shared View Integration Example

This example demonstrates how to use VtkSharedView with an external WebGL context
shared with MapLibre GL JS. VTK renders 3D cones at geographic city locations.

Sync Mode Comparison:
- Sync mode (default): State applied atomically at render time, smooth animation
- Async mode: State applied asynchronously, may cause jitter during animation

Use URL parameter ?sync=false to use async mode. The toggle button reloads the page.

Camera control uses imperative API:
- Python calls set_map_camera() to control MapLibre camera
- Python calls get_map_camera() to query current camera position
"""

import math
import asyncio
import time
from urllib.parse import quote as url_quote

from trame.app import get_server


def lng_lat_to_mercator(lng, lat, alt=0):
    """Convert lng/lat/alt to MapLibre Mercator coordinates (0-1 range)."""
    x = (lng + 180) / 360
    sin_lat = math.sin(math.radians(lat))
    y = 0.5 - 0.25 * math.log((1 + sin_lat) / (1 - sin_lat)) / math.pi
    meters_per_unit = math.cos(math.radians(lat)) * 2 * math.pi * 6378137
    scale = 1 / meters_per_unit
    z = alt * scale
    return x, y, z, scale


from trame.widgets import vtk as vtk_widgets, html, vuetify3
from trame.ui.vuetify3 import SinglePageLayout

from vtkmodules.vtkFiltersSources import vtkConeSource
from vtkmodules.vtkRenderingCore import (
    vtkRenderer,
    vtkRenderWindow,
    vtkRenderWindowInteractor,
    vtkPolyDataMapper,
    vtkActor,
)

from vtkmodules.vtkInteractionStyle import vtkInteractorStyleSwitch  # noqa
import vtkmodules.vtkRenderingOpenGL2  # noqa

server = get_server()
server.client_type = "vue3"
state, ctrl = server.state, server.controller

# Default to sync mode
state.sync_mode = True
state.camera_mode = "orbit"  # "orbit", "new_york", "chicago", "denver", "fit_all"
state.trame__title = "MapLibre + VTK Geo Cones"

# City data with coordinates
CITIES = [
    {"name": "New York", "lng": -74.006, "lat": 40.7128, "color": (1.0, 0.5, 0.0)},
    {"name": "Chicago", "lng": -87.6298, "lat": 41.8781, "color": (0.5, 1.0, 0.0)},
    {"name": "Denver", "lng": -104.9903, "lat": 39.7392, "color": (0.0, 0.5, 1.0)},
]


# Imperative camera control API
def set_map_camera(center, zoom, bearing=0, pitch=0, animate=True, duration=1000):
    """Set MapLibre camera position from Python."""
    server.js_call("mapController", "setCamera", {
        "center": center,
        "zoom": zoom,
        "bearing": bearing,
        "pitch": pitch,
        "animate": animate,
        "duration": duration,
    })


def fit_map_bounds(bounds, padding=100, animate=True):
    """Fit map to bounds. bounds = [[west, south], [east, north]]"""
    server.js_call("mapController", "fitBounds", bounds, padding, animate)


@server.trigger("map_camera_response")
def on_map_camera_response(camera):
    """Called by JS when camera is requested."""
    print(f"Map camera: center={camera['center']}, zoom={camera['zoom']:.2f}, "
          f"bearing={camera['bearing']:.1f}, pitch={camera['pitch']:.1f}", flush=True)


def get_map_camera():
    """Request current camera from JS (response via trigger)."""
    server.js_call("mapController", "getCamera")


# Button handlers
def focus_city(city_name):
    city = next((c for c in CITIES if c["name"] == city_name), None)
    if city:
        set_map_camera(
            center=[city["lng"], city["lat"]],
            zoom=8,
            bearing=0,
            pitch=0,
        )
        print(f"Flying to {city_name}", flush=True)


def fit_all_cities():
    bounds = [
        [min(c["lng"] for c in CITIES), min(c["lat"] for c in CITIES)],
        [max(c["lng"] for c in CITIES), max(c["lat"] for c in CITIES)],
    ]
    fit_map_bounds(bounds, padding=100)
    print("Fitting all cities", flush=True)


def print_camera():
    get_map_camera()


@state.change("camera_mode")
def on_camera_mode_change(camera_mode, **kwargs):
    if camera_mode == "new_york":
        focus_city("New York")
    elif camera_mode == "chicago":
        focus_city("Chicago")
    elif camera_mode == "denver":
        focus_city("Denver")
    elif camera_mode == "fit_all":
        fit_all_cities()


# VTK setup
renderer = vtkRenderer()
renderer.SetBackground(0, 0, 0)
renderer.SetBackgroundAlpha(0)

renderWindow = vtkRenderWindow()
renderWindow.AddRenderer(renderer)
renderWindow.OffScreenRenderingOn()

renderWindowInteractor = vtkRenderWindowInteractor()
renderWindowInteractor.SetRenderWindow(renderWindow)
renderWindowInteractor.GetInteractorStyle().SetCurrentStyleToTrackballCamera()

cone_actors = []
cone_base_scales = []

for city in CITIES:
    x, y, z, scale = lng_lat_to_mercator(city["lng"], city["lat"])
    cone_scale = scale * 100000  # 100km cones

    cone_source = vtkConeSource()
    cone_source.SetHeight(1.0)
    cone_source.SetRadius(0.5)
    cone_source.SetDirection(0, 0, 1)
    mapper = vtkPolyDataMapper()
    mapper.SetInputConnection(cone_source.GetOutputPort())
    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*city["color"])
    actor.SetPosition(x, y, cone_scale * 0.5)
    actor.SetScale(cone_scale, cone_scale, cone_scale)
    renderer.AddActor(actor)
    cone_actors.append(actor)
    cone_base_scales.append(cone_scale)

renderer.ResetCamera()
renderWindow.Render()


animation_task = None

# Orbit center: midpoint between Denver and New York
ORBIT_CENTER = [
    (CITIES[0]["lng"] + CITIES[2]["lng"]) / 2,  # NY + Denver
    (CITIES[0]["lat"] + CITIES[2]["lat"]) / 2,
]
ORBIT_RADIUS = 8  # degrees
ORBIT_ZOOM = 7
ORBIT_PITCH = 0

# Create a center marker that follows the camera
from vtkmodules.vtkFiltersSources import vtkSphereSource
center_x, center_y, _, center_scale = lng_lat_to_mercator(ORBIT_CENTER[0], ORBIT_CENTER[1])
sphere_source = vtkSphereSource()
sphere_source.SetRadius(0.5)
sphere_source.SetThetaResolution(32)
sphere_source.SetPhiResolution(32)
center_mapper = vtkPolyDataMapper()
center_mapper.SetInputConnection(sphere_source.GetOutputPort())
center_actor = vtkActor()
center_actor.SetMapper(center_mapper)
center_actor.GetProperty().SetColor(1.0, 0.0, 0.0)  # red
center_actor.GetProperty().SetAmbient(1.0)  # fully ambient lit
center_actor.GetProperty().SetDiffuse(0.0)
center_actor.SetScale(center_scale * 50000, center_scale * 50000, center_scale * 50000)
renderer.AddActor(center_actor)


async def animate_cones():
    """Animate cone scales and orbit camera to show sync difference."""
    start_time = time.time()
    while True:
        t = time.time() - start_time

        # Cone pulsing animation
        scale_factor = 1.0 + 0.3 * math.sin(t * 4)
        for actor, base_scale in zip(cone_actors, cone_base_scales):
            current_scale = base_scale * scale_factor
            x, y, z = actor.GetPosition()
            actor.SetScale(current_scale, current_scale, current_scale)
            actor.SetPosition(x, y, current_scale * 0.5)

        # Camera orbit animation - complete circle every 20 seconds
        if state.camera_mode == "orbit":
            orbit_speed = 2 * math.pi / 20
            angle = t * orbit_speed
            camera_lng = ORBIT_CENTER[0] + ORBIT_RADIUS * math.cos(angle)
            camera_lat = ORBIT_CENTER[1] + ORBIT_RADIUS * math.sin(angle) * 0.5  # ellipse

            # Move center marker to follow camera center
            marker_x, marker_y, _, marker_scale = lng_lat_to_mercator(camera_lng, camera_lat)
            marker_size = marker_scale * 50000
            center_actor.SetPosition(marker_x, marker_y, marker_size * 0.5)
            center_actor.SetScale(marker_size, marker_size, marker_size)

            # Pass camera with VTK state so they arrive together
            ctrl.view_update(extra={
                "orbitCamera": {
                    "center": [camera_lng, camera_lat],
                    "zoom": ORBIT_ZOOM,
                    "bearing": 0,
                    "pitch": ORBIT_PITCH,
                }
            })
        else:
            ctrl.view_update()

        server.js_call("mapController", "triggerRepaint")
        await asyncio.sleep(1 / 60)  # 60fps updates


@server.trigger("start_animation")
def start_animation():
    global animation_task
    if animation_task is None:
        animation_task = asyncio.create_task(animate_cones())


# MapLibre CDN
maplibre_module = {
    "scripts": ["https://unpkg.com/maplibre-gl@5.16.0/dist/maplibre-gl.js"],
    "styles": ["https://unpkg.com/maplibre-gl@5.16.0/dist/maplibre-gl.css"],
}
server.enable_module(maplibre_module)

# JavaScript initialization - reads sync mode from URL param
INIT_SCRIPT_JS = """
(function() {
    let initialized = false;
    let map = null;
    let pendingOrbitCamera = null;  // Camera target to apply at render time

    // Set up state change callback early (before component ready)
    window.onVtkViewStateChange = (state) => {
        console.log('[VTK] viewStateChange:', state?.extra);
        if (state?.extra?.orbitCamera) {
            pendingOrbitCamera = state.extra.orbitCamera;
            console.log('[VTK] Set pendingOrbitCamera:', pendingOrbitCamera);
        }
    };

    // Parse URL param for sync mode (default to true)
    const urlParams = new URLSearchParams(window.location.search);
    const syncMode = urlParams.get('sync') !== 'false';

    // Register map controller for Python to call
    window.trame = window.trame || {};
    window.trame.refs = window.trame.refs || {};
    window.trame.refs.mapController = {
        setCamera({ center, zoom, bearing = 0, pitch = 0, animate = true, duration = 1000 }) {
            if (!map) return;
            const options = { center, zoom, bearing, pitch };
            if (animate) {
                map.flyTo({ ...options, duration });
            } else {
                map.jumpTo(options);
            }
        },
        fitBounds(bounds, padding = 100, animate = true) {
            if (!map) return;
            map.fitBounds(bounds, { padding, animate });
        },
        getCamera() {
            if (!map) return;
            const center = map.getCenter();
            const camera = {
                center: [center.lng, center.lat],
                zoom: map.getZoom(),
                bearing: map.getBearing(),
                pitch: map.getPitch()
            };
            window.trame.trigger('map_camera_response', [camera]);
        },
        triggerRepaint() {
            if (map) map.triggerRepaint();
        },
        toggleSyncMode() {
            const newMode = !syncMode;
            const url = new URL(window.location);
            url.searchParams.set('sync', newMode);
            window.location.href = url.toString();
        },
        getSyncMode() {
            return syncMode;
        }
    };

    window.initMapLibreVTK = async function() {
        if (initialized) return;

        const vtkViewRef = window.trame?.refs?.['vtkView'];
        const vtkView = vtkViewRef?.initializeForSharedContext ? vtkViewRef :
                        vtkViewRef?.$.exposed ? vtkViewRef.$.exposed :
                        vtkViewRef?.$.setupState;

        if (!vtkView?.initializeForSharedContext || !window.maplibregl) {
            setTimeout(window.initMapLibreVTK, 100);
            return;
        }

        initialized = true;
        console.log('[MapLibre+VTK] Initializing with syncStateAtRender:', syncMode);

        map = new maplibregl.Map({
            container: 'map-container',
            style: {
                version: 8,
                sources: {
                    osm: {
                        type: 'raster',
                        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
                        tileSize: 256,
                        attribution: '© OpenStreetMap contributors'
                    }
                },
                layers: [{
                    id: 'osm',
                    type: 'raster',
                    source: 'osm'
                }]
            },
            center: [-90, 40],
            zoom: 4,
            antialias: true
        });

        await new Promise(resolve => map.on('load', resolve));

        // Route VTK render requests through MapLibre's render loop
        vtkView.onRenderRequested(() => {
            map.triggerRepaint();
        });

        const renderer = vtkView.getRenderWindow().getRenderersByReference()[0];

        map.fitBounds([[-104.9903, 39.7392], [-74.006, 41.8781]], { padding: 100 });

        const vtkLayer = {
            id: 'vtk-cones',
            type: 'custom',
            renderingMode: '3d',
            onAdd: function(mapInstance, gl) {
                const canvas = mapInstance.getCanvas();
                // syncStateAtRender option: queue state when it arrives, apply at render time
                const options = syncMode ? { syncStateAtRender: true } : {};
                vtkView.initializeForSharedContext(canvas, gl, options);
                console.log('[MapLibre+VTK] Initialized shared context with options:', options);
            },
            render: function(gl, args) {
                if (!renderer) return;

                // First apply VTK state (geometry updates) without rendering
                vtkView.renderShared({ skipRender: true });

                // Then apply camera - now geometry and camera are synced
                if (pendingOrbitCamera) {
                    map.jumpTo({
                        center: pendingOrbitCamera.center,
                        zoom: pendingOrbitCamera.zoom,
                        bearing: pendingOrbitCamera.bearing,
                        pitch: pendingOrbitCamera.pitch,
                    });
                    pendingOrbitCamera = null;
                }

                // Get fresh projection matrix after camera update
                const projData = map.transform.getProjectionDataForCustomLayer?.() || args.defaultProjectionData;
                const projMatrix = projData.mainMatrix;

                const camera = renderer.getActiveCamera();
                const identity = new Float64Array([
                    1, 0, 0, 0,
                    0, 1, 0, 0,
                    0, 0, 1, 0,
                    0, 0, 0, 1
                ]);
                camera.setViewMatrix(identity);
                camera.setProjectionMatrix(projMatrix);
                camera.modified();

                // Now render with synced geometry and camera
                vtkView.getRenderWindow().getViews()[0]?.renderShared?.({});
            }
        };

        map.addLayer(vtkLayer);

        // Update title to show current mode
        document.title = syncMode ?
            'MapLibre + VTK (SYNC mode)' :
            'MapLibre + VTK (ASYNC mode)';

        window.trame.trigger('start_animation');
    };
})();
"""

server.enable_module({"scripts": [f"data:text/javascript,{url_quote(INIT_SCRIPT_JS)}"]})


server.enable_module({
    "styles": ["data:text/css,html { overflow-y: hidden !important; }"]
})

with SinglePageLayout(server) as layout:
    layout.title.set_text("MapLibre + VTK Geo Cones")

    with layout.toolbar:
        vuetify3.VSwitch(
            v_model=("sync_mode",),
            label=("sync_mode ? 'Sync' : 'Async'",),
            color="success",
            hide_details=True,
            density="compact",
            change="window.trame.refs.mapController.toggleSyncMode()",
            classes="mr-4",
        )
        vuetify3.VDivider(vertical=True, classes="mx-2")
        with vuetify3.VBtnToggle(
            v_model=("camera_mode",),
            mandatory=True,
            density="compact",
            color="primary",
        ):
            vuetify3.VBtn("Orbit", value="orbit", size="small")
            vuetify3.VBtn("New York", value="new_york", size="small")
            vuetify3.VBtn("Chicago", value="chicago", size="small")
            vuetify3.VBtn("Denver", value="denver", size="small")
            vuetify3.VBtn("Fit All", value="fit_all", size="small")
        vuetify3.VDivider(vertical=True, classes="mx-2")
        vuetify3.VBtn("Print Camera", click=print_camera, variant="text", size="small")

    with layout.content:
        with html.Div(
            style="position: relative; width: 100%; height: 100%; overflow: hidden;",
        ):
            html.Div(
                id="map-container",
                style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;",
            )

            view = vtk_widgets.VtkSharedView(
                renderWindow,
                ref="vtkView",
                style="display: none;",
                on_ready="window.initMapLibreVTK && window.initMapLibreVTK()",
                view_state_change="window.onVtkViewStateChange && window.onVtkViewStateChange($event)",
            )
            ctrl.view_update = view.update


# Parse command line for initial sync mode
import sys
if '--sync=false' in sys.argv or '--async' in sys.argv:
    state.sync_mode = False
    print("Starting in ASYNC mode")
else:
    state.sync_mode = True
    print("Starting in SYNC mode (default)")

print("Use ?sync=false in URL or 'Toggle Mode' button to switch")

server.start()
