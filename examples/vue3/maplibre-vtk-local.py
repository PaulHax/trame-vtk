"""
MapLibre + VTK Local View Integration Example

This example demonstrates how to use VtkLocalView with an external WebGL context
shared with MapLibre GL JS. VTK renders 3D cones at geographic city locations.
"""

from urllib.parse import quote as url_quote

from trame.app import get_server
from trame.widgets import vtk as vtk_widgets, html
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

# City data - positions will be set client-side using MercatorCoordinate
CITIES = [
    {"name": "New York", "color": (1.0, 0.5, 0.0)},
    {"name": "Chicago", "color": (0.5, 1.0, 0.0)},
    {"name": "Denver", "color": (0.0, 0.5, 1.0)},
]

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

    const cities = [
        { name: 'New York', lng: -74.006, lat: 40.7128 },
        { name: 'Chicago', lng: -87.6298, lat: 41.8781 },
        { name: 'Denver', lng: -104.9903, lat: 39.7392 },
    ];

    window.initMapLibreVTK = async function() {
        if (initialized) return;

        const vtkViewRef = window.trame?.refs?.['vtkView'];
        const vtkView = vtkViewRef?.$.setupState;
        if (!vtkView || !window.maplibregl) {
            setTimeout(window.initMapLibreVTK, 100);
            return;
        }

        initialized = true;

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
            center: [-90, 40],
            zoom: 4,
            antialias: true
        });

        await new Promise(resolve => map.on('load', resolve));

        const canvas = map.getCanvas();
        const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');

        // Initialize VTK with MapLibre's WebGL context
        vtkView.initializeWithExternalContext(canvas, gl);

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
        console.log(`Positioned ${actors.length} actors at city locations`);

        // Fit map to show all cities
        const bounds = new maplibregl.LngLatBounds();
        cities.forEach(city => bounds.extend([city.lng, city.lat]));
        map.fitBounds(bounds, { padding: 100 });

        // Use CustomLayerInterface for proper matrix access
        const vtkLayer = {
            id: 'vtk-cones',
            type: 'custom',
            renderingMode: '3d',

            onAdd: function(map, gl) {
                console.log('VTK custom layer added');
            },

            render: function(gl, matrix) {
                try {
                    const camera = renderer.getActiveCamera();

                    // Identity view matrix
                    const identity = new Float64Array([
                        1, 0, 0, 0,
                        0, 1, 0, 0,
                        0, 0, 1, 0,
                        0, 0, 0, 1
                    ]);
                    camera.setViewMatrix(identity);

                    // MapLibre's MVP matrix in column-major format works directly with VTK
                    camera.setProjectionMatrix(matrix);

                    // Force camera to use the new matrices
                    camera.modified();

                    vtkView.saveGLState();
                    vtkView.renderNow();
                    vtkView.restoreGLState();
                } catch (e) {
                    console.error('VTK render error:', e);
                }
            }
        };

        map.addLayer(vtkLayer);
        window.mapLibreMap = map;
        console.log('MapLibre + VTK geo cones initialized');
    };
})();
"""

# Load the init script after MapLibre
server.enable_module({"scripts": [f"data:text/javascript,{url_quote(INIT_SCRIPT_JS)}"]})



with SinglePageLayout(server) as layout:
    layout.title.set_text("MapLibre + VTK Geo Cones")

    with layout.content:
        with html.Div(
            style="position: relative; width: 100%; height: 100%;",
        ):
            # MapLibre container - fills the space
            html.Div(
                id="map-container",
                style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;",
            )

            # VTK Local View - hidden, uses MapLibre's WebGL context
            view = vtk_widgets.VtkLocalView(
                renderWindow,
                ref="vtkView",
                style="display: none;",
                on_ready="window.initMapLibreVTK && window.initMapLibreVTK()",
            )
            ctrl.view_update = view.update


server.start()
