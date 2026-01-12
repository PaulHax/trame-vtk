"""
MapLibre + VTK Shared View Integration Example

This example demonstrates how to use VtkSharedView with an external WebGL context
shared with MapLibre GL JS. VTK renders 3D cones at geographic city locations.

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


async def animate_cones():
    """Animate cone scales with a synced pulsing effect."""
    start_time = time.time()
    while True:
        t = time.time() - start_time
        scale_factor = 1.0 + 0.2 * math.sin(t * 2)
        for actor, base_scale in zip(cone_actors, cone_base_scales):
            current_scale = base_scale * scale_factor
            x, y, z = actor.GetPosition()
            actor.SetScale(current_scale, current_scale, current_scale)
            actor.SetPosition(x, y, current_scale * 0.5)
        ctrl.view_update()
        server.js_call("mapController", "triggerRepaint")
        await asyncio.sleep(1 / 30)


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

# JavaScript initialization with imperative map controller
INIT_SCRIPT_JS = """
(function() {
    let initialized = false;
    let map = null;

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
        // This prevents VTK auto-render from clearing the framebuffer
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
                vtkView.initializeForSharedContext(canvas, gl);
            },
            render: function(gl, args) {
                if (!renderer) return;
                const camera = renderer.getActiveCamera();
                const identity = new Float64Array([
                    1, 0, 0, 0,
                    0, 1, 0, 0,
                    0, 0, 1, 0,
                    0, 0, 0, 1
                ]);
                camera.setViewMatrix(identity);
                // MapLibre 5.x: use defaultProjectionData.mainMatrix
                camera.setProjectionMatrix(args.defaultProjectionData.mainMatrix);
                camera.modified();
                vtkView.renderShared();
            }
        };

        map.addLayer(vtkLayer);

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
        vuetify3.VSpacer()
        vuetify3.VBtn("New York", click=lambda: focus_city("New York"), classes="mx-1")
        vuetify3.VBtn("Chicago", click=lambda: focus_city("Chicago"), classes="mx-1")
        vuetify3.VBtn("Denver", click=lambda: focus_city("Denver"), classes="mx-1")
        vuetify3.VDivider(vertical=True, classes="mx-2")
        vuetify3.VBtn("Fit All", click=fit_all_cities, variant="outlined")
        vuetify3.VBtn("Print Camera", click=print_camera, variant="text")

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
            )
            ctrl.view_update = view.update


server.start()
