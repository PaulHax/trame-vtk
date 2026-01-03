"""
MapLibre + VTK Shared View Integration Example

This example demonstrates how to use VtkSharedView with an external WebGL context
shared with MapLibre GL JS. VTK renders 3D cones at geographic city locations.

Features bidirectional camera sync between Python and JavaScript:
- Python can control MapLibre camera via map_camera state
- JS camera changes sync back to Python and print to console
"""

from urllib.parse import quote as url_quote

from trame.app import get_server
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

# Initial camera state - will be synced bidirectionally
state.map_camera = {
    "center": [-90, 40],
    "zoom": 4,
    "bearing": 0,
    "pitch": 0,
}

# Track if camera update came from Python to avoid feedback loops
state.camera_update_source = "init"


@state.change("map_camera")
def on_camera_change(map_camera, camera_update_source, **kwargs):
    if camera_update_source == "js":
        print(f"Camera updated from JS: center={map_camera['center']}, "
              f"zoom={map_camera['zoom']:.2f}, bearing={map_camera['bearing']:.1f}, "
              f"pitch={map_camera['pitch']:.1f}", flush=True)


def focus_city(city_name):
    city = next((c for c in CITIES if c["name"] == city_name), None)
    if city:
        with state:
            state.camera_update_source = "python"
            state.map_camera = {
                "center": [city["lng"], city["lat"]],
                "zoom": 8,
                "bearing": 0,
                "pitch": 0,
            }
        print(f"Python focusing on {city_name}", flush=True)


def fit_all_cities():
    with state:
        state.camera_update_source = "python"
        state.map_camera = {
            "center": [-90, 40],
            "zoom": 4,
            "bearing": 0,
            "pitch": 0,
        }
    print("Python fitting all cities", flush=True)

renderer = vtkRenderer()
renderer.SetBackground(0, 0, 0)
renderer.SetBackgroundAlpha(0)

renderWindow = vtkRenderWindow()
renderWindow.AddRenderer(renderer)
renderWindow.OffScreenRenderingOn()

renderWindowInteractor = vtkRenderWindowInteractor()
renderWindowInteractor.SetRenderWindow(renderWindow)
renderWindowInteractor.GetInteractorStyle().SetCurrentStyleToTrackballCamera()

# Create cone actors for each city (pointing up in Z direction)
for city in CITIES:
    cone_source = vtkConeSource()
    cone_source.SetHeight(1.0)
    cone_source.SetRadius(0.5)
    cone_source.SetDirection(0, 0, 1)  # Point upward
    mapper = vtkPolyDataMapper()
    mapper.SetInputConnection(cone_source.GetOutputPort())
    actor = vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(*city["color"])
    renderer.AddActor(actor)

renderer.ResetCamera()
renderWindow.Render()


# MapLibre CDN
maplibre_module = {
    "scripts": ["https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"],
    "styles": ["https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css"],
}
server.enable_module(maplibre_module)

# Self-executing init script - defines window.initMapLibreVTK
INIT_SCRIPT_JS = """
(function() {
    let initialized = false;
    let mapInstance = null;
    let isUpdatingFromPython = false;

    const cities = [
        { name: 'New York', lng: -74.006, lat: 40.7128 },
        { name: 'Chicago', lng: -87.6298, lat: 41.8781 },
        { name: 'Denver', lng: -104.9903, lat: 39.7392 },
    ];

    window.initMapLibreVTK = async function() {
        if (initialized) return;

        const vtkViewRef = window.trame?.refs?.['vtkView'];
        // Access component methods - try direct access first, then exposed, then setupState
        const vtkView = vtkViewRef?.initializeForSharedContext ? vtkViewRef :
                        vtkViewRef?.$.exposed ? vtkViewRef.$.exposed :
                        vtkViewRef?.$.setupState;
        const trame = window.trame;

        if (!vtkView?.initializeForSharedContext || !window.maplibregl || !trame) {
            setTimeout(window.initMapLibreVTK, 100);
            return;
        }

        initialized = true;

        // Get initial camera state
        const initialCamera = trame.state.get('map_camera') || { center: [-90, 40], zoom: 4, bearing: 0, pitch: 0 };

        const map = new maplibregl.Map({
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
            center: initialCamera.center,
            zoom: initialCamera.zoom,
            bearing: initialCamera.bearing,
            pitch: initialCamera.pitch,
            antialias: true
        });

        mapInstance = map;

        await new Promise(resolve => map.on('load', resolve));

        const canvas = map.getCanvas();
        const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');

        // Initialize VTK with MapLibre's WebGL context
        vtkView.initializeForSharedContext(canvas, gl);

        // Get renderer and actors, position them at Mercator coordinates
        const renderer = vtkView.getRenderWindow().getRenderersByReference()[0];
        const actors = renderer.getActors();
        cities.forEach((city, i) => {
            if (i < actors.length) {
                const mercator = maplibregl.MercatorCoordinate.fromLngLat([city.lng, city.lat], 0);
                const scale = mercator.meterInMercatorCoordinateUnits() * 100000; // 100km cones
                actors[i].setPosition(mercator.x, mercator.y, scale * 0.5);
                actors[i].setScale(scale, scale, scale);
            }
        });

        // Fit map to show all cities
        const bounds = new maplibregl.LngLatBounds();
        cities.forEach(city => bounds.extend([city.lng, city.lat]));
        map.fitBounds(bounds, { padding: 100 });

        // Watch for camera changes from Python
        trame.state.watch(['map_camera', 'camera_update_source'], (mapCamera, source) => {
            if (source === 'python' && mapCamera && !isUpdatingFromPython) {
                isUpdatingFromPython = true;
                map.flyTo({
                    center: mapCamera.center,
                    zoom: mapCamera.zoom,
                    bearing: mapCamera.bearing,
                    pitch: mapCamera.pitch,
                    duration: 1000
                });
                setTimeout(() => { isUpdatingFromPython = false; }, 1100);
            }
        });

        // Sync camera back to Python when user moves map
        map.on('moveend', () => {
            if (isUpdatingFromPython) return;
            const center = map.getCenter();
            const newCamera = {
                center: [center.lng, center.lat],
                zoom: map.getZoom(),
                bearing: map.getBearing(),
                pitch: map.getPitch()
            };
            trame.state.set('camera_update_source', 'js');
            trame.state.set('map_camera', newCamera);
        });

        // Use CustomLayerInterface for proper matrix access
        const vtkLayer = {
            id: 'vtk-cones',
            type: 'custom',
            renderingMode: '3d',

            onAdd: function(map, gl) {},

            render: function(gl, matrix) {
                if (!renderer) return;
                const camera = renderer.getActiveCamera();

                // Identity view matrix
                const identity = new Float64Array([
                    1, 0, 0, 0,
                    0, 1, 0, 0,
                    0, 0, 1, 0,
                    0, 0, 0, 1
                ]);
                camera.setViewMatrix(identity);
                camera.setProjectionMatrix(matrix);
                camera.modified();

                vtkView.renderShared();
            }
        };

        map.addLayer(vtkLayer);
    };
})();
"""

# Load the init script after MapLibre
server.enable_module({"scripts": [f"data:text/javascript,{url_quote(INIT_SCRIPT_JS)}"]})



with SinglePageLayout(server) as layout:
    layout.title.set_text("MapLibre + VTK Geo Cones")

    with layout.toolbar:
        vuetify3.VSpacer()
        vuetify3.VBtn("New York", click=lambda: focus_city("New York"), classes="mx-1")
        vuetify3.VBtn("Chicago", click=lambda: focus_city("Chicago"), classes="mx-1")
        vuetify3.VBtn("Denver", click=lambda: focus_city("Denver"), classes="mx-1")
        vuetify3.VDivider(vertical=True, classes="mx-2")
        vuetify3.VBtn("Fit All", click=fit_all_cities, variant="outlined")

    with layout.content:
        with html.Div(
            style="position: relative; width: 100%; height: 100%;",
        ):
            # MapLibre container - fills the space
            html.Div(
                id="map-container",
                style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;",
            )

            # VTK Shared View - hidden, uses MapLibre's WebGL context
            view = vtk_widgets.VtkSharedView(
                renderWindow,
                ref="vtkView",
                style="display: none;",
                on_ready="window.initMapLibreVTK && window.initMapLibreVTK()",
            )
            ctrl.view_update = view.update


server.start()
